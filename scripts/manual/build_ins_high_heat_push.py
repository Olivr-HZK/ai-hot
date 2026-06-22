from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
BASE_DIR = SCRIPTS_DIR.parent
INSTAGRAM_DIR = SCRIPTS_DIR / "instagram"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(INSTAGRAM_DIR))

from env_utils import load_env
from ins_ai_intro import apply_ins_ai_intros
from ins_rules import load_ins_rules, resolve_path
from ins_scoring import (
    clean_text,
    normalize_ins_post,
    parse_ins_datetime,
    passes_media_policy,
    passes_quality,
    ranking_score,
    within_lookback,
)
from ins_storage import apply_high_heat_filter
from pipeline_variant import mark_pipeline_variant, resolve_pipeline_variant


INS_RUNS_DIR = BASE_DIR / "skill_runs" / "instagram"
RAW_POSTS_FILE = INS_RUNS_DIR / "raw_posts.json"
MANUAL_AUDIT_DIR = BASE_DIR / "skill_runs" / "manual_audits"
DEFAULT_OUTPUT = MANUAL_AUDIT_DIR / f"ins_high_heat_push_{datetime.now().strftime('%Y%m%d')}.json"


def latest_daily_scrape_cutoff(rules: dict[str, Any]) -> str | None:
    db_path = resolve_path((rules.get("database") or {}).get("path", "skill_runs/instagram/instagram_hotspots.sqlite"))
    if not db_path.exists():
        return None
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT crawled_at FROM crawl_runs WHERE stage = ? ORDER BY id DESC LIMIT 1",
            ("daily_scrape",),
        ).fetchone()
    return str(row["crawled_at"]) if row else None


def build_intro(item: dict[str, Any], rank: int) -> str:
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    username = clean_text(author.get("nickName") or author.get("uniqueId") or author.get("name"))
    author_text = f"@{username}" if username else "Instagram creator"
    media = clean_text(item.get("mediaType") or "post") or "post"
    caption = clean_text(item.get("text") or item.get("title") or item.get("summary"), max_len=120)
    high_heat = item.get("insHighHeat") if isinstance(item.get("insHighHeat"), dict) else {}
    baseline = clean_text(high_heat.get("baselineType") or "creator baseline")
    return (
        f"Manual INS high-heat candidate: {author_text}'s {media} ranked Top {rank}. "
        f"Likes {item.get('diggCount', 0)}, comments {item.get('commentCount', 0)}, "
        f"heat {item.get('heatValue', 0)}. Baseline: {baseline}. "
        f"Caption: {caption or 'no caption'}"
    )


def build_items(raw_posts: list[dict[str, Any]], rules: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    lookback = int((rules.get("creator_pool") or {}).get("lookback_hours", 48) or 48)
    normalized = [normalize_ins_post(item, rules) for item in raw_posts if isinstance(item, dict)]
    recent = [item for item in normalized if within_lookback(item, lookback)]
    media_filtered = [item for item in recent if passes_media_policy(item, rules)]
    high_heat = apply_high_heat_filter(
        media_filtered,
        rules,
        baseline_cutoff_iso=latest_daily_scrape_cutoff(rules) or datetime.now().isoformat(),
    )
    quality = [item for item in high_heat if passes_quality(item, rules)]
    selected = sorted(quality, key=lambda item: ranking_score(item, rules), reverse=True)[:limit]
    selected = mark_pipeline_variant(selected, resolve_pipeline_variant())
    now = datetime.now()
    for index, item in enumerate(selected, 1):
        dt = parse_ins_datetime(item)
        item["publishDays"] = int(max(0, (now - dt).total_seconds()) // 86400) if dt else 0
        item["heatValue"] = ranking_score(item, rules)
        item["pushObject"] = "UA"
        item["hotspotIntro"] = build_intro(item, index)
        item["uaMaterialTargeting"] = {
            "platform": "ins",
            "candidateRank": index,
            "reason": "manual INS high-heat supplemental candidate",
            "source": "ins_high_heat_manual_push",
        }
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local Instagram high-heat manual payload without scraping, Feishu writes, or Feishu pushes."
    )
    parser.add_argument("--raw-posts", type=Path, default=RAW_POSTS_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-n", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    load_env()
    args = parse_args()
    rules = load_ins_rules()
    data = json.loads(args.raw_posts.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError(f"INS raw posts JSON must contain a list: {args.raw_posts}")
    items = build_items(data, rules, max(1, args.top_n))
    items = apply_ins_ai_intros(items, rules)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "items": len(items)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
