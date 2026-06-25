from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
PYTHON = Path(sys.executable)
SKILL_RUNS_DIR = BASE_DIR / "skill_runs"
DISCOVERY_ROOT = SKILL_RUNS_DIR / "tiktok_keyword_discovery"
DEFAULT_LAYER_CONFIG = BASE_DIR / "references" / "tiktok_discovery_keyword_layers.json"
DANCE_LAYER_CONFIG = SKILL_RUNS_DIR / "tiktok_keyword_discovery" / "manual_configs" / "dance_trend_20260615_layer.json"
UA_OUTPUT = SKILL_RUNS_DIR / "hotspots_tiktok_ua.json"
PRODUCT_OUTPUT = SKILL_RUNS_DIR / "hotspots_tiktok_product.json"
ROUTE_REPORT_DIR = SKILL_RUNS_DIR / "tiktok_discovery_routes"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_id_from_now() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    except ValueError:
        return str(path)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def item_key(item: dict[str, Any]) -> str:
    return str(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url") or item.get("upsertKey") or item.get("id") or "").strip()


def heat_value(item: dict[str, Any]) -> float:
    try:
        return float(item.get("heatValue") or 0)
    except (TypeError, ValueError):
        return 0.0


def product_heat_screen_passed(item: dict[str, Any]) -> bool:
    for key in ["productPushHeatScreen", "productPushEligibility"]:
        details = item.get(key)
        if isinstance(details, dict) and bool(details.get("passed") or details.get("isEligible")):
            return True
    return False


def normalize_platform_fields(item: dict[str, Any]) -> dict[str, Any]:
    updated = dict(item)
    url = item_key(updated)
    if url:
        updated["hotspotUrl"] = url
    updated["hotspotPlatform"] = "TikTok"
    updated["sourcePlatform"] = "tiktok"
    updated["platform"] = "tiktok"
    updated["captureSource"] = updated.get("captureSource") or "tiktok_keyword_discovery"
    return updated


def normalize_ua_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items:
        updated = normalize_platform_fields(item)
        updated["pushObject"] = "UA"
        updated["tiktokRoute"] = "ua"
        normalized.append(updated)
    return dedupe_by_url(normalized)


def normalize_product_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items:
        updated = normalize_platform_fields(item)
        updated["pushObject"] = "ALL"
        updated["tiktokRoute"] = "product"
        normalized.append(updated)
    return dedupe_by_url(normalized)


def dedupe_by_url(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for item in items:
        key = item_key(item)
        if not key:
            unkeyed.append(item)
            continue
        existing = keyed.get(key)
        if existing is None or heat_value(item) > heat_value(existing):
            keyed[key] = item
    return [*keyed.values(), *unkeyed]


def select_ua_product_handoff(ua_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [item for item in ua_items if product_heat_screen_passed(item)]
    if not eligible:
        return None
    selected = sorted(eligible, key=heat_value, reverse=True)[0]
    handoff = normalize_platform_fields(selected)
    handoff["pushObject"] = "ALL"
    handoff["tiktokRoute"] = "product"
    handoff["submittedFrom"] = "tiktok-UA"
    handoff["tiktokProductAudit"] = {
        "submittedFrom": "tiktok-UA",
        "method": "product_push_heat_screen",
        "passed": True,
        "reason": "UA route item passed product push heat screen",
    }
    return handoff


def merge_product_handoff(product_items: list[dict[str, Any]], handoff: dict[str, Any] | None) -> list[dict[str, Any]]:
    if handoff is None:
        return product_items
    keyed = {item_key(item): item for item in product_items if item_key(item)}
    key = item_key(handoff)
    if key and key in keyed:
        existing = dict(keyed[key])
        existing["submittedFrom"] = "tiktok-UA"
        existing["tiktokProductAudit"] = handoff.get("tiktokProductAudit")
        keyed[key] = existing
        return [*keyed.values(), *[item for item in product_items if not item_key(item)]]
    return [*product_items, handoff]


def merge_route_outputs(ua_items: list[dict[str, Any]], product_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keyed: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for item in ua_items:
        key = item_key(item)
        if key:
            keyed[key] = dict(item)
        else:
            unkeyed.append(dict(item))
    for item in product_items:
        key = item_key(item)
        product_item = dict(item)
        product_item["pushObject"] = "ALL"
        if not key:
            unkeyed.append(product_item)
            continue
        existing = keyed.get(key)
        if existing is None:
            keyed[key] = product_item
            continue
        merged = dict(existing)
        for field, value in product_item.items():
            if value not in ("", None, [], {}):
                merged[field] = value
        merged["pushObject"] = "ALL"
        merged["tiktokRoute"] = "both"
        keyed[key] = merged
    merged_items = [*keyed.values(), *unkeyed]
    return sorted(merged_items, key=heat_value, reverse=True)


def discovery_report_path(run_id: str) -> Path:
    return DISCOVERY_ROOT / "runs" / run_id / "report.json"


def approved_path_from_report(report: dict[str, Any], run_id: str) -> Path:
    paths = report.get("paths") if isinstance(report.get("paths"), dict) else {}
    raw = str(paths.get("approved") or "")
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else BASE_DIR / path
    return DISCOVERY_ROOT / "runs" / run_id / "10_approved.json"


def apply_headless_override(command: list[str], headless: bool | None) -> list[str]:
    if headless is None:
        return command
    if headless:
        return [*command, "--headless", "--detail-headless"]
    return [*command, "--visible-browser", "--visible-detail-browser"]


def run_discovery_route(route: str, run_id: str, env: dict[str, str], *, headless: bool | None = None) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    if route == "ua":
        command = [
            str(PYTHON),
            str(SCRIPT_DIR / "tiktok_keyword_discovery.py"),
            "--run-id",
            run_id,
            "--stage",
            "all",
            "--layered-keywords",
            "--external-sources",
            "--layer-config",
            str(DEFAULT_LAYER_CONFIG),
            "--stage4-profile",
            "ua",
        ]
    else:
        command = [
            str(PYTHON),
            str(SCRIPT_DIR / "tiktok_keyword_discovery.py"),
            "--run-id",
            run_id,
            "--stage",
            "all",
            "--layered-keywords",
            "--no-external-sources",
            "--layer-config",
            str(DANCE_LAYER_CONFIG),
            "--stage4-profile",
            "product",
        ]
    command = apply_headless_override(command, headless)
    exit_code = subprocess.run(command, cwd=BASE_DIR, env=env, capture_output=False).returncode
    report = read_json(discovery_report_path(run_id), {})
    if exit_code != 0 or not isinstance(report, dict) or report.get("status") != "success":
        return [], report if isinstance(report, dict) else {}, exit_code or 1
    approved = read_json(approved_path_from_report(report, run_id), [])
    return [item for item in approved if isinstance(item, dict)], report, 0


def write_route_report(report: dict[str, Any]) -> None:
    run_id = str(report.get("runId") or run_id_from_now())
    write_json(ROUTE_REPORT_DIR / "runs" / f"{run_id}.json", report)
    write_json(ROUTE_REPORT_DIR / "latest.json", report)


def product_per_window_limit() -> int:
    try:
        return max(0, int(os.environ.get("TIKTOK_PRODUCT_PER_WINDOW_LIMIT", "1") or 1))
    except (TypeError, ValueError):
        return 1


def parse_routes(raw: str | None = None) -> list[str]:
    value = str(raw if raw is not None else os.environ.get("TIKTOK_DISCOVERY_ROUTES", "ua,product")).strip().lower()
    if value in {"", "all", "both", "default"}:
        value = "ua,product"
    aliases = {
        "tiktok-ua": "ua",
        "tiktok_ua": "ua",
        "tiktok-product": "product",
        "tiktok_product": "product",
    }
    routes: list[str] = []
    for part in value.replace("+", ",").split(","):
        route = aliases.get(part.strip(), part.strip())
        if not route:
            continue
        if route not in {"ua", "product"}:
            raise ValueError(f"Unsupported TikTok discovery route: {route}. Supported: ua,product")
        if route not in routes:
            routes.append(route)
    if not routes:
        raise ValueError("At least one TikTok discovery route must be configured")
    return routes


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TikTok main pipeline through Discovery UA/Product routes")
    parser.add_argument("--output", type=Path, default=SKILL_RUNS_DIR / "hotspots_tiktok.json")
    parser.add_argument("--skip-scrape", action="store_true", help="Reuse existing route output files")
    parser.add_argument("--run-id")
    parser.add_argument("--routes", help="Comma-separated TikTok discovery routes: ua,product. Defaults to TIKTOK_DISCOVERY_ROUTES or ua,product")
    parser.add_argument("--headless", dest="headless", action="store_true", default=None)
    parser.add_argument("--headed", "--visible-browser", dest="headless", action="store_false")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    routes = parse_routes(args.routes)
    pipeline_run_id = args.run_id or os.environ.get("PIPELINE_RUN_ID") or run_id_from_now()
    started_at = now_iso()
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "runId": pipeline_run_id,
        "startedAt": started_at,
        "finishedAt": "",
        "status": "failed",
        "routes": {},
        "outputs": {
            "ua": relative_path(UA_OUTPUT),
            "product": relative_path(PRODUCT_OUTPUT),
            "merged": relative_path(args.output),
        },
        "requestedRoutes": routes,
        "handoffUrl": "",
        "itemCount": 0,
        "error": "",
    }
    try:
        ua_items: list[dict[str, Any]] = []
        product_items: list[dict[str, Any]] = []
        handoff: dict[str, Any] | None = None
        if args.skip_scrape:
            if "ua" in routes:
                ua_items = normalize_ua_items(read_json(UA_OUTPUT, []))
                report["routes"]["ua"] = {"status": "reused", "itemCount": len(ua_items)}
            else:
                report["routes"]["ua"] = {"status": "skipped", "itemCount": 0}
            if "product" in routes:
                product_items = normalize_product_items(read_json(PRODUCT_OUTPUT, []))
                report["routes"]["product"] = {"status": "reused", "itemCount": len(product_items)}
            else:
                report["routes"]["product"] = {"status": "skipped", "itemCount": 0}
        else:
            env = {**os.environ, "PIPELINE_RUN_ID": pipeline_run_id}
            ua_run_id = f"{pipeline_run_id}_tiktok_ua"
            product_run_id = f"{pipeline_run_id}_tiktok_product"
            if "ua" in routes:
                ua_raw, ua_report, ua_code = run_discovery_route("ua", ua_run_id, env, headless=args.headless)
                report["routes"]["ua"] = {
                    "status": "success" if ua_code == 0 else "failed",
                    "runId": ua_run_id,
                    "itemCount": len(ua_raw),
                    "reportPath": relative_path(discovery_report_path(ua_run_id)),
                    "error": ua_report.get("error", "") if isinstance(ua_report, dict) else "",
                }
                if ua_code != 0:
                    report["error"] = f"TikTok UA Discovery route failed with exit code {ua_code}"
                    return ua_code
                ua_items = normalize_ua_items(ua_raw)
                handoff = select_ua_product_handoff(ua_items)
                if handoff:
                    report["handoffUrl"] = item_key(handoff)
            else:
                report["routes"]["ua"] = {"status": "skipped", "itemCount": 0}
            if "product" in routes:
                product_raw, product_report, product_code = run_discovery_route("product", product_run_id, env, headless=args.headless)
                report["routes"]["product"] = {
                    "status": "success" if product_code == 0 else "failed",
                    "runId": product_run_id,
                    "itemCount": len(product_raw),
                    "reportPath": relative_path(discovery_report_path(product_run_id)),
                    "perWindowLimit": product_per_window_limit(),
                    "error": product_report.get("error", "") if isinstance(product_report, dict) else "",
                }
                if product_code != 0:
                    report["error"] = f"TikTok Product Discovery route failed with exit code {product_code}"
                    return product_code
                product_items = normalize_product_items(product_raw)
                product_items = merge_product_handoff(product_items, handoff)
            else:
                report["routes"]["product"] = {"status": "skipped", "itemCount": 0, "perWindowLimit": product_per_window_limit()}

        merged = merge_route_outputs(ua_items, product_items)
        write_json(UA_OUTPUT, ua_items)
        write_json(PRODUCT_OUTPUT, product_items)
        write_json(args.output, merged)
        report["itemCount"] = len(merged)
        report["routes"]["ua"]["normalizedItemCount"] = len(ua_items)
        report["routes"]["product"]["normalizedItemCount"] = len(product_items)
        report["status"] = "success"
        return 0
    except Exception as exc:
        report["error"] = str(exc)
        print(f"ERROR: {exc}", flush=True)
        return 1
    finally:
        report["finishedAt"] = now_iso()
        write_route_report(report)


if __name__ == "__main__":
    raise SystemExit(main())
