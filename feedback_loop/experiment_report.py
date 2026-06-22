from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from feishu_feedback import collect_recent_feedback
from optimizer import normalize_acceptance


OUTPUT_DIR = BASE_DIR / "skill_runs" / "experiments"
VARIANTS = ["legacy", "product_v2", "unknown"]


def is_high_quality(row: dict[str, Any]) -> bool:
    return normalize_acceptance(row.get("material_acceptance", "")) == "\u9ad8"


def is_low_quality(row: dict[str, Any]) -> bool:
    return normalize_acceptance(row.get("material_acceptance", "")) in {"\u4f4e", "\u5426\u51b3"}


def pct(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


def summarize(rows: list[dict[str, Any]], min_feedback: int) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        variant = str(row.get("logic_variant") or "unknown").lower()
        if variant not in VARIANTS:
            variant = "unknown"
        groups[variant].append(row)
    summary: dict[str, Any] = {}
    for variant in VARIANTS:
        items = groups.get(variant, [])
        valid = [
            item
            for item in items
            if normalize_acceptance(item.get("material_acceptance", ""))
        ]
        medium_quality = sum(1 for item in valid if normalize_acceptance(item.get("material_acceptance", "")) == "\u4e2d")
        high_quality = sum(1 for item in valid if is_high_quality(item))
        low_quality = sum(1 for item in valid if is_low_quality(item))
        total = len(valid)
        summary[variant] = {
            "records": len(items),
            "valid_feedback": total,
            "status": "ok" if total >= min_feedback else "insufficient_data",
            "medium_quality_count": medium_quality,
            "medium_quality_rate": pct(medium_quality, total),
            "high_quality_count": high_quality,
            "high_quality_rate": pct(high_quality, total),
            "low_quality_count": low_quality,
            "low_quality_rate": pct(low_quality, total),
        }
    return summary


def markdown_report(summary: dict[str, Any], days: int, min_feedback: int) -> str:
    lines = [
        f"# Pipeline Variant Experiment Report\n\n",
        f"- Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"- Window: last {days} days\n",
        f"- Minimum feedback per variant: {min_feedback}\n\n",
        "| Variant | Status | Valid Feedback | High Quality Rate | Medium Rate | Low Quality Rate |\n",
        "| --- | --- | ---: | ---: | ---: | ---: |\n",
    ]
    for variant in VARIANTS:
        item = summary.get(variant, {})
        lines.append(
            f"| {variant} | {item.get('status')} | {item.get('valid_feedback', 0)} | "
            f"{item.get('high_quality_rate', 0):.2%} | {item.get('medium_quality_rate', 0):.2%} | "
            f"{item.get('low_quality_rate', 0):.2%} |\n"
        )
    return "".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare legacy vs product_v2 pipeline feedback quality")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--min-feedback", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = collect_recent_feedback(days=args.days)
    summary = summarize(rows, min_feedback=args.min_feedback)
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days": args.days,
        "min_feedback": args.min_feedback,
        "summary": summary,
    }
    if args.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(markdown_report(summary, args.days, args.min_feedback))
        return 0
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = date.today().strftime("%Y%m%d")
    json_path = OUTPUT_DIR / f"{stamp}_variant_report.json"
    md_path = OUTPUT_DIR / f"{stamp}_variant_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_report(summary, args.days, args.min_feedback), encoding="utf-8")
    print(json.dumps({"rows": len(rows), "json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
