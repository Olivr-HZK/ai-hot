from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from ai_intro import apply_ai_intros
from audience_targeting import apply_audience_targeting
from comment_enrichment import enrich_top_comments
from env_utils import load_env
from feedback_hard_filter import apply_feedback_hard_filter
from feedback_rules import (
    detect_media_type,
    is_excluded_by_rules,
    keyword_hits,
    load_feedback_rules,
    ranking_score,
    video_haystack,
    x_photo_relevance_details,
)
from pipeline_variant import mark_pipeline_variant, resolve_pipeline_variant
from product_targeting import product_fit_details
from scrape_checkpoint import partial_continue_enabled, read_latest_status
from scoring import heat_score, published_days, safe_int
from ua_material_review import (
    blocked_review,
    config as ua_material_review_config,
    review_model,
    review_with_model,
)
from visual_dedupe import apply_visual_dedupe
from x_safety_review import apply_x_image_safety_review
from x_team_product_review import apply_x_team_product_review


SCRAPER_DIR = BASE_DIR / "trend-scrap" / "x-scraper"
DATA_FILE = SCRAPER_DIR / "data" / "filtered-result.json"
SCRAPER_ENTRY = SCRAPER_DIR / "src" / "scraper.js"
SKILL_RUNS_DIR = BASE_DIR / "skill_runs"
HOTSPOTS_FILE = SKILL_RUNS_DIR / "hotspots_x.json"

DEFAULT_X_TEAM_DEMAND_CONFIG: dict[str, Any] = {
    "enabled": True,
    "max_review_candidates": 20,
    "workflow_min_score": 4,
    "photo_min_score": 3,
    "workflow_tool_keywords": [
        "chatgpt",
        "gpt images",
        "gpt image",
        "seedance",
        "suno",
        "kavi",
        "avatar",
        "avatar jigsaw",
        "facebook instant game",
        "veo",
        "runway",
        "kling",
        "pika",
        "hailuo",
        "midjourney",
        "capcut",
        "gemini",
    ],
    "workflow_action_keywords": [
        "workflow",
        "prompt",
        "prompts",
        "tutorial",
        "step by step",
        "process",
        "production",
        "breakdown",
        "how to",
        "guide",
        "recipe",
        "made with",
        "created with",
        "generated with",
        "behind the scenes",
    ],
    "workflow_output_keywords": [
        "iphone vlog",
        "vlog",
        "photo album",
        "selfie video",
        "viral effect",
        "custom 3d figure",
        "avatar puzzle",
        "jigsaw puzzle",
        "clay avatar",
        "profile photo",
        "old photo restoration",
            "before after",
            "long video",
            "couple video",
            "single photo upload",
            "upload an image",
            "portrait to live moment",
            "stream dream",
            "streamer transformation",
            "creator persona",
            "dream portrait",
            "storybook portrait",
            "princess portrait",
            "fairy portrait",
            "dress up template",
            "image/video template",
            "template library",
            "create now",
            "cta",
            "end card",
            "couple",
            "image to video",
        "photo to video",
        "ai video",
        "ai image",
        "ai photo",
        "portrait",
        "cinematic",
    ],
    "photo_product_keywords": [
        "ai",
        "prompt",
        "workflow",
            "template",
            "single photo upload",
            "upload an image",
            "portrait to live moment",
            "stream dream",
            "streamer transformation",
            "creator persona",
            "dream portrait",
            "storybook portrait",
            "princess portrait",
            "fairy portrait",
            "dress up template",
            "image/video template",
            "template library",
            "create now",
            "cta",
            "end card",
            "mobile ad",
            "app store",
            "google play",
            "photo to video",
        "image to video",
        "before after",
        "before/after",
        "enhance",
        "restore",
        "restoration",
        "style transfer",
        "generated",
        "generator",
        "transformation",
        "ai portrait",
        "ai photo",
        "ai image",
        "iphone style",
        "vlog",
        "storyboard",
        "selfie video",
        "viral effect",
        "custom 3d figure",
        "avatar",
        "avatar puzzle",
        "jigsaw puzzle",
        "clay avatar",
        "profile photo",
        "facebook instant game",
        "old photo",
        "old photo restoration",
        "photo enhancer",
    ],
    "reject_keywords": [
        "anime",
        "manga",
        "ova",
        "cel shading",
        "cel-shading",
        "priestess",
        "salamander spirit",
        "fantasy character",
        "character design",
        "character sheet",
        "game character",
        "fanart",
        "genshin",
        "paparazzi",
        "celebrity",
        "celebrity portrait",
        "actor",
        "actress",
        "sadie sink",
        "sydney sweeney",
        "lindsay lohan",
        "street style",
        "bikini",
        "swimsuit",
        "lingerie",
        "cleavage",
        "sexy",
        "seductive",
        "sensual",
        "nsfw",
        "prompt gallery",
        "prompt library",
        "prompt resource",
        "free gallery",
        "viral prompts",
        "copy the ones",
        "meigen7982",
        "booked their photoshoot",
        "engagement shoot",
        "wedding photographer",
        "photographer portfolio",
    ],
    "product_review_enabled": True,
    "product_review_model": "qwen/qwen3.7-max",
}


def get_target_date() -> date | None:
    raw = os.environ.get("TARGET_DATE", "").strip()
    if not raw:
        return None
    return date.fromisoformat(raw)


def check_dependencies() -> bool:
    if not shutil.which("node"):
        print("ERROR: node is not installed or not available in PATH")
        return False
    if not SCRAPER_ENTRY.exists():
        print(f"ERROR: X scraper entry not found: {SCRAPER_ENTRY}")
        return False
    return True


def run_x_scraper() -> int:
    print("Phase 1: running X scraper...")
    return subprocess.run(["node", "src/scraper.js"], cwd=SCRAPER_DIR, capture_output=False).returncode


def can_continue_after_scraper_failure() -> bool:
    status = read_latest_status("x")
    return (
        partial_continue_enabled()
        and status.get("status") == "partial"
        and int(status.get("itemCount") or 0) > 0
        and DATA_FILE.exists()
    )


def parse_x_datetime(item: dict[str, Any]) -> datetime | None:
    raw = item.get("created_at") or item.get("createTime") or item.get("createTimeISO")
    if isinstance(raw, (int, float)):
        timestamp = float(raw)
        if timestamp > 1e12:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp)
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.isdigit():
            timestamp = float(text)
            if timestamp > 1e12:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp)
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
        for fmt in ("%a %b %d %H:%M:%S %z %Y", "%a %b %d %H:%M:%S %Y"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=None)
            except ValueError:
                continue
    return None


def normalize_author(author: Any) -> dict[str, Any]:
    if not isinstance(author, dict):
        return {"nickName": "", "name": "", "uniqueId": ""}
    username = str(author.get("username") or "").strip()
    display_name = str(author.get("display_name") or author.get("name") or username).strip()
    return {"nickName": username, "name": display_name, "uniqueId": username}


def normalize_x_hotspot(item: dict[str, Any], rules: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = dict(item)
    dt = parse_x_datetime(item)
    if dt:
        normalized["createTime"] = int(dt.timestamp())
        normalized["createTimeISO"] = dt.isoformat()
    normalized["sourcePlatform"] = "x"
    normalized["hotspotPlatform"] = "x"
    normalized["platform"] = "x"
    normalized["authorMeta"] = normalize_author(item.get("author"))
    normalized["playCount"] = safe_int(item.get("view_count") or item.get("views"))
    normalized["diggCount"] = safe_int(item.get("like_count") or item.get("likes"))
    normalized["likeCount"] = normalized["diggCount"]
    normalized["commentCount"] = safe_int(item.get("reply_count") or item.get("comments"))
    normalized["retweetCount"] = safe_int(item.get("retweet_count") or item.get("retweets"))
    normalized["hotspotUrl"] = str(item.get("url") or item.get("hotspotUrl") or "").strip()
    normalized["webVideoUrl"] = normalized["hotspotUrl"]
    normalized["title"] = str(item.get("text") or item.get("title") or "").strip()
    normalized["video_summary"] = str(item.get("post_summary") or item.get("summary") or "").strip()
    normalized["summary"] = normalized["video_summary"]
    normalized["hotspotIntro"] = normalized["video_summary"] or normalized["title"]
    normalized["publishDays"] = published_days(normalized)
    normalized["heatValue"] = heat_score(normalized, rules=rules)
    normalized["upsertKey"] = normalized["hotspotUrl"] or f"x:{normalized.get('id', '')}"
    return normalized


def get_video_duration_seconds(item: dict[str, Any]) -> float:
    try:
        return float(item.get("video_duration_seconds") or (item.get("raw_source") or {}).get("video_duration_seconds") or 0)
    except (TypeError, ValueError):
        return 0.0


def filter_by_time_window(data: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    max_hours = int(rules.get("quality_thresholds", {}).get("max_hours", 168) or 168)
    now = datetime.now()
    filtered = []
    for item in data:
        dt = parse_x_datetime(item)
        if not dt:
            continue
        hours = (now - dt).total_seconds() / 3600.0
        if 0 <= hours <= max_hours:
            filtered.append(item)
    print(f"  - After time filter ({max_hours}h): {len(filtered)}")
    return filtered


def filter_by_target_date(data: list[dict[str, Any]], target_date: date | None) -> list[dict[str, Any]]:
    if target_date is None:
        return data
    filtered = [item for item in data if (parse_x_datetime(item) and parse_x_datetime(item).date() == target_date)]
    print(f"  - After target date filter ({target_date.isoformat()}): {len(filtered)}")
    return filtered


def x_quality_thresholds(rules: dict[str, Any]) -> dict[str, Any]:
    thresholds = dict(rules.get("quality_thresholds", {}) or {})
    thresholds.update(rules.get("x_quality_thresholds", {}) or {})
    return thresholds


def x_like_threshold(hours_old: float, rules: dict[str, Any]) -> int:
    thresholds = sorted(
        x_quality_thresholds(rules).get("like_thresholds", []),
        key=lambda item: float(item.get("max_hours", float("inf"))),
    )
    for item in thresholds:
        if hours_old <= float(item.get("max_hours", float("inf"))):
            return int(item.get("min_digg_count", 0) or 0)
    return 0


def filter_by_quality(data: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    thresholds = x_quality_thresholds(rules)
    max_duration = float(thresholds.get("max_duration_seconds", 30) or 30)
    min_play_count = int(thresholds.get("min_play_count", 0) or 0)
    min_comment_count = int(thresholds.get("min_comment_count", 0) or 0)
    now = datetime.now()
    filtered = []
    for item in data:
        if get_video_duration_seconds(item) > max_duration:
            continue
        if safe_int(item.get("playCount") or item.get("view_count")) < min_play_count:
            continue
        if safe_int(item.get("commentCount") or item.get("reply_count")) < min_comment_count:
            continue
        dt = parse_x_datetime(item)
        if not dt:
            continue
        hours_old = (now - dt).total_seconds() / 3600.0
        if safe_int(item.get("diggCount") or item.get("like_count")) < x_like_threshold(hours_old, rules):
            continue
        filtered.append(item)
    print(
        f"  - After quality filter: {len(filtered)} "
        f"(X thresholds: comments>={min_comment_count}, likes={thresholds.get('like_thresholds', [])})"
    )
    return filtered


def filter_by_x_photo_relevance(data: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    filtered = []
    rejected = 0
    for item in data:
        details = x_photo_relevance_details(item, rules)
        item["xPhotoRelevance"] = details
        if not details.get("isRelevant", True):
            rejected += 1
            continue
        filtered.append(item)
    print(f"  - After X photo relevance filter: {len(filtered)} (rejected {rejected})")
    return filtered


def normalize_and_rank(data: list[dict[str, Any]], rules: dict[str, Any], multiplier: int = 1) -> list[dict[str, Any]]:
    normalized = [normalize_x_hotspot(item, rules=rules) for item in data]
    ranked = sorted(normalized, key=lambda item: ranking_score(item, rules), reverse=True)
    top_n = int(rules.get("quality_thresholds", {}).get("top_n", 10) or 10)
    return ranked[: max(top_n, top_n * max(1, multiplier))]


def x_team_demand_config(rules: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(DEFAULT_X_TEAM_DEMAND_CONFIG)
    configured = rules.get("x_team_demand", {})
    if isinstance(configured, dict):
        for key, value in configured.items():
            if value is not None:
                if (
                    key in {"workflow_tool_keywords", "workflow_action_keywords", "workflow_output_keywords", "photo_product_keywords", "reject_keywords"}
                    and isinstance(value, list)
                    and isinstance(cfg.get(key), list)
                ):
                    cfg[key] = list(dict.fromkeys([*cfg[key], *value]))
                else:
                    cfg[key] = value
    return cfg


def x_item_key(item: dict[str, Any]) -> str:
    return str(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url") or item.get("upsertKey") or item.get("id") or "").strip()


AD_FANTASY_TERMS = [
    "dream portrait",
    "storybook portrait",
    "princess portrait",
    "fairy portrait",
    "dress up",
]

AD_STRUCTURE_TERMS = [
    "ai",
    "prompt",
    "workflow",
    "template",
    "photo to video",
    "image to video",
    "before after",
    "before/after",
    "single photo upload",
    "upload an image",
    "portrait to live moment",
    "stream dream",
    "streamer transformation",
    "creator persona",
    "image/video template",
    "template library",
    "create now",
    "cta",
    "end card",
    "mobile ad",
    "app store",
    "google play",
    "generated",
    "generator",
    "transformation",
]


def dedupe_preserving_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = x_item_key(item)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(item)
    return deduped


def x_workflow_details(item: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    cfg = x_team_demand_config(rules)
    haystack = video_haystack(item, include_summary=True)
    tool_hits = keyword_hits(haystack, list(cfg.get("workflow_tool_keywords", [])))
    action_hits = keyword_hits(haystack, list(cfg.get("workflow_action_keywords", [])))
    output_hits = keyword_hits(haystack, list(cfg.get("workflow_output_keywords", [])))
    score = len(tool_hits) * 2 + len(action_hits) * 2 + min(len(output_hits), 4)
    min_score = int(cfg.get("workflow_min_score", 4) or 4)
    is_target = bool(
        score >= min_score
        and (
            (tool_hits and action_hits and output_hits)
            or (len(tool_hits) >= 2 and output_hits)
        )
    )
    return {
        "isTarget": is_target,
        "lane": "workflow",
        "score": score,
        "toolHits": tool_hits[:8],
        "actionHits": action_hits[:8],
        "outputHits": output_hits[:8],
        "reason": "AI creative workflow matched" if is_target else "not an AI workflow/team reference",
    }


def x_team_demand_details(item: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    cfg = x_team_demand_config(rules)
    media_type = detect_media_type(item)
    base: dict[str, Any] = {
        "isTarget": False,
        "lane": "",
        "score": 0,
        "mediaType": media_type,
        "reason": "team demand matching disabled" if not cfg.get("enabled", True) else "not a team demand candidate",
    }
    if not cfg.get("enabled", True):
        return base
    if media_type not in {"image", "mixed", "video"}:
        base["reason"] = f"media type {media_type} is not visual"
        return base

    haystack = video_haystack(item, include_summary=True)
    reject_hits = keyword_hits(haystack, list(cfg.get("reject_keywords", [])))
    if reject_hits:
        base["rejectHits"] = reject_hits[:8]
        base["reason"] = f"rejected non-product X material: {', '.join(reject_hits[:4])}"
        return base

    workflow = x_workflow_details(item, rules)
    if workflow.get("isTarget"):
        workflow["mediaType"] = media_type
        return workflow

    photo = x_photo_relevance_details(item, rules)
    product_hits = keyword_hits(haystack, list(cfg.get("photo_product_keywords", [])))
    fantasy_hits = keyword_hits(haystack, AD_FANTASY_TERMS)
    ad_structure_hits = keyword_hits(haystack, AD_STRUCTURE_TERMS)
    effective_ad_structure_hits = [hit for hit in ad_structure_hits if hit != "ai"]
    if fantasy_hits and not effective_ad_structure_hits:
        base["productHits"] = product_hits[:8]
        base["fantasyHits"] = fantasy_hits[:8]
        base["reason"] = "fantasy/dress-up material lacks upload/template/product/ad-structure evidence"
        return base
    photo_min_score = int(cfg.get("photo_min_score", 3) or 3)
    if (
        media_type in {"image", "mixed"}
        and photo.get("isRelevant")
        and int(photo.get("score", 0) or 0) >= photo_min_score
        and product_hits
    ):
        return {
            "isTarget": True,
            "lane": "photo",
            "score": int(photo.get("score", 0) or 0),
            "mediaType": media_type,
            "strongHits": photo.get("strongHits", []),
            "supportHits": photo.get("supportHits", []),
            "productHits": product_hits[:8],
            "adStructureHits": effective_ad_structure_hits[:8],
            "reason": "real-person photo with product/prompt/template signal matched",
        }

    base["score"] = max(int(workflow.get("score", 0) or 0), int(photo.get("score", 0) or 0))
    base["photoRelevance"] = photo
    base["productHits"] = product_hits[:8]
    return base


def select_x_team_demand_candidates(items: list[dict[str, Any]], rules: dict[str, Any], target_date: date | None) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    excluded = 0
    for item in items:
        if is_excluded_by_rules(item, rules, include_summary=True):
            excluded += 1
            continue
        details = x_team_demand_details(item, rules)
        if not details.get("isTarget"):
            continue
        updated = dict(item)
        updated["xTeamDemand"] = details
        updated["xPhotoRelevance"] = x_photo_relevance_details(updated, rules)
        pool.append(updated)

    print(f"  - X team demand matched: {len(pool)} (excluded by feedback rules {excluded})")
    pool = filter_by_time_window(pool, rules)
    pool = filter_by_quality(pool, rules)
    pool = filter_by_target_date(pool, target_date)
    ranked = sorted(dedupe_preserving_first(pool), key=lambda item: ranking_score(item, rules), reverse=True)
    top_n = int(rules.get("quality_thresholds", {}).get("top_n", 10) or 10)
    limit = max(top_n, int(x_team_demand_config(rules).get("max_review_candidates", top_n * 2) or top_n * 2))
    selected: list[dict[str, Any]] = []
    for index, item in enumerate(ranked[:limit], 1):
        updated = dict(item)
        details = dict(updated.get("xTeamDemand") or {})
        details["reviewPoolRank"] = index
        details["reviewPoolSize"] = limit
        updated["xTeamDemand"] = details
        selected.append(updated)
    print(f"  - X team demand candidates after quality/date/rank: {len(selected)}")
    return selected


def apply_x_product_first_targeting(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    updated_items: list[dict[str, Any]] = []
    for item in items:
        updated = dict(item)
        updated["productFit"] = product_fit_details(updated, rules)
        updated["pushObject"] = "\u4ea7\u54c1"
        details = dict(updated.get("xTeamDemand") or {})
        details["pushObject"] = "\u4ea7\u54c1"
        updated["xTeamDemand"] = details
        updated_items.append(updated)
    return updated_items


def apply_product_manual_ua_review(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = ua_material_review_config(rules)
    if not cfg.get("enabled", True):
        print("  - X product manual UA review skipped: ua_material_review disabled")
        return items

    reviewed: list[dict[str, Any]] = []
    upgraded = 0
    blocked = 0
    for item in items:
        updated = dict(item)
        try:
            review = review_with_model(updated, rules, platform="x")
        except Exception as exc:
            review = blocked_review(review_model(rules), f"model review failed: {exc}")
        updated["productManualUaReview"] = review
        if review.get("isAllowed"):
            updated["pushObject"] = "ALL"
            details = dict(updated.get("xTeamDemand") or {})
            details["pushObject"] = "ALL"
            updated["xTeamDemand"] = details
            upgraded += 1
        else:
            updated["pushObject"] = "\u4ea7\u54c1"
            blocked += 1
        reviewed.append(updated)
    print(f"  - X product manual UA review upgraded {upgraded}/{len(items)} to ALL; kept {blocked} as product")
    return reviewed


def keep_x_product_side_only(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    removed = 0
    for item in items:
        push_object = str(item.get("pushObject") or "").strip()
        if push_object in {"\u4ea7\u54c1", "ALL"}:
            kept.append(item)
        else:
            removed += 1
    if removed:
        print(f"  - X product-first policy removed {removed} non-product-only items after feedback retargeting")
    return kept


def write_hotspots(output_path: Path, items: list[dict[str, Any]]) -> None:
    items = [{**item, "pushObject": "ALL"} for item in items]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  - Wrote {len(items)} X hotspots: {output_path}")


def process_scraper_output(output_path: Path = HOTSPOTS_FILE) -> list[dict[str, Any]]:
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"Data file not found: {DATA_FILE}")
    rules = load_feedback_rules()
    variant = resolve_pipeline_variant()
    data = json.loads(DATA_FILE.read_text(encoding="utf-8-sig"))
    target_date = get_target_date()
    print(f"  - Loaded {len(data)} posts from X scraper")
    normalized_for_rules = [normalize_x_hotspot(item, rules=rules) for item in data]
    candidate_posts = select_x_team_demand_candidates(normalized_for_rules, rules, target_date)
    if not candidate_posts:
        print("  - No X hotspots found after filtering; writing empty output")
        write_hotspots(output_path, [])
        return []
    candidate_posts, _blocked_posts = apply_x_image_safety_review(candidate_posts)
    if not candidate_posts:
        print("  - No X hotspots found after image safety review; writing empty output")
        write_hotspots(output_path, [])
        return []
    candidate_posts = enrich_top_comments(candidate_posts, platform="x")
    top_n = int(rules.get("quality_thresholds", {}).get("top_n", 10) or 10)
    final_posts, _deduped_posts = apply_visual_dedupe(candidate_posts, platform="x", top_n=top_n)
    if not final_posts:
        print("  - No X hotspots found after visual dedupe; writing empty output")
        write_hotspots(output_path, [])
        return []
    final_posts = apply_ai_intros(final_posts)
    final_posts = mark_pipeline_variant(final_posts, variant)
    final_posts = apply_x_product_first_targeting(final_posts, rules)
    final_posts = apply_audience_targeting(final_posts, rules)
    final_posts, _product_blocked = apply_x_team_product_review(final_posts, rules)
    if not final_posts:
        print("  - No X hotspots found after product manual review; writing empty output")
        write_hotspots(output_path, [])
        return []
    final_posts = apply_product_manual_ua_review(final_posts, rules)
    final_posts = apply_feedback_hard_filter(final_posts, variant=variant, label="x")
    final_posts = keep_x_product_side_only(final_posts)
    if not final_posts:
        print("  - No X hotspots found after feedback hard filter; writing empty output")
    write_hotspots(output_path, final_posts)
    return final_posts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape and prepare X social media hotspots")
    parser.add_argument("--skip-scrape", action="store_true", help="Reuse existing X filtered-result.json")
    parser.add_argument("--output", type=Path, default=HOTSPOTS_FILE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env()
    if not args.skip_scrape:
        if not check_dependencies():
            return 1
        exit_code = run_x_scraper()
        if exit_code != 0:
            if can_continue_after_scraper_failure():
                print(f"WARNING: X scraper failed with exit code {exit_code}; continuing with partial checkpoint data")
            else:
                print(f"ERROR: X scraper failed with exit code {exit_code}")
                return exit_code
    try:
        process_scraper_output(args.output)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

