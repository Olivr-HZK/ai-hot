from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
BASE_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from creator_discovery import discover_and_update_creator_pool
from creator_pool import read_creator_pool
from env_utils import load_env
from feedback_hard_filter import apply_feedback_hard_filter
from ins_ai_intro import apply_ins_ai_intros
from ins_product_fit import apply_product_fit
from ins_product_review import apply_product_v2_review
from ins_rules import load_ins_rules, resolve_path
from ins_safety_review import apply_ins_safety_review
from ins_scoring import (
    clean_text,
    normalize_ins_post,
    passes_media_policy,
    passes_quality,
    ranking_score,
    within_lookback,
)
from ins_storage import apply_high_heat_filter, save_posts
from pipeline_variant import mark_pipeline_variant, resolve_pipeline_variant
from scrape_checkpoint import atomic_write_json, write_checkpoint
from provider_rapidapi import RapidApiInstagramProvider
from ua_material_review import (
    apply_ua_material_review,
    force_ua_material_push_object,
    is_ua_material_candidate,
    keep_required_ua_material,
    mark_ua_material_candidates,
    merge_unique_preserving_ua_material,
)
from visual_dedupe import apply_visual_dedupe


SKILL_RUNS_DIR = BASE_DIR / "skill_runs"
INS_RUNS_DIR = SKILL_RUNS_DIR / "instagram"
RAW_POSTS_FILE = INS_RUNS_DIR / "raw_posts.json"
HOTSPOTS_FILE = SKILL_RUNS_DIR / "hotspots_ins.json"


def build_deterministic_intro(item: dict[str, Any]) -> str:
    fit = item.get("insProductFit") if isinstance(item.get("insProductFit"), dict) else {}
    product = clean_text(fit.get("primaryProduct") or "").lower()
    caption = clean_text(item.get("text") or item.get("title") or item.get("summary"), max_len=120)
    media = clean_text(item.get("mediaType") or "post") or "post"
    author = clean_text((item.get("authorMeta") or {}).get("nickName") if isinstance(item.get("authorMeta"), dict) else "")
    push_object = clean_text(item.get("pushObject"))
    if product == "toki":
        direction = "Toki 图生视频、动态表情或照片动画玩法"
    elif product == "evoke":
        direction = "Evoke 写真、人像增强或照片风格化素材"
    elif product == "kavi":
        direction = "Kavi 自拍转视频、爆款 AI effect 或 3D figure 素材"
    elif product in {"avatar", "avatar_jigsaw", "ai_avatar_jigsaw"}:
        direction = "Avatar 头像生成、拼图挑战或 Facebook 社交分享玩法"
    elif push_object == "UA":
        direction = "UA 广告创意"
    else:
        direction = "产品功能或图片素材趋势"
    author_text = f"@{author}" if author else "INS 博主"
    if not caption:
        caption = "无文字说明"
    return (
        f"INS 高热度图片素材：{author_text} 发布了{media}内容，"
        f"点赞/评论达到该博主已有数据均值或无历史基线每日上限，适合作为{direction}参考。内容摘要：{caption}"
    )


def load_raw_posts(skip_scrape: bool, rules: dict[str, Any]) -> list[dict[str, Any]]:
    if skip_scrape:
        if not RAW_POSTS_FILE.exists():
            raise FileNotFoundError(f"INS raw posts file not found: {RAW_POSTS_FILE}")
        data = json.loads(RAW_POSTS_FILE.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            raise ValueError(f"INS raw posts JSON must contain a list: {RAW_POSTS_FILE}")
        return [item for item in data if isinstance(item, dict)]

    pool_path = resolve_path(rules.get("creator_pool", {}).get("csv_path", "AIGC-INS.csv"))
    creator_urls = read_creator_pool(pool_path)
    max_creators = int(rules.get("creator_pool", {}).get("max_creators_per_run", 24) or 24)
    if not creator_urls:
        raise RuntimeError(f"No Instagram creators found in {pool_path}")
    provider = RapidApiInstagramProvider(rules)
    if not provider.available():
        raise RuntimeError("INS_RAPIDAPI_KEY is required for INS daily scraping")
    INS_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = os.environ.get("PIPELINE_RUN_ID") or datetime.now().strftime("%Y%m%d_%H%M%S")

    def checkpoint(raw_posts_snapshot: list[dict[str, Any]], meta: dict[str, Any]) -> None:
        atomic_write_json(RAW_POSTS_FILE, raw_posts_snapshot)
        write_checkpoint(
            "ins",
            raw_posts_snapshot,
            status=str(meta.get("status") or "partial"),
            run_id=run_id,
            completed=[str(value) for value in meta.get("completed", [])],
            failed=[item for item in meta.get("failed", []) if isinstance(item, dict)],
            error=str(meta.get("error") or ""),
            extra={},
        )

    raw_posts = provider.fetch_profile_posts(creator_urls[:max_creators], checkpoint_callback=checkpoint)
    atomic_write_json(RAW_POSTS_FILE, raw_posts)
    final_status = "partial" if provider.usage.get("errors") else "full"
    write_checkpoint(
        "ins",
        raw_posts,
        status=final_status,
        run_id=run_id,
        completed=[str((item or {}).get("username") or (item or {}).get("ownerUsername") or "") for item in provider.usage.get("profiles", []) if isinstance(item, dict)],
        failed=[item for item in provider.usage.get("errors", []) if isinstance(item, dict)],
        error="",
        extra={},
    )
    usage_path = provider.write_usage("daily_scrape", extra={"profileCount": min(len(creator_urls), max_creators)})
    print(f"  - INS RapidAPI usage written: {usage_path}", flush=True)
    return raw_posts


def variant_top_n(rules: dict[str, Any], variant: str) -> int:
    quality = rules.get("quality", {}) if isinstance(rules.get("quality"), dict) else {}
    if variant == "product_v2":
        return int(quality.get("product_v2_top_n", 2) or 2)
    return int(quality.get("top_n", 5) or 5)


def filter_and_rank(raw_posts: list[dict[str, Any]], rules: dict[str, Any], variant: str) -> list[dict[str, Any]]:
    lookback = int(rules.get("creator_pool", {}).get("lookback_hours", 48) or 48)
    normalized = [normalize_ins_post(item, rules) for item in raw_posts]
    baseline_cutoff_iso = datetime.now().isoformat()
    saved_count = save_posts(normalized, rules, stage="daily_scrape")
    print(f"  - Loaded {len(normalized)} INS posts; saved {saved_count} to local database", flush=True)

    recent = [item for item in normalized if within_lookback(item, lookback)]
    print(f"  - After INS {lookback}h time filter: {len(recent)}", flush=True)

    media_filtered = [item for item in recent if passes_media_policy(item, rules)]
    print(f"  - After INS posts-only image material filter: {len(media_filtered)}", flush=True)

    high_heat = apply_high_heat_filter(media_filtered, rules, baseline_cutoff_iso=baseline_cutoff_iso)
    print(f"  - After INS creator available-history high-heat filter: {len(high_heat)}", flush=True)

    quality = [item for item in high_heat if passes_quality(item, rules)]
    print(f"  - After INS quality filter: {len(quality)}", flush=True)

    ua_material_candidates = mark_ua_material_candidates(
        sorted(quality, key=lambda item: ranking_score(item, rules), reverse=True),
        rules,
        platform="ins",
        reason="high-heat INS image/carousel material; non-AI allowed if model approves UA ad use",
    )
    print(f"  - INS UA material review candidates: {len(ua_material_candidates)}", flush=True)

    fitted = apply_product_fit(quality, rules)
    relevant = [item for item in fitted if (item.get("insProductFit") or {}).get("isRelevant")]
    print(f"  - After INS product-manual relevance filter: {len(relevant)}", flush=True)

    if variant == "product_v2":
        relevant, product_review_blocked = apply_product_v2_review(relevant, rules)
        if product_review_blocked:
            blocked_path = INS_RUNS_DIR / f"ins_product_review_blocked_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            INS_RUNS_DIR.mkdir(parents=True, exist_ok=True)
            blocked_path.write_text(json.dumps(product_review_blocked, ensure_ascii=False, indent=2), encoding="utf-8")

    combined = merge_unique_preserving_ua_material(relevant, ua_material_candidates)
    safe_items, blocked = apply_ins_safety_review(combined, rules)
    if blocked:
        blocked_path = INS_RUNS_DIR / f"ins_safety_blocked_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        INS_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        blocked_path.write_text(json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8")

    ranked = sorted(safe_items, key=lambda item: ranking_score(item, rules), reverse=True)
    for item in ranked:
        item["heatValue"] = ranking_score(item, rules)
        item["hotspotIntro"] = item.get("hotspotIntro") or build_deterministic_intro(item)
    return ranked


def apply_ins_dedupe(items: list[dict[str, Any]], rules: dict[str, Any], variant: str) -> list[dict[str, Any]]:
    top_n = variant_top_n(rules, variant)
    if not rules.get("dedupe", {}).get("enabled", True):
        regular = [item for item in items if not is_ua_material_candidate(item)][:top_n]
        ua_material = [item for item in items if is_ua_material_candidate(item)]
        return merge_unique_preserving_ua_material(regular, ua_material)
    multiplier = int(rules.get("dedupe", {}).get("candidate_multiplier", 2) or 2)
    regular = [item for item in items if not is_ua_material_candidate(item)]
    ua_material = [item for item in items if is_ua_material_candidate(item)]
    candidates = merge_unique_preserving_ua_material(regular[: max(top_n, top_n * max(1, multiplier))], ua_material)
    try:
        kept, _deduped = apply_visual_dedupe(candidates, platform="ins", top_n=top_n + len(ua_material))
        return kept
    except Exception as exc:
        print(f"  - INS visual dedupe skipped: {exc}", flush=True)
        return merge_unique_preserving_ua_material(candidates[:top_n], ua_material)


def write_hotspots(output_path: Path, items: list[dict[str, Any]]) -> None:
    items = [{**item, "pushObject": "ALL"} for item in items]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  - Wrote {len(items)} INS hotspots: {output_path}", flush=True)


def process_scraper_output(
    output_path: Path = HOTSPOTS_FILE,
    *,
    skip_scrape: bool = False,
    discover_creators: bool = False,
) -> list[dict[str, Any]]:
    rules = load_ins_rules()
    variant = resolve_pipeline_variant()
    raw_posts = load_raw_posts(skip_scrape, rules)
    if discover_creators:
        discover_and_update_creator_pool(rules=rules, seed_raw_posts=raw_posts)
    ranked = filter_and_rank(raw_posts, rules, variant)
    final_items = apply_ins_dedupe(ranked, rules, variant)
    final_items, _ua_material_blocked = apply_ua_material_review(final_items, rules, platform="ins")
    final_items = apply_ins_ai_intros(final_items, rules)
    final_items = mark_pipeline_variant(final_items, variant)
    final_items = force_ua_material_push_object(final_items)
    final_items = apply_feedback_hard_filter(final_items, variant=variant, label="ins")
    final_items = keep_required_ua_material(final_items, rules, platform="ins")
    if not final_items:
        print("  - No INS hotspots found after filtering; writing empty output", flush=True)
    write_hotspots(output_path, final_items)
    return final_items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape and prepare isolated Instagram hotspots")
    parser.add_argument("--skip-scrape", action="store_true", help="Reuse skill_runs/instagram/raw_posts.json")
    parser.add_argument("--discover-creators", action="store_true", help="Run creator discovery before post scraping")
    parser.add_argument("--output", type=Path, default=HOTSPOTS_FILE)
    return parser.parse_args()


def main() -> int:
    load_env()
    args = parse_args()
    try:
        process_scraper_output(args.output, skip_scrape=args.skip_scrape, discover_creators=args.discover_creators)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
