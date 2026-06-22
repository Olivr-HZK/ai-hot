from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = BASE_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from tiktok_ua_video_review import load_cache, review_config, review_item, summarize, write_artifacts


def item_url(item: dict[str, Any]) -> str:
    return str(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url") or "").split("?", 1)[0]


def read_items(run_dir: Path) -> list[dict[str, Any]]:
    slim_path = run_dir / "11_visual_dedupe_kept_379_by_play.json"
    candidates_path = run_dir / "07_candidates.json"
    slim_payload = json.loads(slim_path.read_text(encoding="utf-8-sig"))
    slim_items = slim_payload.get("items") if isinstance(slim_payload, dict) else slim_payload
    candidates = json.loads(candidates_path.read_text(encoding="utf-8-sig"))
    by_url = {item_url(item): item for item in candidates if item_url(item)}
    items: list[dict[str, Any]] = []
    for slim_item in slim_items:
        full = by_url.get(item_url(slim_item))
        if not full:
            continue
        updated = dict(full)
        updated["visualDedupeRank"] = slim_item.get("rank")
        updated["visualDedupePlayRank"] = slim_item.get("rank")
        items.append(updated)
    return items


def write_approved_outputs(output_dir: Path, kept: list[dict[str, Any]], total: int) -> None:
    sorted_kept = sorted(kept, key=lambda item: int(float(item.get("playCount") or 0)), reverse=True)
    output_dir.joinpath("approved_by_video_review.json").write_text(
        json.dumps(sorted_kept, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = ["# TikTok-UA Video Review Approved", "", f"Summary: approved {len(kept)} / {total}", ""]
    for rank, item in enumerate(sorted_kept, 1):
        review = item.get("tiktokUaVideoReview") if isinstance(item.get("tiktokUaVideoReview"), dict) else {}
        products = ",".join(str(value) for value in review.get("matchedProducts") or [])
        formats = ",".join(str(value) for value in review.get("templateFormats") or [])
        url = item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url") or ""
        text = str(item.get("text") or item.get("desc") or item.get("title") or "").replace("\n", " ")[:140]
        lines.append(f"{rank}. {item.get('playCount', 0)} views | {products} | {formats} | {url} | {text}")
    output_dir.joinpath("approved_by_video_review.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit prior TikTok-UA visual-dedupe kept items with OpenRouter video review")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--progress-every", type=int, default=10)
    args = parser.parse_args()

    run_dir = args.run_dir if args.run_dir.is_absolute() else BASE_DIR / args.run_dir
    output_dir = args.output_dir or run_dir / "ua_video_review_379_openrouter"
    output_dir = output_dir if output_dir.is_absolute() else BASE_DIR / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    items = read_items(run_dir)
    cfg = review_config({})
    cached = load_cache(output_dir)
    reviewed: list[dict[str, Any]] = []
    started = time.time()
    progress_path = output_dir / "progress.json"
    progress_every = max(1, int(args.progress_every or 10))

    print(f"starting total={len(items)} model={cfg['model']} concurrency={cfg['max_concurrency']}", flush=True)
    with ThreadPoolExecutor(max_workers=int(cfg["max_concurrency"])) as executor:
        futures = [executor.submit(review_item, item, cfg, cached) for item in items]
        for index, future in enumerate(as_completed(futures), 1):
            reviewed_item = future.result()
            reviewed.append(reviewed_item)
            review = reviewed_item.get("tiktokUaVideoReview") if isinstance(reviewed_item.get("tiktokUaVideoReview"), dict) else {}
            cache_key = review.get("cacheKey")
            if cache_key:
                cached[str(cache_key)] = review
            if index % progress_every == 0 or index == len(items):
                kept = [item for item in reviewed if (item.get("tiktokUaVideoReview") or {}).get("allow")]
                rejected = [item for item in reviewed if not (item.get("tiktokUaVideoReview") or {}).get("allow")]
                summary = summarize(reviewed)
                summary["model"] = cfg["model"]
                summary["frameMode"] = cfg["frame_mode"]
                summary["completed"] = index
                summary["total"] = len(items)
                summary["elapsedSeconds"] = round(time.time() - started, 2)
                write_artifacts(output_dir, kept, rejected, summary)
                progress_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                write_approved_outputs(output_dir, kept, len(items))
                print(
                    f"progress {index}/{len(items)} allowed={summary['allowed']} "
                    f"rejected={summary['rejected']} modelFailed={summary['modelFailed']} cacheHit={summary['cacheHit']}",
                    flush=True,
                )

    kept = [item for item in reviewed if (item.get("tiktokUaVideoReview") or {}).get("allow")]
    rejected = [item for item in reviewed if not (item.get("tiktokUaVideoReview") or {}).get("allow")]
    summary = summarize(reviewed)
    summary["model"] = cfg["model"]
    summary["frameMode"] = cfg["frame_mode"]
    summary["completed"] = len(reviewed)
    summary["total"] = len(items)
    summary["elapsedSeconds"] = round(time.time() - started, 2)
    write_artifacts(output_dir, kept, rejected, summary)
    progress_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_approved_outputs(output_dir, kept, len(items))
    print(f"done approved={len(kept)} rejected={len(rejected)} elapsed={summary['elapsedSeconds']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
