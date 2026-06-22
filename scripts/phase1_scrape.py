from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from env_utils import load_env
from ai_intro import apply_ai_intros
from audience_targeting import apply_audience_targeting
from feedback_hard_filter import apply_feedback_hard_filter
from comment_enrichment import enrich_top_comments
from feedback_rules import get_like_threshold, is_excluded_by_rules, load_feedback_rules, passes_include_keywords, ranking_score, video_haystack
from pipeline_variant import mark_pipeline_variant, resolve_pipeline_variant
from product_targeting import apply_product_targeting, product_fit_details
from scrape_checkpoint import partial_continue_enabled, read_latest_status
from scoring import normalize_hotspot, parse_video_datetime, safe_int
from ua_geo_targeting import config as ua_geo_config
from ua_geo_targeting import is_ua_geo_candidate, merge_unique, select_ua_geo_candidates, ua_geo_details
from ua_material_review import blocked_review, review_model, review_with_model
from tiktok_ua_batch_similarity_filter import apply_tiktok_ua_batch_similarity_filter
from tiktok_ua_video_review import apply_tiktok_ua_video_review
from tiktok_product_effect_name import apply_tiktok_product_effect_names
from visual_dedupe import apply_visual_dedupe


SCRAPER_DIR = BASE_DIR / "trend-scrap" / "tiktok-scraper"
DATA_FILE = SCRAPER_DIR / "data" / "filtered-result.json"
SCRAPER_ENTRY = SCRAPER_DIR / "src" / "scraper.js"
SKILL_RUNS_DIR = BASE_DIR / "skill_runs"
HOTSPOTS_FILE = SKILL_RUNS_DIR / "hotspots.json"


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
        print(f"ERROR: scraper entry not found: {SCRAPER_ENTRY}")
        return False
    return True


def run_tiktok_scraper() -> int:
    print("Phase 1: running TikTok scraper...")
    return subprocess.run(["node", "src/scraper.js"], cwd=SCRAPER_DIR, capture_output=False).returncode


def can_continue_after_scraper_failure() -> bool:
    status = read_latest_status("tiktok")
    return (
        partial_continue_enabled()
        and status.get("status") == "partial"
        and int(status.get("itemCount") or 0) > 0
        and DATA_FILE.exists()
    )


def get_video_duration_seconds(video: dict[str, Any]) -> float:
    try:
        return float((video.get("videoMeta") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


HOT_FEED_TEMPLATE_SIGNAL_KEYWORDS = [
    "ai template link",
    "ai creative editing",
    "ai photo editing",
    "ai editing photo effect",
    "ai photo effect",
    "filter foto ai",
    "ai foto efek",
    "ai promptfoto",
    "prompt buat foto serupa",
    "buat foto serupa",
    "one click",
    "hypic",
    "gemini ai photo edit",
    "gemini ai editor",
]


def is_hot_feed_template_signal(item: dict[str, Any]) -> bool:
    if not is_hot_feed_source(item):
        return False
    haystack = str(video_haystack(item, include_summary=True) or "").lower()
    return any(keyword in haystack for keyword in HOT_FEED_TEMPLATE_SIGNAL_KEYWORDS)


def filter_by_time_window(
    data: list[dict[str, Any]],
    rules: dict[str, Any],
    *,
    max_hours: int | None = None,
    allow_hot_feed_bypass: bool = True,
) -> list[dict[str, Any]]:
    max_hours = int(max_hours if max_hours is not None else rules.get("quality_thresholds", {}).get("max_hours", 168) or 168)
    now = datetime.now()
    filtered = []
    bypassed = 0
    for video in data:
        dt = parse_video_datetime(video)
        if not dt:
            continue
        hours = (now - dt).total_seconds() / 3600.0
        if 0 <= hours <= max_hours:
            filtered.append(video)
        elif allow_hot_feed_bypass and is_hot_feed_template_signal(video):
            updated = dict(video)
            updated["tiktokHotFeedTimeBypass"] = {
                "applied": True,
                "reason": "SocialCrawl hot-feed item with explicit AI template/photo-editing reuse signal",
                "hoursOld": round(hours, 2),
                "maxHours": max_hours,
            }
            filtered.append(updated)
            bypassed += 1
    print(f"  - After time filter ({max_hours}h): {len(filtered)}")
    if bypassed:
        print(f"  - Hot-feed product-template time bypass: {bypassed}")
    return filtered


def filter_by_duration(data: list[dict[str, Any]], max_duration_seconds: float) -> list[dict[str, Any]]:
    filtered = [video for video in data if get_video_duration_seconds(video) <= max_duration_seconds]
    print(f"  - After duration filter (<={max_duration_seconds:g}s): {len(filtered)}")
    return filtered


def filter_by_target_date(data: list[dict[str, Any]], target_date: date | None) -> list[dict[str, Any]]:
    if target_date is None:
        return data
    filtered = [video for video in data if (parse_video_datetime(video) and parse_video_datetime(video).date() == target_date)]
    print(f"  - After target date filter ({target_date.isoformat()}): {len(filtered)}")
    return filtered


def filter_by_quality(
    data: list[dict[str, Any]],
    rules: dict[str, Any],
    *,
    max_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    thresholds = rules.get("quality_thresholds", {})
    max_duration = float(max_duration_seconds if max_duration_seconds is not None else thresholds.get("max_duration_seconds", 30) or 30)
    min_play_count = int(thresholds.get("min_play_count", 0) or 0)
    min_comment_count = int(thresholds.get("min_comment_count", 0) or 0)
    now = datetime.now()
    filtered = []
    for video in data:
        if get_video_duration_seconds(video) > max_duration:
            continue
        if safe_int(video.get("playCount")) < min_play_count:
            continue
        if safe_int(video.get("commentCount")) < min_comment_count:
            continue
        dt = parse_video_datetime(video)
        if not dt:
            continue
        hours_old = (now - dt).total_seconds() / 3600.0
        if safe_int(video.get("diggCount") or video.get("likeCount")) < get_like_threshold(hours_old, rules):
            continue
        filtered.append(video)
    print(f"  - After quality filter: {len(filtered)}")
    return filtered


def apply_stage4_ua_quality_gate(
    data: list[dict[str, Any]],
    rules: dict[str, Any],
    *,
    disable_metric_thresholds: bool = False,
    max_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    if disable_metric_thresholds:
        max_duration = float(max_duration_seconds if max_duration_seconds is not None else rules.get("quality_thresholds", {}).get("max_duration_seconds", 30) or 30)
        filtered = filter_by_duration(data, max_duration)
        print("  - TikTok UA metric quality gate disabled; duration gate only", flush=True)
        return filtered
    discovery_items = [video for video in data if is_tiktok_keyword_discovery_source(video)]
    regular_items = [video for video in data if not is_tiktok_keyword_discovery_source(video)]
    filtered_regular = filter_by_quality(regular_items, rules, max_duration_seconds=max_duration_seconds) if regular_items else []
    if discovery_items:
        print(
            "  - TikTok Discovery UA quality gate bypass: "
            f"kept {len(discovery_items)} after safety/time filters; product push heat screen still applies",
            flush=True,
        )
    return [*discovery_items, *filtered_regular]


def normalize_and_rank(data: list[dict[str, Any]], rules: dict[str, Any], multiplier: int = 1, limit: int | None = None) -> list[dict[str, Any]]:
    normalized = [normalize_hotspot(video, rules=rules) for video in data]
    ranked = sorted(normalized, key=lambda video: ranking_score(video, rules), reverse=True)
    if limit is not None:
        if limit <= 0:
            return ranked
        return ranked[:limit]
    top_n = int(rules.get("quality_thresholds", {}).get("top_n", 10) or 10)
    return ranked[: max(top_n, top_n * max(1, multiplier))]


def ua_geo_review_pool_size(rules: dict[str, Any]) -> int:
    cfg = ua_geo_config(rules)
    daily_max = int(cfg.get("daily_max", 1) or 1)
    configured = int(cfg.get("review_pool_size", 5) or 5)
    return max(daily_max, configured)


FOCUS_PRODUCT_KEYS = {"evoke", "toki", "kavi", "avatar_jigsaw"}
UA_PUSH_OBJECT = "UA"
ALL_PUSH_OBJECT = "ALL"
PRODUCT_PUSH_OBJECT = "\u4ea7\u54c1"
DANCE_PRODUCT_PERSON_FILTER_QUERIES = {
    "dance 2026",
    "dance trend 2026",
    "dance challenge 2026",
    "dance2026",
    "dancetrend",
    "dance",
    "dance trend",
    "new dance trend",
    "dance challenge",
    "solo dance choreography",
    "fixed camera dance",
    "floor move dance",
    "hip hop dance challenge",
    "japan dance trend",
    "copines dance trend",
}
DANCE_PRODUCT_KNOWN_NON_ADULT_VIDEO_IDS = {
    "7651382091661217055",
}
DANCE_PRODUCT_MULTI_PERSON_RE = re.compile(
    r"\b("
    r"couple|bf/gf|boyfriend|girlfriend|husband|wife|"
    r"sister|sisters|brother|brothers|twins|trio|duo|"
    r"group|covergroup|team|crew|squad|collab|with|we|us|they|"
    r"tag your|partner|family|friends|girls|boys|members|bias"
    r")\b",
    re.IGNORECASE,
)
DANCE_PRODUCT_MINOR_RE = re.compile(
    r"\b(child|children|kid|kids|minor|underage|teen|teenage|toddler|schoolboy|schoolgirl|youngster)\b"
    r"|儿童|小孩|小朋友|未成年|幼儿|宝宝",
    re.IGNORECASE,
)
DANCE_PRODUCT_CREDIT_MENTION_RE = re.compile(r"\b(dc|ctto|credit|credits|cred|choreo|choreography|tutorial|by)\b", re.IGNORECASE)
DANCE_PRODUCT_MENTION_RE = re.compile(r"@[\w.\-]+")


def source_query(item: dict[str, Any]) -> str:
    return str(item.get("sourceQuery") or item.get("searchQuery") or "").strip().lower()


def clean_query_token(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def dance_product_source_queries(item: dict[str, Any]) -> set[str]:
    queries: set[str] = set()
    for key in ["sourceQuery", "searchQuery"]:
        query = clean_query_token(item.get(key))
        if query:
            queries.add(query)
    details = item.get("tiktokKeywordDiscovery") if isinstance(item.get("tiktokKeywordDiscovery"), dict) else {}
    for key in ["sourceQueries", "keywords"]:
        values = details.get(key)
        if isinstance(values, list):
            for value in values:
                query = clean_query_token(value)
                if query:
                    queries.add(query)
    plan_entries = details.get("planEntries")
    if isinstance(plan_entries, list):
        for entry in plan_entries:
            if isinstance(entry, dict):
                query = clean_query_token(entry.get("keyword"))
                if query:
                    queries.add(query)
    return queries


def is_dance_product_person_filter_query(item: dict[str, Any]) -> bool:
    return bool(dance_product_source_queries(item) & DANCE_PRODUCT_PERSON_FILTER_QUERIES)


def dance_product_filter_haystack(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ["title", "text", "desc", "summary", "video_summary", "hotspotIntro", "sourceQuery", "searchQuery"]:
        if item.get(key):
            parts.append(str(item.get(key)))
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    for key in ["uniqueId", "nickName", "name"]:
        if author.get(key):
            parts.append(str(author.get(key)))
    hashtags = item.get("hashtags")
    if isinstance(hashtags, list):
        for tag in hashtags:
            if isinstance(tag, dict):
                parts.append(str(tag.get("name") or tag.get("title") or tag.get("hashtag") or ""))
            else:
                parts.append(str(tag))
    return clean_query_token(" ".join(part for part in parts if part))


def dance_product_video_identifiers(item: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for key in ["id", "hotspotUrl", "webVideoUrl", "url", "upsertKey"]:
        text = str(item.get(key) or "").strip()
        if text:
            values.add(text)
    video_meta = item.get("videoMeta") if isinstance(item.get("videoMeta"), dict) else {}
    for key in ["webVideoUrl", "downloadAddr", "coverUrl"]:
        text = str(video_meta.get(key) or "").strip()
        if text:
            values.add(text)
    return values


def dance_product_mention_count(item: dict[str, Any]) -> int:
    return len(DANCE_PRODUCT_MENTION_RE.findall(str(item.get("text") or "")))


def dance_product_person_filter_details(item: dict[str, Any]) -> dict[str, Any]:
    queries = sorted(dance_product_source_queries(item))
    matched_queries = [query for query in queries if query in DANCE_PRODUCT_PERSON_FILTER_QUERIES]
    if not matched_queries:
        return {
            "applied": False,
            "passed": True,
            "reason": "source query is not one of the bound dance Product search terms",
            "matchedQueries": [],
        }

    identifiers = dance_product_video_identifiers(item)
    if str(item.get("id") or "").strip() in DANCE_PRODUCT_KNOWN_NON_ADULT_VIDEO_IDS or any(
        video_id in identifier for video_id in DANCE_PRODUCT_KNOWN_NON_ADULT_VIDEO_IDS for identifier in identifiers
    ):
        return {
            "applied": True,
            "passed": False,
            "reason": "known non-adult lead subject for bound dance Product search term",
            "matchedQueries": matched_queries,
            "rule": "known_non_adult_video_id",
        }

    haystack = dance_product_filter_haystack(item)
    if DANCE_PRODUCT_MINOR_RE.search(haystack):
        return {
            "applied": True,
            "passed": False,
            "reason": "text metadata indicates a non-adult lead subject",
            "matchedQueries": matched_queries,
            "rule": "minor_keyword",
        }
    if DANCE_PRODUCT_MULTI_PERSON_RE.search(haystack):
        return {
            "applied": True,
            "passed": False,
            "reason": "text metadata indicates multiple people, couple, team, or group dance",
            "matchedQueries": matched_queries,
            "rule": "multi_person_keyword",
        }

    mention_count = dance_product_mention_count(item)
    if mention_count >= 2:
        return {
            "applied": True,
            "passed": False,
            "reason": "caption has multiple @ mentions, likely not a single-person dance",
            "matchedQueries": matched_queries,
            "rule": "multiple_mentions",
        }
    if mention_count == 1 and not DANCE_PRODUCT_CREDIT_MENTION_RE.search(haystack):
        return {
            "applied": True,
            "passed": False,
            "reason": "caption has a non-credit @ mention, likely not a single-person dance",
            "matchedQueries": matched_queries,
            "rule": "non_credit_mention",
        }

    return {
        "applied": True,
        "passed": True,
        "reason": "passed bound dance Product metadata screen for single adult lead",
        "matchedQueries": matched_queries,
        "rule": "metadata_single_adult_gate",
    }


def apply_dance_product_person_filter(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    applied = 0
    removed = 0
    for item in items:
        details = dance_product_person_filter_details(item)
        if details["applied"]:
            applied += 1
        if not details["passed"]:
            removed += 1
            continue
        if details["applied"]:
            kept.append({**item, "tiktokProductDancePersonFilter": details})
        else:
            kept.append(item)
    if applied:
        print(
            "  - TikTok Product dance single/adult filter: "
            f"kept {len(kept)}/{len(items)}; applied={applied}; removed={removed}",
            flush=True,
        )
    return kept


def is_hot_feed_source(item: dict[str, Any]) -> bool:
    values = [
        item.get("captureSource"),
        item.get("sourcePath"),
        item.get("source"),
        item.get("sourceQuery"),
        item.get("searchQuery"),
    ]
    return any("hot_feed" in str(value or "").strip().lower() for value in values)


def is_tiktok_keyword_discovery_source(item: dict[str, Any]) -> bool:
    values = [
        item.get("captureSource"),
        item.get("sourcePath"),
        item.get("source"),
        item.get("sourceQuery"),
        item.get("searchQuery"),
    ]
    return any("tiktok_keyword_discovery" in str(value or "").strip().lower() for value in values)


def tiktok_keyword_discovery_layer_details(item: dict[str, Any]) -> dict[str, str]:
    details = item.get("tiktokKeywordDiscovery") if isinstance(item.get("tiktokKeywordDiscovery"), dict) else {}
    layers = details.get("keywordLayers") if isinstance(details.get("keywordLayers"), list) else []
    fit_types = details.get("fitTypes") if isinstance(details.get("fitTypes"), list) else []
    return {
        "layer": str(item.get("tiktokKeywordDiscoveryLayer") or (layers[0] if layers else "") or "").strip().lower(),
        "fitType": str(item.get("tiktokKeywordDiscoveryFitType") or (fit_types[0] if fit_types else "") or "").strip().lower(),
    }


def is_hot_layer_ad_material_candidate(item: dict[str, Any]) -> bool:
    if not is_tiktok_keyword_discovery_source(item):
        return False
    details = tiktok_keyword_discovery_layer_details(item)
    return details["layer"] == "hot" and details["fitType"] in {"ad_material", "both"}


def non_ai_search_queries(rules: dict[str, Any]) -> set[str]:
    queries: set[str] = set()
    for query in rules.get("scrape", {}).get("search_queries", []):
        text = str(query or "").strip().lower()
        if text and "ai" not in text:
            queries.add(text)
    return queries


def is_non_ai_or_hot_feed_source(item: dict[str, Any], rules: dict[str, Any]) -> bool:
    query = source_query(item)
    return is_hot_feed_source(item) or is_tiktok_keyword_discovery_source(item) or (query and query in non_ai_search_queries(rules))


def product_hard_gate(item: dict[str, Any], rules: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    fit = product_fit_details(item, rules)
    primary = str(fit.get("primaryProduct") or "").strip().lower()
    return bool(fit.get("isProductCandidate")) and primary in FOCUS_PRODUCT_KEYS, fit


def is_focus_product_candidate(fit: dict[str, Any]) -> bool:
    primary = str(fit.get("primaryProduct") or "").strip().lower()
    return bool(fit.get("isProductCandidate")) and primary in FOCUS_PRODUCT_KEYS


def product_push_heat_multiplier(item: dict[str, Any]) -> float:
    details = item.get("tiktokNonAiTargeting")
    if isinstance(details, dict) and details.get("isTarget"):
        return 1.0 if is_hot_layer_ad_material_candidate(item) else 1.5
    return 1.0


def product_push_heat_screen(item: dict[str, Any], rules: dict[str, Any], fit: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved_fit = fit if isinstance(fit, dict) else product_fit_details(item, rules)
    thresholds = rules.get("quality_thresholds", {})
    min_play_count = int(thresholds.get("min_play_count", 0) or 0)
    min_comment_count = int(thresholds.get("min_comment_count", 0) or 0)
    dt = parse_video_datetime(item)
    multiplier = product_push_heat_multiplier(item)
    play_threshold = max(min_play_count, int(min_play_count * multiplier))
    comment_threshold = max(min_comment_count, int(min_comment_count * multiplier))
    hours_old: float | None = None
    like_threshold = 0
    if dt:
        hours_old = max(0.0, (datetime.now() - dt).total_seconds() / 3600.0)
        base_like_threshold = get_like_threshold(hours_old, rules)
        like_threshold = max(base_like_threshold, int(base_like_threshold * multiplier))
    play_count = safe_int(item.get("playCount"))
    comment_count = safe_int(item.get("commentCount"))
    like_count = safe_int(item.get("diggCount") or item.get("likeCount"))
    is_product_candidate = is_focus_product_candidate(resolved_fit)
    passed = (
        is_product_candidate
        and dt is not None
        and play_count >= play_threshold
        and comment_count >= comment_threshold
        and like_count >= like_threshold
    )
    if not is_product_candidate:
        reason = "not a focus product candidate"
    elif dt is None:
        reason = "missing publish time for heat screening"
    elif passed:
        reason = "passed product push heat screening"
    else:
        reason = "below product push heat thresholds"
    return {
        "passed": passed,
        "reason": reason,
        "primaryProduct": resolved_fit.get("primaryProduct"),
        "multiplier": multiplier,
        "hoursOld": round(hours_old, 2) if hours_old is not None else None,
        "actual": {
            "playCount": play_count,
            "commentCount": comment_count,
            "likeCount": like_count,
        },
        "thresholds": {
            "playCount": play_threshold,
            "commentCount": comment_threshold,
            "likeCount": like_threshold,
        },
    }


def product_push_object_for_item(item: dict[str, Any], rules: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    fit = item.get("productFit") if isinstance(item.get("productFit"), dict) else product_fit_details(item, rules)
    heat_screen = product_push_heat_screen(item, rules, fit)
    return (ALL_PUSH_OBJECT if heat_screen.get("passed") else UA_PUSH_OBJECT), fit, heat_screen


def is_high_heat_non_ai_candidate(item: dict[str, Any], rules: dict[str, Any]) -> bool:
    thresholds = rules.get("quality_thresholds", {})
    min_play_count = int(thresholds.get("min_play_count", 0) or 0)
    min_comment_count = int(thresholds.get("min_comment_count", 0) or 0)
    dt = parse_video_datetime(item)
    if not dt:
        return False
    hours_old = max(0.0, (datetime.now() - dt).total_seconds() / 3600.0)
    like_threshold = get_like_threshold(hours_old, rules)
    multiplier = 1.0 if is_hot_layer_ad_material_candidate(item) else 1.5
    return (
        safe_int(item.get("playCount")) >= max(min_play_count, int(min_play_count * multiplier))
        and safe_int(item.get("commentCount")) >= max(min_comment_count, int(min_comment_count * multiplier))
        and safe_int(item.get("diggCount") or item.get("likeCount")) >= max(like_threshold, int(like_threshold * multiplier))
    )


def non_ai_candidate_lane(item: dict[str, Any]) -> str:
    if is_hot_feed_source(item):
        return "hot_feed_lane"
    if is_hot_layer_ad_material_candidate(item):
        return "hot_keyword_discovery_lane"
    return "non_ai_product_lane"


def annotate_non_ai_product_candidate(
    item: dict[str, Any],
    *,
    lane: str,
    method: str,
    reason: str,
    fit: dict[str, Any],
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated = dict(item)
    updated["productFit"] = fit
    updated["pushObject"] = UA_PUSH_OBJECT
    updated["tiktokNonAiTargeting"] = {
        "isTarget": True,
        "lane": lane,
        "method": method,
        "reason": reason,
        "sourceQuery": source_query(updated),
        "primaryProduct": fit.get("primaryProduct"),
        "pushObject": UA_PUSH_OBJECT,
        "productPushRequiresHeatScreen": True,
    }
    if review is not None:
        updated["tiktokNonAiMaterialReview"] = review
    return updated


def apply_non_ai_product_lane(data: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    review_pool: list[dict[str, Any]] = []
    counts = {
        "ai_or_geo": 0,
        "non_ai_sources": 0,
        "hard_gate": 0,
        "model_allowed": 0,
        "model_blocked": 0,
        "discovery_ua": 0,
        "dropped": 0,
    }
    review_limit = max(1, int(rules.get("ua_material_review", {}).get("review_pool_size", 10) or 10))
    for item in data:
        is_ai_or_geo = passes_include_keywords(item, rules) or bool(ua_geo_details(item, rules).get("isTarget"))
        is_non_ai = is_non_ai_or_hot_feed_source(item, rules)
        if not is_non_ai:
            if is_ai_or_geo:
                counts["ai_or_geo"] += 1
                kept.append(item)
            else:
                counts["dropped"] += 1
            continue
        counts["non_ai_sources"] += 1
        lane = non_ai_candidate_lane(item)
        hard_ok, fit = product_hard_gate(item, rules)
        if hard_ok:
            counts["hard_gate"] += 1
            kept.append(
                annotate_non_ai_product_candidate(
                    item,
                    lane=lane,
                    method="product_hard_gate",
                    reason="matched Evoke/Toki/Kavi/Avatar product material signals",
                    fit=fit,
                )
            )
            continue
        if is_tiktok_keyword_discovery_source(item):
            counts["discovery_ua"] += 1
            kept.append(
                annotate_non_ai_product_candidate(
                    item,
                    lane=lane,
                    method="discovery_source_ua_gate",
                    reason="TikTok Discovery source kept for UA after safety and time screening",
                    fit=fit,
                )
            )
            continue
        if is_high_heat_non_ai_candidate(item, rules):
            review_pool.append(item)
        else:
            counts["dropped"] += 1
    review_pool = sorted(review_pool, key=lambda item: ranking_score(item, rules), reverse=True)[:review_limit]
    for item in review_pool:
        try:
            review = review_with_model(item, rules, platform="tiktok")
        except Exception as exc:
            review = blocked_review(review_model(rules), f"model review failed: {exc}")
        if review.get("isAllowed"):
            product = str(review.get("recommendedProduct") or "").strip().lower()
            fit = product_fit_details(item, rules)
            if product in FOCUS_PRODUCT_KEYS:
                fit = dict(fit)
                fit["primaryProduct"] = product
                fit["isProductCandidate"] = True
                scores = dict(fit.get("productScores") or {})
                scores[product] = max(float(scores.get(product, 0) or 0), 2.0)
                fit["productScores"] = scores
            counts["model_allowed"] += 1
            kept.append(
                annotate_non_ai_product_candidate(
                    item,
                    lane=non_ai_candidate_lane(item),
                    method="model_review",
                    reason="high-heat non-AI material passed product manual review",
                    fit=fit,
                    review=review,
                )
            )
        else:
            counts["model_blocked"] += 1
    if counts["non_ai_sources"] or counts["dropped"]:
        print(
            "  - TikTok non-AI/hot-feed lane: "
            f"sources={counts['non_ai_sources']}, hard_gate={counts['hard_gate']}, "
            f"model_allowed={counts['model_allowed']}, model_blocked={counts['model_blocked']}, "
            f"discovery_ua={counts['discovery_ua']}, ai_or_geo={counts['ai_or_geo']}, dropped={counts['dropped']}",
            flush=True,
        )
    return kept


def preserve_non_ai_product_push_object(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated_items: list[dict[str, Any]] = []
    for item in items:
        details = item.get("tiktokNonAiTargeting")
        if not isinstance(details, dict) or not details.get("isTarget"):
            updated_items.append(item)
            continue
        updated = dict(item)
        updated["pushObject"] = UA_PUSH_OBJECT
        details = dict(details)
        details["pushObject"] = UA_PUSH_OBJECT
        details["productPushRequiresHeatScreen"] = True
        updated["tiktokNonAiTargeting"] = details
        updated_items.append(updated)
    return updated_items


def is_reviewed_hot_feed_candidate(item: dict[str, Any]) -> bool:
    details = item.get("tiktokNonAiTargeting")
    return (
        is_hot_feed_source(item)
        and isinstance(details, dict)
        and bool(details.get("isTarget"))
        and details.get("lane") == "hot_feed_lane"
    )


def ua_geo_push_object_for_item(item: dict[str, Any], rules: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    push_object, fit, _heat_screen = product_push_object_for_item(item, rules)
    return push_object, fit


def force_ua_geo_push_object(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    updated_items: list[dict[str, Any]] = []
    for item in items:
        if not is_ua_geo_candidate(item):
            updated_items.append(item)
            continue
        updated = dict(item)
        push_object, fit, heat_screen = product_push_object_for_item(updated, rules)
        details = dict(updated.get("uaGeoTargeting") or {})
        details["pushObject"] = push_object
        if push_object == ALL_PUSH_OBJECT:
            details["productMatchedPushObject"] = ALL_PUSH_OBJECT
            details["primaryProduct"] = fit.get("primaryProduct")
        details["productPushHeatScreen"] = heat_screen
        updated["uaGeoTargeting"] = details
        updated["productFit"] = fit
        updated["productPushHeatScreen"] = heat_screen
        updated["pushObject"] = push_object
        updated_items.append(updated)
    return updated_items


def apply_tiktok_push_object_policy(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    updated_items: list[dict[str, Any]] = []
    for item in items:
        updated = dict(item)
        push_object, fit, heat_screen = product_push_object_for_item(updated, rules)
        updated["productFit"] = fit
        updated["productPushHeatScreen"] = heat_screen
        updated["pushObject"] = push_object
        geo_details = updated.get("uaGeoTargeting")
        if isinstance(geo_details, dict):
            geo_details = dict(geo_details)
            geo_details["pushObject"] = push_object
            geo_details["productPushHeatScreen"] = heat_screen
            if push_object == ALL_PUSH_OBJECT:
                geo_details["productMatchedPushObject"] = ALL_PUSH_OBJECT
                geo_details["primaryProduct"] = fit.get("primaryProduct")
            else:
                geo_details.pop("productMatchedPushObject", None)
            updated["uaGeoTargeting"] = geo_details
        non_ai_details = updated.get("tiktokNonAiTargeting")
        if isinstance(non_ai_details, dict):
            non_ai_details = dict(non_ai_details)
            non_ai_details["pushObject"] = push_object
            non_ai_details["productPushHeatScreen"] = heat_screen
            updated["tiktokNonAiTargeting"] = non_ai_details
        updated_items.append(updated)
    return updated_items


def keep_required_ua_geo(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = ua_geo_config(rules)
    daily_max = int(cfg.get("daily_max", 1) or 1)
    daily_min = int(cfg.get("daily_min", 1) or 1)
    regular = [item for item in items if not is_ua_geo_candidate(item)]
    geo = force_ua_geo_push_object([item for item in items if is_ua_geo_candidate(item)], rules)
    if daily_max <= 0:
        return regular
    geo = sorted(geo, key=lambda item: float(item.get("heatValue") or ranking_score(item, rules)), reverse=True)
    selected_geo = geo[:daily_max]
    if selected_geo:
        best = selected_geo[0]
        print(
            f"  - Required TikTok UA geo kept {len(selected_geo)}/{len(geo)} passed candidates; "
            f"best heat {best.get('heatValue', 0)}",
            flush=True,
        )
    elif daily_min > 0:
        print("  - WARNING: no TikTok UA geo candidate survived downstream filters/reviews", flush=True)
    return [*regular, *selected_geo]


def keep_pushable_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    removed = 0
    for item in items:
        if str(item.get("pushObject") or "").strip() in {UA_PUSH_OBJECT, ALL_PUSH_OBJECT}:
            kept.append(item)
        else:
            removed += 1
    if removed:
        print(f"  - Removed {removed} items without valid pushObject after targeting", flush=True)
    return kept


def route_profile_options(route_profile: str | None) -> dict[str, Any]:
    profile = str(route_profile or "main").strip().lower()
    if profile in {"ua", "tiktok-ua", "tiktok_ua"}:
        return {
            "name": "ua",
            "maxHours": 168,
            "maxDurationSeconds": 60.0,
            "disableMetricThresholds": True,
            "allowHotFeedTimeBypass": False,
            "unlimitedOutput": True,
            "forcePushObject": UA_PUSH_OBJECT,
        }
    if profile in {"product", "tiktok-product", "tiktok_product"}:
        return {
            "name": "product",
            "maxHours": 2160,
            "maxDurationSeconds": 15.0,
            "allowHotFeedTimeBypass": False,
        }
    return {
        "name": "main",
        "maxHours": None,
        "maxDurationSeconds": None,
        "disableMetricThresholds": False,
        "allowHotFeedTimeBypass": True,
        "unlimitedOutput": False,
        "forcePushObject": "",
    }


def route_item_key(item: dict[str, Any]) -> str:
    return str(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url") or item.get("upsertKey") or item.get("id") or "").strip()


def dedupe_by_url_keep_best(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    keyed: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for item in items:
        key = route_item_key(item)
        if not key:
            unkeyed.append(item)
            continue
        existing = keyed.get(key)
        if existing is None or ranking_score(item, rules) > ranking_score(existing, rules):
            keyed[key] = item
    return [*keyed.values(), *unkeyed]


def force_route_push_object(items: list[dict[str, Any]], push_object: str) -> list[dict[str, Any]]:
    updated_items: list[dict[str, Any]] = []
    for item in items:
        updated = dict(item)
        updated["pushObject"] = push_object
        if push_object == UA_PUSH_OBJECT:
            details = updated.get("tiktokNonAiTargeting")
            if isinstance(details, dict):
                details = dict(details)
                details["pushObject"] = UA_PUSH_OBJECT
                updated["tiktokNonAiTargeting"] = details
            geo_details = updated.get("uaGeoTargeting")
            if isinstance(geo_details, dict):
                geo_details = dict(geo_details)
                geo_details["pushObject"] = UA_PUSH_OBJECT
                geo_details.pop("productMatchedPushObject", None)
                updated["uaGeoTargeting"] = geo_details
        updated_items.append(updated)
    return updated_items


def hours_old(item: dict[str, Any]) -> float | None:
    dt = parse_video_datetime(item)
    if not dt:
        return None
    return max(0.0, (datetime.now() - dt).total_seconds() / 3600.0)


def metric_value(item: dict[str, Any], metric: str) -> int:
    if metric == "plays":
        return safe_int(item.get("playCount") or item.get("views"))
    if metric == "likes":
        return safe_int(item.get("diggCount") or item.get("likeCount") or item.get("likes"))
    if metric == "comments":
        return safe_int(item.get("commentCount") or item.get("comments"))
    return 0


def top_by_metric(items: list[dict[str, Any]], metric: str, limit: int) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: metric_value(item, metric), reverse=True)[:limit]


def merge_metric_candidates(*groups: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [candidate for group in groups for candidate in group]:
        key = route_item_key(item)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        merged.append(item)
    return sorted(merged, key=lambda item: ranking_score(item, rules), reverse=True)


def product_window_candidate_pool(items: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    windows = [
        ("7d", 168),
        ("30d", 720),
        ("90d", 2160),
    ]
    by_window: dict[str, list[dict[str, Any]]] = {}
    assigned: set[str] = set()
    for label, max_hours in windows:
        pool = [
            item
            for item in items
            if (hours_old(item) is not None and hours_old(item) <= max_hours)
        ]
        candidates = merge_metric_candidates(
            top_by_metric(pool, "plays", 20),
            top_by_metric(pool, "likes", 10),
            top_by_metric(pool, "comments", 5),
            rules=rules,
        )
        window_items: list[dict[str, Any]] = []
        for index, item in enumerate(candidates, 1):
            key = route_item_key(item)
            if key and key in assigned:
                continue
            if key:
                assigned.add(key)
            updated = dict(item)
            updated["tiktokProductWindow"] = label
            updated["tiktokProductWindowRank"] = index
            updated["tiktokProductWindowHours"] = max_hours
            window_items.append(updated)
        by_window[label] = window_items
    return by_window


def product_route_limit(env: dict[str, str] | None = None) -> int:
    source = env or os.environ
    try:
        return max(0, int(source.get("TIKTOK_PRODUCT_PER_WINDOW_LIMIT", "1") or 1))
    except (TypeError, ValueError):
        return 1


def select_product_route_items(items: list[dict[str, Any]], rules: dict[str, Any], *, per_window_limit: int) -> list[dict[str, Any]]:
    by_window = product_window_candidate_pool(items, rules)
    ordered_candidates: list[dict[str, Any]] = []
    for label in ["7d", "30d", "90d"]:
        ordered_candidates.extend(sorted(by_window.get(label, []), key=lambda item: ranking_score(item, rules), reverse=True))
    if not ordered_candidates:
        return []
    visually_deduped, _deduped = apply_visual_dedupe(
        ordered_candidates,
        platform="tiktok",
        top_n=len(ordered_candidates),
    )
    selected: list[dict[str, Any]] = []
    for label in ["7d", "30d", "90d"]:
        window_items = [item for item in visually_deduped if item.get("tiktokProductWindow") == label]
        selected.extend(sorted(window_items, key=lambda item: ranking_score(item, rules), reverse=True)[:per_window_limit])
    return selected


def process_product_route_output(
    output_path: Path,
    *,
    input_data: Path,
    data_snapshot_path: Path | None,
) -> list[dict[str, Any]]:
    if not input_data.exists():
        raise FileNotFoundError(f"Data file not found: {input_data}")
    rules = load_feedback_rules()
    variant = resolve_pipeline_variant()
    data = json.loads(input_data.read_text(encoding="utf-8-sig"))
    print(f"  - Loaded {len(data)} videos from {input_data}")
    data = filter_by_time_window(data, rules, max_hours=2160, allow_hot_feed_bypass=False)
    data = filter_by_duration(data, 15.0)
    normalized = [normalize_hotspot(video, rules=rules) for video in data]
    normalized = [item for item in normalized if route_item_key(item)]
    normalized = dedupe_by_url_keep_best(normalized, rules)
    print(f"  - After URL dedupe: {len(normalized)}")
    normalized = apply_dance_product_person_filter(normalized)
    selected = select_product_route_items(normalized, rules, per_window_limit=product_route_limit())
    if selected:
        selected = apply_tiktok_product_effect_names(selected)
        selected = mark_pipeline_variant(selected, variant)
        selected = [
            {
                **item,
                "pushObject": ALL_PUSH_OBJECT,
                "tiktokRoute": "product",
                "tiktokProductRoute": {"source": "dance_trend", "pushObject": ALL_PUSH_OBJECT},
            }
            for item in selected
        ]
    else:
        print("  - No TikTok Product route hotspots found after window selection")
    write_hotspots(output_path, selected, "tiktok product hotspots", data_snapshot_path=data_snapshot_path)
    return selected


def write_hotspots(
    output_path: Path,
    items: list[dict[str, Any]],
    label: str = "hotspots",
    *,
    data_snapshot_path: Path | None = DATA_FILE,
) -> None:
    items = [
        {**item, "pushObject": str(item.get("pushObject") or "").strip() if str(item.get("pushObject") or "").strip() in {UA_PUSH_OBJECT, ALL_PUSH_OBJECT} else UA_PUSH_OBJECT}
        for item in items
    ]
    if data_snapshot_path is not None:
        data_snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        data_snapshot_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  - Wrote {len(items)} {label}: {output_path}")


def process_scraper_output(
    output_path: Path = HOTSPOTS_FILE,
    *,
    input_data: Path = DATA_FILE,
    data_snapshot_path: Path | None = DATA_FILE,
    route_profile: str | None = None,
) -> list[dict[str, Any]]:
    route_options = route_profile_options(route_profile)
    if route_options["name"] == "product":
        return process_product_route_output(
            output_path,
            input_data=input_data,
            data_snapshot_path=data_snapshot_path,
        )
    if not input_data.exists():
        raise FileNotFoundError(f"Data file not found: {input_data}")
    rules = load_feedback_rules()
    variant = resolve_pipeline_variant()
    data = json.loads(input_data.read_text(encoding="utf-8-sig"))
    target_date = get_target_date()
    print(f"  - Loaded {len(data)} videos from {input_data}")
    data = [
        video
        for video in data
        if passes_include_keywords(video, rules)
        or ua_geo_details(video, rules).get("isTarget")
        or is_non_ai_or_hot_feed_source(video, rules)
    ]
    print(f"  - After include/non-AI source filter: {len(data)}")
    data = [video for video in data if not is_excluded_by_rules(video, rules)]
    print(f"  - After feedback exclude filter: {len(data)}")
    data = filter_by_time_window(
        data,
        rules,
        max_hours=route_options.get("maxHours"),
        allow_hot_feed_bypass=bool(route_options.get("allowHotFeedTimeBypass", True)),
    )
    normalized_geo_pool = [normalize_hotspot(video, rules=rules) for video in filter_by_target_date(data, target_date)]
    geo_limit = int(ua_geo_config(rules).get("daily_max", 1) or 1)
    geo_pool_size = ua_geo_review_pool_size(rules)
    ua_geo_candidates = select_ua_geo_candidates(normalized_geo_pool, rules, limit=geo_pool_size)
    print(f"  - UA geo review candidates: {len(ua_geo_candidates)} (pool top {geo_pool_size}, daily max {geo_limit})")
    data = apply_stage4_ua_quality_gate(
        data,
        rules,
        disable_metric_thresholds=bool(route_options.get("disableMetricThresholds")),
        max_duration_seconds=route_options.get("maxDurationSeconds"),
    )
    data = filter_by_target_date(data, target_date)
    data = apply_non_ai_product_lane(data, rules)
    reviewed_hot_feed_candidates = [normalize_hotspot(video, rules=rules) for video in data if is_reviewed_hot_feed_candidate(video)]
    candidate_videos = normalize_and_rank(
        data,
        rules,
        multiplier=2,
        limit=0 if route_options.get("unlimitedOutput") else None,
    )
    candidate_videos = merge_unique(candidate_videos, reviewed_hot_feed_candidates)
    if not candidate_videos and not ua_geo_candidates:
        print("  - No TikTok hotspots found after filtering; writing empty output")
        write_hotspots(output_path, [], "hotspots", data_snapshot_path=data_snapshot_path)
        return []
    candidate_videos = merge_unique(candidate_videos, ua_geo_candidates)
    if route_options["name"] == "ua":
        candidate_videos, _similarity_rejected, _similarity_summary = apply_tiktok_ua_batch_similarity_filter(
            candidate_videos,
            rules,
            score_fn=lambda item: ranking_score(item, rules),
            artifact_dir=output_path.parent,
        )
        if not candidate_videos:
            print("  - No TikTok-UA hotspots found after batch similarity filter; writing empty output")
            write_hotspots(output_path, [], "hotspots", data_snapshot_path=data_snapshot_path)
            return []
        candidate_videos, _video_review_rejected, _video_review_summary = apply_tiktok_ua_video_review(
            candidate_videos,
            rules,
            artifact_dir=output_path.parent,
        )
        if not candidate_videos:
            print("  - No TikTok-UA hotspots found after video review; writing empty output")
            write_hotspots(output_path, [], "hotspots", data_snapshot_path=data_snapshot_path)
            return []
    candidate_videos = enrich_top_comments(candidate_videos, platform="tiktok")
    top_n = len(candidate_videos) if route_options.get("unlimitedOutput") else int(rules.get("quality_thresholds", {}).get("top_n", 10) or 10)
    final_videos, _deduped_videos = apply_visual_dedupe(
        candidate_videos,
        platform="tiktok",
        top_n=top_n + len(ua_geo_candidates) + len(reviewed_hot_feed_candidates),
    )
    if not final_videos:
        print("  - No TikTok hotspots found after visual dedupe; writing empty output")
        write_hotspots(output_path, [], "hotspots", data_snapshot_path=data_snapshot_path)
        return []
    final_videos = apply_ai_intros(final_videos)
    final_videos = mark_pipeline_variant(final_videos, variant)
    if variant == "product_v2":
        final_videos = apply_product_targeting(final_videos, rules)
    final_videos = force_ua_geo_push_object(final_videos, rules)
    final_videos = preserve_non_ai_product_push_object(final_videos)
    final_videos = apply_audience_targeting(final_videos, rules)
    final_videos = apply_feedback_hard_filter(final_videos, variant=variant, label="tiktok")
    final_videos = keep_required_ua_geo(final_videos, rules)
    final_videos = apply_tiktok_push_object_policy(final_videos, rules)
    if route_options.get("forcePushObject"):
        final_videos = force_route_push_object(final_videos, str(route_options["forcePushObject"]))
        final_videos = [{**item, "tiktokRoute": route_options["name"]} for item in final_videos]
    final_videos = keep_pushable_items(final_videos)
    if not final_videos:
        print("  - No TikTok hotspots found after feedback hard filter; writing empty output")
    write_hotspots(output_path, final_videos, "hotspots", data_snapshot_path=data_snapshot_path)
    return final_videos


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape and prepare TikTok social media hotspots")
    parser.add_argument("--skip-scrape", action="store_true", help="Reuse existing filtered-result.json")
    parser.add_argument("--output", type=Path, default=HOTSPOTS_FILE)
    parser.add_argument("--input-data", type=Path, default=DATA_FILE, help="Read TikTok normalized input from this JSON file")
    parser.add_argument("--route-profile", choices=["main", "ua", "product"], default="main")
    parser.add_argument(
        "--no-data-snapshot",
        action="store_true",
        help="Do not rewrite the TikTok scraper filtered-result.json snapshot after filtering",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env()
    if not args.skip_scrape:
        if not check_dependencies():
            return 1
        exit_code = run_tiktok_scraper()
        if exit_code != 0:
            if can_continue_after_scraper_failure():
                print(f"WARNING: TikTok scraper failed with exit code {exit_code}; continuing with partial checkpoint data")
            else:
                print(f"ERROR: TikTok scraper failed with exit code {exit_code}")
                return exit_code
    try:
        process_scraper_output(
            args.output,
            input_data=args.input_data,
            data_snapshot_path=None if args.no_data_snapshot else DATA_FILE,
            route_profile=args.route_profile,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
