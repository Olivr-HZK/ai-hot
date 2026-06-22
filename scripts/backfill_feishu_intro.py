from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from urllib.parse import urlencode

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from ai_intro import generate_intro_with_retry
from env_utils import load_env, resolve_bitable_config
from feishu_push import HOTSPOTS_FILE, WRITE_FIELD_NAMES, _field_to_text, _field_to_url, get_tenant_access_token, load_hotspots, split_batches


SHANGHAI_TZ = timezone(timedelta(hours=8))


def parse_feishu_date(value: Any) -> date | None:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000, tz=SHANGHAI_TZ).date()
    text = _field_to_text(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def hotspot_url(item: dict[str, Any]) -> str:
    return str(item.get("hotspotUrl") or item.get("webVideoUrl") or (item.get("videoMeta") or {}).get("webVideoUrl") or "").strip()


def load_hotspot_map(path: Path) -> dict[str, dict[str, Any]]:
    hotspots = load_hotspots(path)
    mapping: dict[str, dict[str, Any]] = {}
    for item in hotspots:
        url = hotspot_url(item)
        if url:
            mapping[url] = item
    if not mapping:
        raise RuntimeError(f"No hotspot URLs found in {path}")
    return mapping


def get_feishu_headers() -> tuple[dict[str, str], dict[str, str]]:
    load_env()
    cfg = resolve_bitable_config()
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret or not cfg.get("app_token") or not cfg.get("table_id"):
        raise RuntimeError("Missing Feishu bitable credentials")
    token = get_tenant_access_token(app_id, app_secret)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    return headers, cfg


def fetch_all_records(headers: dict[str, str], app_token: str, table_id: str) -> list[dict[str, Any]]:
    base_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/search"
    records: list[dict[str, Any]] = []
    page_token = ""
    seen_tokens: set[str] = set()
    while True:
        query: dict[str, Any] = {"page_size": 500}
        if page_token:
            query["page_token"] = page_token
            if page_token in seen_tokens:
                raise RuntimeError("Repeated Feishu page_token detected while fetching records")
            seen_tokens.add(page_token)
        body: dict[str, Any] = {"automatic_fields": True}
        url = f"{base_url}?{urlencode(query)}"
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to fetch Feishu records: {data}")
        payload = data.get("data", {})
        records.extend(payload.get("items", []))
        if not payload.get("has_more"):
            return records
        page_token = payload.get("page_token") or ""
        if not page_token:
            return records
        if len(seen_tokens) >= 100:
            raise RuntimeError("Too many Feishu pages while fetching records")


def is_old_intro(value: str) -> bool:
    text = str(value or "").strip()
    return text.startswith("\u793e\u5a92\u70ed\u70b9+") or "+\u64ad\u653e" in text


def build_updates(records: list[dict[str, Any]], hotspots_by_url: dict[str, dict[str, Any]], target_date: date, limit: int = 0, force: bool = False) -> list[dict[str, Any]]:
    candidates: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    for record in records:
        fields = record.get("fields") or {}
        push_date = parse_feishu_date(fields.get(WRITE_FIELD_NAMES["push_date"]))
        if push_date != target_date:
            continue
        url = _field_to_url(fields.get(WRITE_FIELD_NAMES["url"])).strip()
        hotspot = hotspots_by_url.get(url)
        if not hotspot:
            continue
        old_intro = _field_to_text(fields.get(WRITE_FIELD_NAMES["intro"]))
        if not force and not is_old_intro(old_intro):
            continue
        candidates.append((record, hotspot, url))
        if limit > 0 and len(candidates) >= limit:
            break
    if not candidates:
        raise RuntimeError(f"No matching Feishu records found for {target_date.isoformat()}")
    updates: list[dict[str, Any]] = []
    for index, (record, hotspot, url) in enumerate(candidates, 1):
        print(f"  - Generating AI intro for Feishu record {index}/{len(candidates)}", flush=True)
        fields = record.get("fields") or {}
        new_intro = generate_intro_with_retry(hotspot)
        updates.append(
            {
                "record_id": record.get("record_id", ""),
                "url": url,
                "old_intro": _field_to_text(fields.get(WRITE_FIELD_NAMES["intro"])),
                "new_intro": new_intro,
                "fields": {WRITE_FIELD_NAMES["intro"]: new_intro},
            }
        )
    return updates


def write_updates(headers: dict[str, str], app_token: str, table_id: str, updates: list[dict[str, Any]]) -> int:
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update"
    count = 0
    records = [{"record_id": item["record_id"], "fields": item["fields"]} for item in updates]
    for batch in split_batches(records, 500):
        resp = requests.post(url, headers=headers, json={"records": batch}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Bitable intro backfill failed: {data}")
        count += len(data.get("data", {}).get("records", []))
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill AI hotspot intros into Feishu bitable without scraping")
    parser.add_argument("--hotspots", type=Path, default=HOTSPOTS_FILE)
    parser.add_argument("--date", default="2026-05-11", help="Feishu push date in Asia/Shanghai, YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N matched records")
    parser.add_argument("--force", action="store_true", help="Regenerate intros even when the Feishu intro already looks updated")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        target_date = date.fromisoformat(args.date)
        hotspots_by_url = load_hotspot_map(args.hotspots)
        headers, cfg = get_feishu_headers()
        records = fetch_all_records(headers, cfg["app_token"], cfg["table_id"])
        updates = build_updates(records, hotspots_by_url, target_date, limit=max(0, args.limit), force=args.force)
        preview = [
            {"url": item["url"], "old_intro": item["old_intro"], "new_intro": item["new_intro"]}
            for item in updates
        ]
        if args.dry_run:
            print(json.dumps({"date": target_date.isoformat(), "updates": preview}, ensure_ascii=True, indent=2))
            return 0
        updated = write_updates(headers, cfg["app_token"], cfg["table_id"], updates)
        print(json.dumps({"date": target_date.isoformat(), "matched": len(updates), "updated": updated, "updates": preview}, ensure_ascii=True, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
