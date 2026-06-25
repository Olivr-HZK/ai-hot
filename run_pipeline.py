from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
PYTHON = Path(sys.executable)
SKILL_RUNS_DIR = BASE_DIR / "skill_runs"
HOTSPOTS_FILE = SKILL_RUNS_DIR / "hotspots.json"
MONITOR_DIR = SKILL_RUNS_DIR / "pipeline_monitor"
INS_KEYWORD_DISCOVERY_DIR = SKILL_RUNS_DIR / "instagram_keyword_discovery"
INS_KEYWORD_DISCOVERY_LATEST = INS_KEYWORD_DISCOVERY_DIR / "latest.json"
INS_KEYWORD_DISCOVERY_LOCK = SKILL_RUNS_DIR / "locks" / "ins_keyword_discovery.lock"
TIKTOK_KEYWORD_DISCOVERY_DIR = SKILL_RUNS_DIR / "tiktok_keyword_discovery"
TIKTOK_KEYWORD_DISCOVERY_LATEST = TIKTOK_KEYWORD_DISCOVERY_DIR / "latest.json"
TIKTOK_KEYWORD_DISCOVERY_LOCK = SKILL_RUNS_DIR / "locks" / "tiktok_keyword_discovery.lock"
PLATFORM_OUTPUTS = {
    "tiktok": SKILL_RUNS_DIR / "hotspots_tiktok.json",
    "x": SKILL_RUNS_DIR / "hotspots_x.json",
    "ins": SKILL_RUNS_DIR / "hotspots_ins.json",
}
PLATFORM_SCRIPTS = {
    "tiktok": BASE_DIR / "scripts" / "tiktok_discovery_routes.py",
    "x": BASE_DIR / "scripts" / "phase1_scrape_x.py",
    "ins": BASE_DIR / "scripts" / "instagram" / "phase1_scrape_ins.py",
}

sys.path.insert(0, str(BASE_DIR / "scripts"))
from env_utils import env_bool, env_int, load_env, parse_list
from feedback_rules import detect_media_type, load_feedback_rules, video_haystack
from pipeline_variant import parse_target_date, resolve_pipeline_variant
from scrape_checkpoint import read_latest_status
from ua_geo_targeting import config as ua_geo_config
from ua_geo_targeting import is_ua_geo_candidate
from ua_geo_targeting import ua_geo_details
from ua_material_review import is_ua_material_candidate
from x_team_product_review import hard_reject_review as x_hard_reject_review


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_id_from_now() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_repo_path(raw: str | None, default: Path) -> Path:
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def monitor_paths(run_id: str, env: dict[str, str]) -> tuple[Path, Path]:
    root = resolve_repo_path(env.get("PIPELINE_MONITOR_DIR"), MONITOR_DIR)
    return root / "latest.json", root / "runs" / f"{run_id}.json"


def write_monitor_reports(report: dict[str, Any], env: dict[str, str]) -> None:
    latest_path, archive_path = monitor_paths(str(report.get("runId") or run_id_from_now()), env)
    write_json_atomic(archive_path, report)
    write_json_atomic(latest_path, report)


def run_python(script: Path, *args: str) -> int:
    command = [str(PYTHON), str(script), *args]
    return subprocess.run(command, cwd=BASE_DIR, capture_output=False).returncode


def resolve_platforms(raw: str | None) -> list[str]:
    values = parse_list(raw or os.environ.get("PIPELINE_PLATFORMS") or "tiktok")
    platforms = []
    for value in values:
        platform = value.strip().lower()
        if platform in {"tt", "tik tok"}:
            platform = "tiktok"
        if platform in {"twitter"}:
            platform = "x"
        if platform in {"instagram"}:
            platform = "ins"
        if platform not in PLATFORM_OUTPUTS:
            raise ValueError(f"Unsupported platform: {value}. Supported: tiktok,x,ins")
        if platform not in platforms:
            platforms.append(platform)
    if not platforms:
        raise ValueError("At least one platform must be configured")
    return platforms


def item_key(item: dict) -> str:
    return str(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url") or item.get("upsertKey") or item.get("id") or "").strip()


def heat_value(item: dict) -> float:
    try:
        return float(item.get("heatValue") or 0)
    except (TypeError, ValueError):
        return 0.0


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def dedupe_hotspots(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for item in items:
        key = item_key(item)
        if not key:
            unkeyed.append(item)
            continue
        existing = keyed.get(key)
        if existing is None:
            keyed[key] = item
            continue
        if heat_value(item) > heat_value(existing):
            winner = dict(item)
            if is_tiktok_item(item) and is_tiktok_item(existing):
                if normalize_item_push_object(item) == "ALL" or normalize_item_push_object(existing) == "ALL":
                    winner["pushObject"] = "ALL"
                item_route = str(item.get("tiktokRoute") or "").strip()
                existing_route = str(existing.get("tiktokRoute") or "").strip()
                if item_route and existing_route and item_route != existing_route:
                    winner["tiktokRoute"] = "both"
                    winner["pushObject"] = "ALL"
            keyed[key] = winner
        elif is_tiktok_item(item) and is_tiktok_item(existing):
            if normalize_item_push_object(item) == "ALL" or normalize_item_push_object(existing) == "ALL":
                existing["pushObject"] = "ALL"
            item_route = str(item.get("tiktokRoute") or "").strip()
            existing_route = str(existing.get("tiktokRoute") or "").strip()
            if item_route and existing_route and item_route != existing_route:
                existing["tiktokRoute"] = "both"
                existing["pushObject"] = "ALL"
    return [*keyed.values(), *unkeyed]


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_ins_keyword_discovery_item(item: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    url = str(
        normalized.get("hotspotUrl")
        or normalized.get("webVideoUrl")
        or normalized.get("url")
        or normalized.get("permalink")
        or ""
    ).strip()
    if url:
        normalized["hotspotUrl"] = url
    normalized["hotspotPlatform"] = "Instagram"
    normalized["sourcePlatform"] = "ins"
    normalized["platform"] = "ins"
    normalized["pushObject"] = "ALL"
    normalized["captureSource"] = normalized.get("captureSource") or "ins_keyword_discovery"
    normalized["insKeywordDiscovery"] = {
        "mergedFromDailyDiscovery": True,
        "runId": meta.get("runId", ""),
        "generatedAt": meta.get("generatedAt", ""),
        "approvedPath": meta.get("approvedPath", ""),
    }
    return normalized


def normalize_tiktok_keyword_discovery_item(item: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    url = str(
        normalized.get("hotspotUrl")
        or normalized.get("webVideoUrl")
        or normalized.get("url")
        or normalized.get("permalink")
        or ""
    ).strip()
    if url:
        normalized["hotspotUrl"] = url
    normalized["hotspotPlatform"] = "TikTok"
    normalized["sourcePlatform"] = "tiktok"
    normalized["platform"] = "tiktok"
    normalized["pushObject"] = tiktok_discovery_push_object(normalized)
    normalized["captureSource"] = normalized.get("captureSource") or "tiktok_keyword_discovery"
    normalized["tiktokKeywordDiscovery"] = {
        **(normalized.get("tiktokKeywordDiscovery") if isinstance(normalized.get("tiktokKeywordDiscovery"), dict) else {}),
        "mergedFromDailyDiscovery": True,
        "runId": meta.get("runId", ""),
        "generatedAt": meta.get("generatedAt", ""),
        "approvedPath": meta.get("approvedPath", ""),
    }
    return normalized


def product_heat_screen_passed(item: dict[str, Any]) -> bool:
    for key in ["productPushHeatScreen", "productPushEligibility"]:
        details = item.get(key)
        if isinstance(details, dict) and bool(details.get("passed") or details.get("isEligible")):
            return True
    return False


def tiktok_discovery_push_object(item: dict[str, Any]) -> str:
    return "ALL" if product_heat_screen_passed(item) else "UA"


def is_tiktok_item(item: dict[str, Any]) -> bool:
    platform = str(item.get("hotspotPlatform") or item.get("sourcePlatform") or item.get("platform") or "").strip().lower()
    return platform in {"tiktok", "tik tok"}


def ins_keyword_discovery_status(status: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": True,
        "mergeEnabled": True,
        "status": status,
        "latestPath": relative_path(INS_KEYWORD_DISCOVERY_LATEST),
        "approvedPath": "",
        "generatedAt": "",
        "runId": "",
        "approvedCount": 0,
        "itemCount": 0,
        "error": "",
    }
    payload.update(extra)
    return payload


def tiktok_keyword_discovery_status(status: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "enabled": True,
        "mergeEnabled": True,
        "status": status,
        "latestPath": relative_path(TIKTOK_KEYWORD_DISCOVERY_LATEST),
        "approvedPath": "",
        "generatedAt": "",
        "runId": "",
        "approvedCount": 0,
        "itemCount": 0,
        "error": "",
    }
    payload.update(extra)
    return payload


def load_ins_keyword_discovery_items(env: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    enabled = env_bool("INS_KEYWORD_DISCOVERY_DAILY_ENABLED", False, env)
    merge_enabled = env_bool("INS_KEYWORD_DISCOVERY_MERGE_ENABLED", False, env)
    require_today = env_bool("INS_KEYWORD_DISCOVERY_REQUIRE_TODAY", True, env)
    fails_pipeline = env_bool("INS_KEYWORD_DISCOVERY_FAILS_PIPELINE", False, env)
    latest_path = resolve_repo_path(env.get("INS_KEYWORD_DISCOVERY_LATEST_PATH"), INS_KEYWORD_DISCOVERY_LATEST)
    lock_path = resolve_repo_path(env.get("INS_KEYWORD_DISCOVERY_LOCK_PATH"), INS_KEYWORD_DISCOVERY_LOCK)

    if not enabled or not merge_enabled:
        return [], {
            **ins_keyword_discovery_status("disabled"),
            "enabled": enabled,
            "mergeEnabled": merge_enabled,
            "latestPath": relative_path(latest_path),
        }
    if not latest_path.exists():
        status = "running" if lock_path.exists() else "missing"
        return [], {
            **ins_keyword_discovery_status(status),
            "latestPath": relative_path(latest_path),
            "error": "latest.json not found",
        }
    try:
        report = json.loads(latest_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        status = {
            **ins_keyword_discovery_status("failed"),
            "latestPath": relative_path(latest_path),
            "error": f"failed to read latest.json: {exc}",
        }
        if fails_pipeline:
            raise RuntimeError(status["error"]) from exc
        return [], status
    if not isinstance(report, dict):
        status = {
            **ins_keyword_discovery_status("failed"),
            "latestPath": relative_path(latest_path),
            "error": "latest.json must contain an object",
        }
        if fails_pipeline:
            raise RuntimeError(status["error"])
        return [], status

    generated_at = str(report.get("generatedAt") or report.get("finishedAt") or report.get("startedAt") or "")
    generated_dt = parse_iso_datetime(generated_at)
    base_status = {
        "latestPath": relative_path(latest_path),
        "generatedAt": generated_at,
        "runId": str(report.get("runId") or ""),
        "approvedCount": safe_int(report.get("approvedCount"), 0),
    }
    if require_today and (generated_dt is None or generated_dt.date() != datetime.now().date()):
        status = "running" if lock_path.exists() else "stale"
        return [], {
            **ins_keyword_discovery_status(status),
            **base_status,
            "error": "latest.json is not from today",
        }

    paths = report.get("paths") if isinstance(report.get("paths"), dict) else {}
    approved_raw = str(paths.get("approved") or "")
    if not approved_raw:
        return [], {
            **ins_keyword_discovery_status("success"),
            **base_status,
            "error": "approved path is empty",
        }
    approved_path = resolve_repo_path(approved_raw, INS_KEYWORD_DISCOVERY_DIR / "approved.json")
    if not approved_path.exists():
        status = {
            **ins_keyword_discovery_status("failed"),
            **base_status,
            "approvedPath": relative_path(approved_path),
            "error": "approved.json not found",
        }
        if fails_pipeline:
            raise RuntimeError(status["error"])
        return [], status
    try:
        approved = json.loads(approved_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        status = {
            **ins_keyword_discovery_status("failed"),
            **base_status,
            "approvedPath": relative_path(approved_path),
            "error": f"failed to read approved.json: {exc}",
        }
        if fails_pipeline:
            raise RuntimeError(status["error"]) from exc
        return [], status
    if not isinstance(approved, list):
        status = {
            **ins_keyword_discovery_status("failed"),
            **base_status,
            "approvedPath": relative_path(approved_path),
            "error": "approved.json must contain a list",
        }
        if fails_pipeline:
            raise RuntimeError(status["error"])
        return [], status

    meta = {**base_status, "approvedPath": relative_path(approved_path)}
    items = [
        normalize_ins_keyword_discovery_item(item, meta)
        for item in approved
        if isinstance(item, dict)
    ]
    items = dedupe_hotspots(items)
    return items, {
        **ins_keyword_discovery_status("success"),
        **base_status,
        "approvedPath": relative_path(approved_path),
        "itemCount": len(items),
    }


def load_tiktok_keyword_discovery_items(env: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    enabled = env_bool("TIKTOK_KEYWORD_DISCOVERY_DAILY_ENABLED", False, env)
    merge_enabled = env_bool("TIKTOK_KEYWORD_DISCOVERY_MERGE_ENABLED", False, env)
    require_today = env_bool("TIKTOK_KEYWORD_DISCOVERY_REQUIRE_TODAY", True, env)
    fails_pipeline = env_bool("TIKTOK_KEYWORD_DISCOVERY_FAILS_PIPELINE", False, env)
    latest_path = resolve_repo_path(env.get("TIKTOK_KEYWORD_DISCOVERY_LATEST_PATH"), TIKTOK_KEYWORD_DISCOVERY_LATEST)
    lock_path = resolve_repo_path(env.get("TIKTOK_KEYWORD_DISCOVERY_LOCK_PATH"), TIKTOK_KEYWORD_DISCOVERY_LOCK)

    if not enabled or not merge_enabled:
        return [], {
            **tiktok_keyword_discovery_status("disabled"),
            "enabled": enabled,
            "mergeEnabled": merge_enabled,
            "latestPath": relative_path(latest_path),
        }
    if not latest_path.exists():
        status = "running" if lock_path.exists() else "missing"
        return [], {
            **tiktok_keyword_discovery_status(status),
            "latestPath": relative_path(latest_path),
            "error": "latest.json not found",
        }
    try:
        report = json.loads(latest_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        status = {
            **tiktok_keyword_discovery_status("failed"),
            "latestPath": relative_path(latest_path),
            "error": f"failed to read latest.json: {exc}",
        }
        if fails_pipeline:
            raise RuntimeError(status["error"]) from exc
        return [], status
    if not isinstance(report, dict):
        status = {
            **tiktok_keyword_discovery_status("failed"),
            "latestPath": relative_path(latest_path),
            "error": "latest.json must contain an object",
        }
        if fails_pipeline:
            raise RuntimeError(status["error"])
        return [], status

    generated_at = str(report.get("generatedAt") or report.get("finishedAt") or report.get("startedAt") or "")
    generated_dt = parse_iso_datetime(generated_at)
    base_status = {
        "latestPath": relative_path(latest_path),
        "generatedAt": generated_at,
        "runId": str(report.get("runId") or ""),
        "approvedCount": safe_int(report.get("approvedCount"), 0),
    }
    if str(report.get("status") or "").strip().lower() != "success":
        status = {
            **tiktok_keyword_discovery_status("failed"),
            **base_status,
            "error": str(report.get("error") or "latest run did not finish successfully"),
        }
        if fails_pipeline:
            raise RuntimeError(status["error"])
        return [], status
    if require_today and (generated_dt is None or generated_dt.date() != datetime.now().date()):
        status = "running" if lock_path.exists() else "stale"
        return [], {
            **tiktok_keyword_discovery_status(status),
            **base_status,
            "error": "latest.json is not from today",
        }

    paths = report.get("paths") if isinstance(report.get("paths"), dict) else {}
    approved_raw = str(paths.get("approved") or "")
    if not approved_raw:
        return [], {
            **tiktok_keyword_discovery_status("success"),
            **base_status,
            "error": "approved path is empty",
        }
    approved_path = resolve_repo_path(approved_raw, TIKTOK_KEYWORD_DISCOVERY_DIR / "10_approved.json")
    if not approved_path.exists():
        status = {
            **tiktok_keyword_discovery_status("failed"),
            **base_status,
            "approvedPath": relative_path(approved_path),
            "error": "approved.json not found",
        }
        if fails_pipeline:
            raise RuntimeError(status["error"])
        return [], status
    try:
        approved = json.loads(approved_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        status = {
            **tiktok_keyword_discovery_status("failed"),
            **base_status,
            "approvedPath": relative_path(approved_path),
            "error": f"failed to read approved.json: {exc}",
        }
        if fails_pipeline:
            raise RuntimeError(status["error"]) from exc
        return [], status
    if not isinstance(approved, list):
        status = {
            **tiktok_keyword_discovery_status("failed"),
            **base_status,
            "approvedPath": relative_path(approved_path),
            "error": "approved.json must contain a list",
        }
        if fails_pipeline:
            raise RuntimeError(status["error"])
        return [], status

    meta = {**base_status, "approvedPath": relative_path(approved_path)}
    items = [
        normalize_tiktok_keyword_discovery_item(item, meta)
        for item in approved
        if isinstance(item, dict)
    ]
    items = dedupe_hotspots(items)
    return items, {
        **tiktok_keyword_discovery_status("success"),
        **base_status,
        "approvedPath": relative_path(approved_path),
        "itemCount": len(items),
    }


def item_platform(item: dict) -> str:
    platform = str(item.get("hotspotPlatform") or item.get("sourcePlatform") or item.get("platform") or "").strip().lower()
    if platform in {"tt", "tik tok"}:
        return "tiktok"
    if platform == "twitter":
        return "x"
    return platform


def is_tiktok_ua_geo_candidate(item: dict) -> bool:
    return item_platform(item) == "tiktok" and is_ua_geo_candidate(item)


def is_tiktok_hot_feed_item(item: dict[str, Any]) -> bool:
    if item_platform(item) != "tiktok":
        return False
    values = [
        item.get("captureSource"),
        item.get("sourcePath"),
        item.get("source"),
        item.get("sourceQuery"),
        item.get("searchQuery"),
        item.get("hotFeedProvider"),
    ]
    return any("hot_feed" in str(value or "").strip().lower() for value in values)


def cap_ua_geo_candidates(items: list[dict], *, prefer_tiktok: bool = True, rules: dict[str, Any] | None = None) -> list[dict]:
    rules = rules or load_feedback_rules()
    cfg = ua_geo_config(rules)
    daily_max = int(cfg.get("daily_max", 3) or 3)
    daily_min = int(cfg.get("daily_min", 1) or 1)
    if daily_max <= 0:
        return [item for item in items if not is_ua_geo_candidate(item) or is_ua_material_candidate(item)]
    regular: list[dict] = []
    tiktok_geo: list[dict] = []
    other_geo: list[dict] = []
    for item in items:
        if is_tiktok_hot_feed_item(item) or is_ua_material_candidate(item):
            regular.append(item)
        elif is_tiktok_ua_geo_candidate(item):
            tiktok_geo.append(item)
        elif is_ua_geo_candidate(item):
            other_geo.append(item)
        else:
            regular.append(item)
    if prefer_tiktok:
        selected_geo = sorted(tiktok_geo, key=heat_value, reverse=True)[:daily_max]
        if len(selected_geo) < daily_max:
            selected_geo.extend(
                sorted(other_geo, key=heat_value, reverse=True)[: daily_max - len(selected_geo)]
            )
    else:
        selected_geo = sorted([*tiktok_geo, *other_geo], key=heat_value, reverse=True)[:daily_max]
    if prefer_tiktok and len(tiktok_geo) < daily_min:
        log(f"TikTok UA geo targeting: only {len(tiktok_geo)} candidates passed filters; minimum target is {daily_min}")
    selected_geo_keys = {item_key(item) for item in selected_geo if item_key(item)}
    regular = [item for item in regular if item_key(item) not in selected_geo_keys]
    return [*regular, *selected_geo]


def normalize_push_object(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"all", "aii"}:
        return "ALL"
    if text == "ua":
        return "UA"
    return "UA"


def is_tiktok_product_route_item(item: dict[str, Any]) -> bool:
    route = str(item.get("tiktokRoute") or "").strip().lower()
    if route in {"product", "both"}:
        return True
    details = item.get("tiktokProductRoute")
    return isinstance(details, dict)


def normalize_item_push_object(item: dict[str, Any]) -> str:
    if is_tiktok_item(item) and not product_heat_screen_passed(item) and not is_tiktok_product_route_item(item):
        return "UA"
    return normalize_push_object(item.get("pushObject"))


def has_product_side(item: dict[str, Any]) -> bool:
    return normalize_item_push_object(item) == "ALL"


def has_ua_side(item: dict[str, Any]) -> bool:
    return normalize_item_push_object(item) in {"UA", "ALL"}


def push_caps_config(rules: dict[str, Any]) -> dict[str, Any]:
    defaults = {
        "enabled": True,
        "total_daily_max": 15,
    }
    configured = rules.get("push_caps", {})
    if isinstance(configured, dict):
        defaults.update({key: value for key, value in configured.items() if value is not None})
    return defaults


def cap_value(config: dict[str, Any], key: str, default: int) -> int:
    try:
        return max(0, int(config.get(key, default)))
    except (TypeError, ValueError):
        return default


def explicit_video_media_type(item: dict[str, Any]) -> str:
    raw_source = item.get("raw_source") if isinstance(item.get("raw_source"), dict) else {}
    values: list[Any] = []
    for key in ["mediaType", "media_type", "type", "contentType", "content_type"]:
        value = item.get(key) or raw_source.get(key)
        if value:
            values.append(value)
    for key in ["media_types", "mediaTypes"]:
        value = item.get(key) or raw_source.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value:
            values.append(value)
    normalized = " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())
    has_video = any(token in normalized for token in ["video", "reel", "gif"])
    has_image = any(token in normalized for token in ["photo", "image", "carousel", "album"])
    if has_video and has_image:
        return "mixed"
    if has_video:
        return "video"
    return ""


def is_product_video(item: dict[str, Any]) -> bool:
    if not has_product_side(item):
        return False
    explicit = explicit_video_media_type(item)
    if explicit in {"video", "mixed"}:
        return True
    media_type = detect_media_type(item)
    if media_type in {"video", "mixed"}:
        return True
    haystack = video_haystack(item, include_summary=True)
    video_markers = [
        "photo to video",
        "image to video",
        "ai video",
        "video generator",
        "video template",
        "storyboard",
        "static to motion",
        "animate photo",
        "talking photo",
        "face animation",
        "图生视频",
        "照片转视频",
        "视频模板",
    ]
    return any(marker in haystack for marker in video_markers)


def is_ua_geo_counted(item: dict[str, Any], rules: dict[str, Any]) -> bool:
    if not has_ua_side(item):
        return False
    details = item.get("uaGeoTargeting")
    if isinstance(details, dict) and bool(details.get("isTarget")):
        return True
    try:
        return bool(ua_geo_details(item, rules).get("isTarget"))
    except Exception:
        return False


def apply_push_caps(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = push_caps_config(rules)
    normalized = [{**item, "pushObject": normalize_item_push_object(item)} for item in sorted(items, key=heat_value, reverse=True)]
    tiktok_items = [item for item in normalized if is_tiktok_item(item)]
    capped_items = [item for item in normalized if not is_tiktok_item(item)]
    if not cfg.get("enabled", True):
        return normalized
    total_max = cap_value(cfg, "total_daily_max", 15)
    if total_max <= 0:
        log(f"Push caps: kept {len(tiktok_items)}/{len(normalized)} (non-TikTok total_daily_max=0; TikTok bypassed)")
        return tiktok_items
    kept_capped = capped_items[:total_max]
    if len(kept_capped) != len(capped_items):
        log(
            f"Push caps: kept {len(kept_capped)}/{len(capped_items)} non-TikTok "
            f"(total_daily_max={total_max}); TikTok bypassed={len(tiktok_items)}; "
            f"skipped total_daily_max={len(capped_items) - len(kept_capped)}"
        )
    return sorted([*kept_capped, *tiktok_items], key=heat_value, reverse=True)


def apply_final_guardrails(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    for item in items:
        platform = str(item.get("hotspotPlatform") or item.get("sourcePlatform") or item.get("platform") or "").strip().lower()
        if platform in {"x", "twitter"}:
            reject = x_hard_reject_review(item, "final_guardrail")
            if reject:
                skipped["x_hard_reject"] = skipped.get("x_hard_reject", 0) + 1
                continue
        kept.append(item)
    if skipped:
        skipped_text = ", ".join(f"{reason}={count}" for reason, count in sorted(skipped.items()))
        log(f"Final guardrails: kept {len(kept)}/{len(items)}; skipped {skipped_text}")
    return kept


def load_platform_items(platform: str) -> list[dict[str, Any]]:
    path = PLATFORM_OUTPUTS[platform]
    if not path.exists():
        raise FileNotFoundError(f"Platform hotspots file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError(f"Platform hotspots JSON must contain a list: {path}")
    return [item for item in data if isinstance(item, dict)]


def merge_hotspots(platforms: list[str], output_path: Path | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    output_path = output_path or HOTSPOTS_FILE
    merged = []
    for platform in platforms:
        merged.extend(load_platform_items(platform))
    tiktok_keyword_status = {
        **tiktok_keyword_discovery_status("disabled"),
        "enabled": False,
        "mergeEnabled": False,
        "error": "TikTok Discovery is merged through tiktok-UA/tiktok-Product route outputs in the main pipeline",
    }
    ins_keyword_items, ins_keyword_status = load_ins_keyword_discovery_items(env or {})
    if ins_keyword_items:
        log(f"INS keyword discovery: merging {len(ins_keyword_items)} approved items")
        merged.extend(ins_keyword_items)
    elif ins_keyword_status.get("status") not in {"disabled", "success"}:
        log(f"INS keyword discovery: {ins_keyword_status.get('status')} ({ins_keyword_status.get('error')})")
    rules = load_feedback_rules()
    merged = dedupe_hotspots(merged)
    merged = apply_final_guardrails(merged)
    merged = dedupe_hotspots(merged)
    merged = apply_push_caps(merged, rules)
    merged = sorted(merged, key=heat_value, reverse=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "count": len(merged),
        "tiktokKeywordDiscovery": tiktok_keyword_status,
        "insKeywordDiscovery": ins_keyword_status,
    }


def platform_timeout_seconds(platform: str, env: dict[str, str]) -> int:
    default = env_int("PIPELINE_PLATFORM_TIMEOUT_SECONDS", 5400, env)
    key = f"PIPELINE_{platform.upper()}_TIMEOUT_SECONDS"
    return max(0, env_int(key, default, env))


def platform_log_path(platform: str, run_id: str) -> Path:
    return SKILL_RUNS_DIR / "logs" / f"platform_{platform}_{run_id}.log"


def terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=30,
            )
            if completed.returncode != 0 and process.poll() is None:
                try:
                    process.kill()
                except Exception:
                    pass
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
    else:
        try:
            process.kill()
        except Exception:
            pass
    if process.poll() is None:
        try:
            process.kill()
        except Exception:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def validate_platform_output(platform: str) -> tuple[str, int]:
    try:
        items = load_platform_items(platform)
    except Exception as exc:
        return str(exc), 0
    return "", len(items)


def enrich_with_scrape_status(result: dict[str, Any], platform: str, run_id: str, env: dict[str, str], *, skip_scrape: bool) -> None:
    if skip_scrape:
        result["scrapeStatus"] = "skipped"
        return
    status = read_latest_status(platform, env)
    if not status:
        result["scrapeStatus"] = ""
        return
    if status.get("runId") and str(status.get("runId")) != run_id:
        result["scrapeStatus"] = ""
        return
    scrape_status = str(status.get("status") or "")
    result["scrapeStatus"] = scrape_status
    if status.get("checkpointPath"):
        result["checkpointPath"] = relative_path(Path(str(status["checkpointPath"])))
    if status.get("error"):
        result["partialReason"] = str(status.get("error") or "")


def platform_headless_args(platform: str, env: dict[str, str]) -> list[str]:
    if platform != "tiktok" or "TIKTOK_DISCOVERY_HEADLESS" not in env:
        return []
    return ["--headless"] if env_bool("TIKTOK_DISCOVERY_HEADLESS", True, env) else ["--headed"]


def build_platform_command(platform: str, *, skip_scrape: bool, env: dict[str, str]) -> list[str]:
    script = PLATFORM_SCRIPTS[platform]
    output_path = PLATFORM_OUTPUTS[platform]
    command = [str(PYTHON), str(script), "--output", str(output_path)]
    if skip_scrape:
        command.insert(2, "--skip-scrape")
    command.extend(platform_headless_args(platform, env))
    return command


def run_platform(platform: str, *, run_id: str, skip_scrape: bool, env: dict[str, str]) -> dict[str, Any]:
    script = PLATFORM_SCRIPTS[platform]
    output_path = PLATFORM_OUTPUTS[platform]
    timeout_seconds = platform_timeout_seconds(platform, env)
    log_path = platform_log_path(platform, run_id)
    command = build_platform_command(platform, skip_scrape=skip_scrape, env=env)
    result: dict[str, Any] = {
        "platform": platform,
        "status": "failed",
        "exitCode": None,
        "durationSeconds": 0.0,
        "timeoutSeconds": timeout_seconds,
        "outputPath": relative_path(output_path),
        "itemCount": 0,
        "logPath": relative_path(log_path),
        "scrapeStatus": "skipped" if skip_scrape else "",
        "checkpointPath": "",
        "partialReason": "",
        "error": "",
    }
    started = time.monotonic()
    try:
        output_path.unlink(missing_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        child_env = {**env, **os.environ, "PIPELINE_RUN_ID": run_id}
        with log_path.open("w", encoding="utf-8") as log_file:
            log_file.write(f"[{now_iso()}] Starting platform={platform}\n")
            log_file.write(f"Command: {' '.join(command)}\n\n")
            log_file.flush()
            process = subprocess.Popen(command, cwd=BASE_DIR, stdout=log_file, stderr=subprocess.STDOUT, env=child_env)
            try:
                exit_code = process.wait(timeout=timeout_seconds if timeout_seconds > 0 else None)
            except subprocess.TimeoutExpired:
                terminate_process_tree(process)
                result["status"] = "timeout"
                result["error"] = f"Platform {platform} exceeded timeout of {timeout_seconds}s"
                log_file.write(f"\n[{now_iso()}] TIMEOUT after {timeout_seconds}s\n")
            else:
                result["exitCode"] = exit_code
                enrich_with_scrape_status(result, platform, run_id, child_env, skip_scrape=skip_scrape)
                if exit_code == 0:
                    output_error, item_count = validate_platform_output(platform)
                    result["itemCount"] = item_count
                    if output_error:
                        result["status"] = "output_error"
                        result["error"] = output_error
                    elif result.get("scrapeStatus") == "partial":
                        result["status"] = "partial_success"
                    else:
                        result["status"] = "success"
                else:
                    result["status"] = "failed"
                    result["error"] = f"Platform {platform} failed with exit code {exit_code}"
                log_file.write(f"\n[{now_iso()}] Finished status={result['status']} exitCode={exit_code}\n")
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = str(exc)
    finally:
        if not result.get("scrapeStatus"):
            enrich_with_scrape_status(result, platform, run_id, env, skip_scrape=skip_scrape)
        result["durationSeconds"] = round(time.monotonic() - started, 2)
    return result


def run_platforms(platforms: list[str], *, run_id: str, skip_scrape: bool, env: dict[str, str]) -> list[dict[str, Any]]:
    parallel = env_bool("PIPELINE_PARALLEL_PLATFORMS", True, env)
    max_workers = max(1, env_int("PIPELINE_MAX_WORKERS", 3, env))
    max_workers = min(max_workers, len(platforms))
    results_by_platform: dict[str, dict[str, Any]] = {}
    if not parallel or max_workers == 1:
        for platform in platforms:
            log(f"Stage 1/{platform}: running isolated platform task")
            result = run_platform(platform, run_id=run_id, skip_scrape=skip_scrape, env=env)
            log(f"Stage 1/{platform}: {result['status']} ({result['itemCount']} items)")
            results_by_platform[platform] = result
        return [results_by_platform[platform] for platform in platforms]

    log(f"Stage 1: running {len(platforms)} platform tasks in parallel (max_workers={max_workers})")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_platform = {
            executor.submit(run_platform, platform, run_id=run_id, skip_scrape=skip_scrape, env=env): platform
            for platform in platforms
        }
        for future in as_completed(future_to_platform):
            platform = future_to_platform[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "platform": platform,
                    "status": "failed",
                    "exitCode": None,
                    "durationSeconds": 0.0,
                    "timeoutSeconds": platform_timeout_seconds(platform, env),
                    "outputPath": relative_path(PLATFORM_OUTPUTS[platform]),
                    "itemCount": 0,
                    "logPath": relative_path(platform_log_path(platform, run_id)),
                    "scrapeStatus": "",
                    "checkpointPath": "",
                    "partialReason": "",
                    "error": str(exc),
                }
            log(f"Stage 1/{platform}: {result['status']} ({result['itemCount']} items)")
            results_by_platform[platform] = result
    return [results_by_platform[platform] for platform in platforms]


def successful_platforms(results: list[dict[str, Any]]) -> list[str]:
    return [str(result["platform"]) for result in results if result.get("status") in {"success", "partial_success"}]


def failed_platforms(results: list[dict[str, Any]]) -> list[str]:
    return [str(result["platform"]) for result in results if result.get("status") not in {"success", "partial_success"}]


def build_initial_report(run_id: str, started_at: str, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "runId": run_id,
        "startedAt": started_at,
        "finishedAt": "",
        "status": "failed",
        "variant": "",
        "platformsRequested": [],
        "platformsSucceeded": [],
        "platformsFailed": [],
        "hotspotsPath": relative_path(HOTSPOTS_FILE),
        "hotspotCount": 0,
        "skipFeishu": bool(args.skip_feishu),
        "feishuStatus": "skipped",
        "error": "",
        "platformResults": [],
        "tiktokKeywordDiscovery": {},
        "insKeywordDiscovery": {},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Social Media Hotspots TT v1 pipeline")
    parser.add_argument("--skip-feedback", action="store_true", help="Skip Feishu feedback rule optimization")
    parser.add_argument("--skip-scrape", action="store_true", help="Reuse existing platform filtered-result.json files")
    parser.add_argument("--skip-feishu", action="store_true", help="Skip Feishu webhook and bitable write")
    parser.add_argument("--dry-run-feishu", action="store_true", help="Build Feishu payload/records without sending")
    parser.add_argument("--platforms", help="Comma-separated platforms to run: tiktok,x,ins")
    parser.add_argument("--variant", choices=["legacy", "product_v2", "auto"], help="Filtering logic variant. auto uses even-day legacy and odd-day product_v2")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = run_id_from_now()
    started_at = now_iso()
    report = build_initial_report(run_id, started_at, args)
    env = {**load_env(), **os.environ}
    exit_code = 1
    try:
        variant = resolve_pipeline_variant(args.variant or os.environ.get("PIPELINE_VARIANT", "auto"), target_date=parse_target_date())
        os.environ["PIPELINE_VARIANT"] = variant
        report["variant"] = variant
        log(f"Pipeline variant: {variant}")
        try:
            platforms = resolve_platforms(args.platforms)
        except ValueError as exc:
            report["error"] = str(exc)
            print(f"ERROR: {exc}")
            return 1
        report["platformsRequested"] = platforms
        SKILL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        if not args.skip_feedback:
            log("Stage 0: optimizing rules from Feishu feedback")
            code = run_python(BASE_DIR / "feedback_loop" / "optimizer.py")
            if code != 0:
                report["error"] = f"Stage 0 feedback optimizer failed with exit code {code}"
                return code
        else:
            log("Stage 0 skipped")

        log(f"Stage 1: scraping and scoring hotspots for {','.join(platforms)}")
        platform_results = run_platforms(platforms, run_id=run_id, skip_scrape=args.skip_scrape, env=env)
        report["platformResults"] = platform_results
        succeeded = successful_platforms(platform_results)
        failed = failed_platforms(platform_results)
        partial = any(result.get("status") == "partial_success" for result in platform_results)
        report["platformsSucceeded"] = succeeded
        report["platformsFailed"] = failed

        continue_on_failure = env_bool("PIPELINE_CONTINUE_ON_PLATFORM_FAILURE", True, env)
        if failed and not continue_on_failure:
            report["error"] = f"Platform failure blocked merge: {','.join(failed)}"
            return 1

        merge_result = merge_hotspots(succeeded, env=env)
        merged_count = int(merge_result.get("count") or 0)
        report["tiktokKeywordDiscovery"] = merge_result.get("tiktokKeywordDiscovery", {})
        report["insKeywordDiscovery"] = merge_result.get("insKeywordDiscovery", {})
        report["hotspotCount"] = merged_count
        log(f"Stage 1: merged {merged_count} hotspots into {HOTSPOTS_FILE}")
        if merged_count <= 0:
            report["error"] = "No usable hotspots after merge"
            return 1

        if args.skip_feishu:
            report["status"] = "success" if not failed and not partial else "partial_success"
            log("Stage 2 skipped")
            exit_code = 0
            return 0

        log("Stage 2: pushing card and writing Feishu bitable")
        feishu_args = ["--hotspots", str(HOTSPOTS_FILE)]
        if args.dry_run_feishu:
            feishu_args.append("--dry-run")
        feishu_code = run_python(BASE_DIR / "scripts" / "feishu_push.py", *feishu_args)
        if feishu_code != 0:
            report["feishuStatus"] = "failed"
            report["error"] = f"Feishu push/write failed with exit code {feishu_code}"
            return feishu_code
        report["feishuStatus"] = "success"
        report["status"] = "success" if not failed and not partial else "partial_success"
        exit_code = 0
        return 0
    except Exception as exc:
        report["error"] = str(exc)
        print(f"ERROR: {exc}")
        return 1
    finally:
        if report.get("status") == "failed" and report.get("hotspotCount", 0) > 0 and report.get("error") == "":
            has_partial = any(result.get("status") == "partial_success" for result in report.get("platformResults", []))
            report["status"] = "success" if not report.get("platformsFailed") and not has_partial else "partial_success"
        report["finishedAt"] = now_iso()
        if exit_code != 0 and not report.get("error"):
            report["error"] = f"Pipeline exited with code {exit_code}"
        try:
            write_monitor_reports(report, env)
            latest_path, archive_path = monitor_paths(str(report["runId"]), env)
            log(f"Monitor report written: {latest_path} ({archive_path})")
        except Exception as exc:
            print(f"ERROR: failed to write monitor report: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
