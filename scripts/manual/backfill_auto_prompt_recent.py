from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
BASE_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from auto_prompt_extraction import extract_auto_prompt
from env_utils import load_env, resolve_bitable_config
from feishu_push import (
    WRITE_FIELD_NAMES,
    _field_to_text,
    _field_to_url,
    fetch_table_field_names,
    get_tenant_access_token,
    split_batches,
)


SHANGHAI_TZ = timezone(timedelta(hours=8))
AUDIT_DIR = BASE_DIR / "skill_runs" / "manual_audits"
AUTO_PROMPT_FIELD = WRITE_FIELD_NAMES["auto_prompt"]


def feishu_headers() -> tuple[dict[str, str], dict[str, str]]:
    load_env()
    cfg = resolve_bitable_config()
    app_id = load_env().get("FEISHU_APP_ID", "")
    app_secret = load_env().get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret or not cfg.get("app_token") or not cfg.get("table_id"):
        raise RuntimeError("Missing Feishu bitable credentials")
    token = get_tenant_access_token(app_id, app_secret)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}, cfg


def fetch_all_records(headers: dict[str, str], app_token: str, table_id: str) -> list[dict[str, Any]]:
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/search"
    records: list[dict[str, Any]] = []
    page_token = ""
    while True:
        body: dict[str, Any] = {"automatic_fields": True}
        params: dict[str, Any] = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        resp = requests.post(url, headers=headers, params=params, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to fetch Feishu records: {data}")
        payload = data.get("data") or {}
        records.extend(payload.get("items") or [])
        if not payload.get("has_more"):
            return records
        page_token = payload.get("page_token") or ""
        if not page_token:
            return records


def push_timestamp_ms(record: dict[str, Any]) -> int:
    value = (record.get("fields") or {}).get(WRITE_FIELD_NAMES["push_date"])
    if isinstance(value, (int, float)):
        return int(value)
    text = _field_to_text(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=SHANGHAI_TZ)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return 0


def normalize_url(value: Any) -> str:
    return _field_to_url(value).strip()


def url_from_item(item: dict[str, Any]) -> str:
    video_meta = item.get("videoMeta") if isinstance(item.get("videoMeta"), dict) else {}
    raw_source = item.get("raw_source") if isinstance(item.get("raw_source"), dict) else {}
    for value in [
        item.get("hotspotUrl"),
        item.get("webVideoUrl"),
        item.get("url"),
        item.get("shareUrl"),
        item.get("canonicalUrl"),
        video_meta.get("webVideoUrl"),
        raw_source.get("hotspotUrl"),
        raw_source.get("webVideoUrl"),
        raw_source.get("url"),
        raw_source.get("shareUrl"),
    ]:
        url = normalize_url(value)
        if url.startswith("http"):
            return url
    return ""


def iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def load_local_hotspot_map() -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    roots = [
        BASE_DIR / "skill_runs" / "hotspots.json",
        BASE_DIR / "skill_runs" / "hotspots_tiktok.json",
        BASE_DIR / "skill_runs" / "hotspots_x.json",
        BASE_DIR / "skill_runs" / "hotspots_ins.json",
        BASE_DIR / "skill_runs" / "manual_audits",
        BASE_DIR / "skill_runs" / "scrape_checkpoints",
        BASE_DIR / "skill_runs" / "tiktok_hot_feed",
    ]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.exists():
            files.extend(root.rglob("*.json"))
    for path in files:
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                continue
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        for item in iter_dicts(data):
            url = url_from_item(item)
            if url and url not in mapping:
                mapping[url] = item
    return mapping


def record_to_item(record: dict[str, Any], local_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    fields = record.get("fields") or {}
    url = normalize_url(fields.get(WRITE_FIELD_NAMES["url"]))
    base = dict(local_map.get(url) or {})
    base["hotspotUrl"] = url or base.get("hotspotUrl") or base.get("url")
    base["hotspotIntro"] = base.get("hotspotIntro") or _field_to_text(fields.get(WRITE_FIELD_NAMES["intro"]))
    base["hotspotPlatform"] = base.get("hotspotPlatform") or _field_to_text(fields.get(WRITE_FIELD_NAMES["platform"]))
    base["playCount"] = base.get("playCount") or _field_to_text(fields.get(WRITE_FIELD_NAMES["plays"]))
    base["diggCount"] = base.get("diggCount") or _field_to_text(fields.get(WRITE_FIELD_NAMES["likes"]))
    base["commentCount"] = base.get("commentCount") or _field_to_text(fields.get(WRITE_FIELD_NAMES["comments"]))
    return base


def build_updates(records: list[dict[str, Any]], local_map: dict[str, dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    sorted_records = sorted(records, key=push_timestamp_ms, reverse=True)
    updates: list[dict[str, Any]] = []
    env = load_env()
    for record in sorted_records[:limit]:
        item = record_to_item(record, local_map)
        extracted = extract_auto_prompt(item, env)
        prompt = str(extracted.get("autoPromptText") or "")
        fields = record.get("fields") or {}
        updates.append(
            {
                "record_id": record.get("record_id", ""),
                "url": normalize_url(fields.get(WRITE_FIELD_NAMES["url"])),
                "pushDateMs": push_timestamp_ms(record),
                "platform": _field_to_text(fields.get(WRITE_FIELD_NAMES["platform"])),
                "prompt": prompt,
                "extraction": extracted.get("autoPromptExtraction") or {},
                "sourceRehydrate": extracted.get("sourceRehydrate") or {},
                "fields": {AUTO_PROMPT_FIELD: prompt},
            }
        )
    return updates


def write_updates(headers: dict[str, str], app_token: str, table_id: str, updates: list[dict[str, Any]]) -> int:
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update"
    records = [{"record_id": item["record_id"], "fields": item["fields"]} for item in updates if item.get("record_id")]
    count = 0
    for batch in split_batches(records, 500):
        resp = requests.post(url, headers=headers, json={"records": batch}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Auto prompt backfill failed: {data}")
        count += len(data.get("data", {}).get("records", []))
    return count


def save_report(report: dict[str, Any]) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(SHANGHAI_TZ).strftime("%Y%m%d_%H%M%S")
    path = AUDIT_DIR / f"auto_prompt_recent_{run_id}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill auto prompt extraction for recent Feishu pushes")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        headers, cfg = feishu_headers()
        token = headers["Authorization"].replace("Bearer ", "", 1)
        fields = fetch_table_field_names(token, cfg["app_token"], cfg["table_id"])
        if AUTO_PROMPT_FIELD not in fields:
            raise RuntimeError(f"Feishu field does not exist: {AUTO_PROMPT_FIELD}")
        records = fetch_all_records(headers, cfg["app_token"], cfg["table_id"])
        local_map = load_local_hotspot_map()
        updates = build_updates(records, local_map, max(args.limit, 1))
        updated = 0 if args.dry_run else write_updates(headers, cfg["app_token"], cfg["table_id"], updates)
        report = {
            "limit": max(args.limit, 1),
            "dryRun": bool(args.dry_run),
            "matched": len(updates),
            "updated": updated,
            "promptCount": sum(1 for item in updates if item.get("prompt")),
            "updates": [
                {
                    "url": item["url"],
                    "platform": item["platform"],
                    "prompt": item["prompt"],
                    "reason": (item.get("extraction") or {}).get("reason", ""),
                    "error": (item.get("extraction") or {}).get("error", ""),
                    "cookieUsed": (item.get("sourceRehydrate") or {}).get("cookieUsed", False),
                    "cookieDomain": (item.get("sourceRehydrate") or {}).get("cookieDomain", ""),
                    "htmlStatus": (item.get("sourceRehydrate") or {}).get("htmlStatus", ""),
                    "cacheHit": (item.get("sourceRehydrate") or {}).get("cacheHit", False),
                    "localCacheHit": (item.get("sourceRehydrate") or {}).get("localCacheHit", False),
                    "sourceRehydrate": item.get("sourceRehydrate") or {},
                }
                for item in updates
            ],
        }
        path = save_report(report)
        report["reportPath"] = str(path)
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
