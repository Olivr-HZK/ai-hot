from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
BASE_DIR = SCRIPTS_DIR.parent
INSTAGRAM_DIR = SCRIPTS_DIR / "instagram"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(INSTAGRAM_DIR))

from audience_targeting import apply_audience_targeting
from env_utils import load_env
from feedback_hard_filter import apply_feedback_hard_filter
from feedback_rules import is_excluded_by_rules, load_feedback_rules, ranking_score as core_ranking_score
from instagram.ins_product_fit import apply_product_fit as apply_ins_product_fit
from instagram.ins_product_review import apply_product_v2_review
from instagram.ins_rules import load_ins_rules
from instagram.ins_safety_review import apply_ins_safety_review
from instagram.ins_scoring import (
    normalize_ins_post,
    passes_media_policy,
    ranking_score as ins_ranking_score,
    within_lookback,
)
from phase1_scrape import (
    force_ua_geo_push_object,
    keep_pushable_items,
    normalize_hotspot,
)
from phase1_scrape_x import (
    apply_product_manual_ua_review,
    apply_x_product_first_targeting,
    keep_x_product_side_only,
    normalize_x_hotspot,
    x_team_demand_details,
)
from pipeline_variant import mark_pipeline_variant, resolve_pipeline_variant
from product_targeting import apply_product_targeting
from scrape_checkpoint import platform_checkpoint_dir, read_latest_status
from ua_material_review import (
    apply_ua_material_review,
    force_ua_material_push_object,
    mark_ua_material_candidates,
    merge_unique_preserving_ua_material,
)
from visual_dedupe import apply_visual_dedupe
from x_safety_review import apply_x_image_safety_review
from x_team_product_review import apply_x_team_product_review


MANUAL_AUDIT_DIR = BASE_DIR / "skill_runs" / "manual_audits"
DEFAULT_OUTPUT = MANUAL_AUDIT_DIR / f"today_low_heat_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
VALID_PUSH_OBJECTS = {"UA", "ALL", "\u4ea7\u54c1"}


def read_latest_raw(platform: str) -> list[dict[str, Any]]:
    raw_path = platform_checkpoint_dir(platform) / "latest_raw.json"
    if not raw_path.exists():
        return []
    data = json.loads(raw_path.read_text(encoding="utf-8-sig"))
    return data if isinstance(data, list) else []


def item_key(item: dict[str, Any]) -> str:
    return str(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url") or item.get("upsertKey") or item.get("id") or "").strip()


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = item_key(item)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(item)
    return result


def flatten_x_raw(raw_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tweets: list[dict[str, Any]] = []
    for page in raw_pages:
        if not isinstance(page, dict):
            continue
        page_tweets = page.get("tweets")
        if isinstance(page_tweets, list):
            for tweet in page_tweets:
                if not isinstance(tweet, dict):
                    continue
                updated = dict(tweet)
                updated.setdefault("capture_source", page.get("capture_source"))
                updated.setdefault("matched_quality_creator", page.get("quality_creator"))
                tweets.append(updated)
        elif page.get("id") or page.get("url"):
            tweets.append(page)
    return dedupe_items(tweets)


def low_heat_candidates_tiktok(raw: list[dict[str, Any]], rules: dict[str, Any]) -> tuple[list[dict[str, Any]], Counter[str]]:
    stats: Counter[str] = Counter(input=len(raw))
    candidates: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            stats["invalid"] += 1
            continue
        if is_excluded_by_rules(item, rules):
            stats["excluded_by_rules"] += 1
            continue
        normalized = normalize_hotspot(item, rules=rules)
        normalized["auditPlatform"] = "tiktok"
        normalized["lowHeatScore"] = float(core_ranking_score(normalized, rules))
        normalized["heatValue"] = normalized["lowHeatScore"]
        candidates.append(normalized)
    stats["candidate"] = len(candidates)
    return candidates, stats


def low_heat_candidates_x(raw_pages: list[dict[str, Any]], rules: dict[str, Any]) -> tuple[list[dict[str, Any]], Counter[str]]:
    tweets = flatten_x_raw(raw_pages)
    stats: Counter[str] = Counter(input=len(tweets))
    candidates: list[dict[str, Any]] = []
    for item in tweets:
        if is_excluded_by_rules(item, rules, include_summary=True):
            stats["excluded_by_rules"] += 1
            continue
        normalized = normalize_x_hotspot(item, rules=rules)
        normalized["auditPlatform"] = "x"
        normalized["lowHeatScore"] = float(core_ranking_score(normalized, rules))
        normalized["heatValue"] = normalized["lowHeatScore"]
        candidates.append(normalized)
    stats["candidate"] = len(candidates)
    return candidates, stats


def low_heat_candidates_ins(raw: list[dict[str, Any]], rules: dict[str, Any]) -> tuple[list[dict[str, Any]], Counter[str]]:
    stats: Counter[str] = Counter(input=len(raw))
    lookback = int((rules.get("creator_pool") or {}).get("lookback_hours", 48) or 48)
    candidates: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            stats["invalid"] += 1
            continue
        normalized = normalize_ins_post(item, rules)
        if not within_lookback(normalized, lookback):
            stats["outside_lookback"] += 1
            continue
        if not passes_media_policy(normalized, rules):
            stats["media_policy_blocked"] += 1
            continue
        normalized["auditPlatform"] = "ins"
        normalized["lowHeatScore"] = float(ins_ranking_score(normalized, rules))
        normalized["heatValue"] = normalized["lowHeatScore"]
        candidates.append(normalized)
    stats["candidate"] = len(candidates)
    return candidates, stats


def summarize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summarized: list[dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
        product_fit = item.get("productFit") if isinstance(item.get("productFit"), dict) else {}
        ins_fit = item.get("insProductFit") if isinstance(item.get("insProductFit"), dict) else {}
        x_review = item.get("xTeamDemandReview") if isinstance(item.get("xTeamDemandReview"), dict) else {}
        product_review = item.get("productManualReview") if isinstance(item.get("productManualReview"), dict) else {}
        ua_review = item.get("uaMaterialReview") if isinstance(item.get("uaMaterialReview"), dict) else {}
        manual_ua = item.get("productManualUaReview") if isinstance(item.get("productManualUaReview"), dict) else {}
        primary_product = (
            x_review.get("primaryProduct")
            or product_review.get("primaryProduct")
            or ua_review.get("recommendedProduct")
            or manual_ua.get("recommendedProduct")
            or product_fit.get("primaryProduct")
            or ins_fit.get("primaryProduct")
            or ""
        )
        reason = (
            x_review.get("reason")
            or product_review.get("reason")
            or ua_review.get("reason")
            or manual_ua.get("reason")
            or (item.get("xTeamDemand") or {}).get("reason") if isinstance(item.get("xTeamDemand"), dict) else ""
        )
        summarized.append(
            {
                "rank": index,
                "platform": item.get("auditPlatform") or item.get("sourcePlatform") or item.get("platform"),
                "pushObject": item.get("pushObject", ""),
                "primaryProduct": primary_product,
                "author": author.get("nickName") or author.get("name") or "",
                "url": item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url") or "",
                "heat": item.get("heatValue") or item.get("lowHeatScore") or 0,
                "likes": item.get("diggCount") or item.get("likeCount") or 0,
                "comments": item.get("commentCount") or 0,
                "text": str(item.get("title") or item.get("text") or item.get("desc") or item.get("summary") or "")[:280],
                "reason": str(reason or "")[:360],
            }
        )
    return summarized


def audit_tiktok(items: list[dict[str, Any]], rules: dict[str, Any], variant: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats: dict[str, Any] = {"inputTop100": len(items)}
    if not items:
        return [], stats
    items = apply_visual_dedupe(items, platform="tiktok", top_n=max(1, len(items)))[0]
    stats["afterVisualDedupe"] = len(items)
    items = mark_pipeline_variant(items, variant)
    items = apply_product_targeting(items, rules)
    items = force_ua_geo_push_object(items, rules)
    items = apply_audience_targeting(items, rules)
    items = apply_feedback_hard_filter(items, variant=variant, label="manual_tiktok")
    items = keep_pushable_items(items)
    stats["passed"] = len(items)
    return items, stats


def audit_x(items: list[dict[str, Any]], rules: dict[str, Any], variant: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats: dict[str, Any] = {"inputTop100": len(items)}
    demand_items: list[dict[str, Any]] = []
    for item in items:
        details = x_team_demand_details(item, rules)
        if details.get("isTarget"):
            updated = dict(item)
            updated["xTeamDemand"] = details
            demand_items.append(updated)
    stats["afterTeamDemand"] = len(demand_items)
    if not demand_items:
        return [], stats
    demand_items, blocked_safety = apply_x_image_safety_review(demand_items)
    stats["blockedSafety"] = len(blocked_safety)
    stats["afterSafety"] = len(demand_items)
    if not demand_items:
        return [], stats
    demand_items = apply_visual_dedupe(demand_items, platform="x", top_n=max(1, len(demand_items)))[0]
    stats["afterVisualDedupe"] = len(demand_items)
    demand_items = mark_pipeline_variant(demand_items, variant)
    demand_items = apply_x_product_first_targeting(demand_items, rules)
    demand_items = apply_audience_targeting(demand_items, rules)
    demand_items, blocked_product = apply_x_team_product_review(demand_items, rules)
    stats["blockedProductManual"] = len(blocked_product)
    stats["afterProductManual"] = len(demand_items)
    if not demand_items:
        return [], stats
    demand_items = apply_product_manual_ua_review(demand_items, rules)
    demand_items = apply_feedback_hard_filter(demand_items, variant=variant, label="manual_x")
    demand_items = keep_x_product_side_only(demand_items)
    stats["passed"] = len(demand_items)
    return demand_items, stats


def audit_ins(items: list[dict[str, Any]], rules: dict[str, Any], variant: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats: dict[str, Any] = {"inputTop100": len(items)}
    if not items:
        return [], stats
    safe_items, blocked_safety = apply_ins_safety_review(items, rules)
    stats["blockedSafety"] = len(blocked_safety)
    stats["afterSafety"] = len(safe_items)
    if not safe_items:
        return [], stats
    fitted = apply_ins_product_fit(safe_items, rules)
    relevant = [item for item in fitted if (item.get("insProductFit") or {}).get("isRelevant")]
    stats["afterKeywordProductFit"] = len(relevant)
    reviewed_product, blocked_product = apply_product_v2_review(relevant, rules)
    stats["blockedProductManual"] = len(blocked_product)
    stats["afterProductManual"] = len(reviewed_product)
    ua_candidates = mark_ua_material_candidates(
        sorted(safe_items, key=lambda item: float(item.get("heatValue") or 0), reverse=True),
        {"ua_material_review": {"review_pool_size": max(1, len(safe_items)), "enabled": True, "daily_max": len(safe_items), "daily_min": 0, "require_model": True}},
        platform="ins",
        reason="manual low-heat Top 100 audit; no high-heat/quality threshold applied",
    )
    reviewed_ua, blocked_ua = apply_ua_material_review(ua_candidates, rules, platform="ins")
    stats["blockedUaMaterial"] = len(blocked_ua)
    stats["afterUaMaterial"] = len(reviewed_ua)
    combined = merge_unique_preserving_ua_material(reviewed_product, reviewed_ua)
    combined = apply_visual_dedupe(combined, platform="ins", top_n=max(1, len(combined)))[0] if combined else []
    stats["afterVisualDedupe"] = len(combined)
    combined = mark_pipeline_variant(combined, variant)
    combined = force_ua_material_push_object(combined)
    combined = apply_feedback_hard_filter(combined, variant=variant, label="manual_ins")
    combined = [item for item in combined if str(item.get("pushObject") or "").strip() in VALID_PUSH_OBJECTS]
    stats["passed"] = len(combined)
    return combined, stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit today's cached TikTok/X/INS data with a low heat prefilter Top 100.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    load_env()
    args = parse_args()
    variant = resolve_pipeline_variant()
    tiktok_rules = load_feedback_rules()
    ins_rules = load_ins_rules()

    raw_status = {platform: read_latest_status(platform) for platform in ["tiktok", "x", "ins"]}
    raw_data = {platform: read_latest_raw(platform) for platform in ["tiktok", "x", "ins"]}

    tiktok_candidates, tiktok_prefilter = low_heat_candidates_tiktok(raw_data["tiktok"], tiktok_rules)
    x_candidates, x_prefilter = low_heat_candidates_x(raw_data["x"], tiktok_rules)
    ins_candidates, ins_prefilter = low_heat_candidates_ins(raw_data["ins"], ins_rules)

    all_candidates = [*tiktok_candidates, *x_candidates, *ins_candidates]
    all_candidates = sorted(all_candidates, key=lambda item: float(item.get("lowHeatScore") or item.get("heatValue") or 0), reverse=True)
    top_candidates = all_candidates[: max(1, args.limit)]
    top_by_platform: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in top_candidates:
        top_by_platform[str(item.get("auditPlatform") or "")].append(item)

    passed_tiktok, tiktok_audit = audit_tiktok(top_by_platform.get("tiktok", []), tiktok_rules, variant)
    passed_x, x_audit = audit_x(top_by_platform.get("x", []), tiktok_rules, variant)
    passed_ins, ins_audit = audit_ins(top_by_platform.get("ins", []), ins_rules, variant)

    passed = sorted([*passed_tiktok, *passed_x, *passed_ins], key=lambda item: float(item.get("heatValue") or item.get("lowHeatScore") or 0), reverse=True)
    summary = {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "variant": variant,
        "limit": args.limit,
        "checkpointStatus": raw_status,
        "rawInputCounts": {platform: len(items) for platform, items in raw_data.items()},
        "lowHeatPrefilter": {
            "tiktok": dict(tiktok_prefilter),
            "x": dict(x_prefilter),
            "ins": dict(ins_prefilter),
            "totalCandidates": len(all_candidates),
            "top100ByPlatform": dict(Counter(str(item.get("auditPlatform") or "") for item in top_candidates)),
        },
        "audit": {
            "tiktok": tiktok_audit,
            "x": x_audit,
            "ins": ins_audit,
            "passedByPlatform": dict(Counter(str(item.get("auditPlatform") or item.get("sourcePlatform") or "") for item in passed)),
            "passedTotal": len(passed),
        },
        "passedItems": summarize_items(passed),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), **summary["lowHeatPrefilter"], "audit": summary["audit"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
