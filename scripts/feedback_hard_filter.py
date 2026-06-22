from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any

import requests

from env_utils import load_env, resolve_bitable_config
from feedback_field_utils import (
    field_url,
    material_feedback,
    normalize_acceptance,
)
from pipeline_variant import resolve_pipeline_variant


WRITE_FIELD_NAMES = {
    "push_date": "\u63a8\u9001\u65e5\u671f",
    "intro": "\u70ed\u70b9\u7b80\u4ecb",
    "platform": "\u70ed\u70b9\u5e73\u53f0",
    "url": "\u70ed\u70b9\u94fe\u63a5",
    "plays": "\u64ad\u653e\u91cf",
    "likes": "\u70b9\u8d5e\u6570",
    "comments": "\u8bc4\u8bba\u6570",
    "publish_days": "\u53d1\u5e03\u5929\u6570",
    "heat": "\u70ed\u5ea6\u8bc4\u5206",
    "push_object": "\u63a8\u9001\u5bf9\u8c61",
}

def parse_feishu_date(value: Any) -> date | None:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000).date()
    text = field_text(value)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Failed to get tenant token: {data}")
    return data["tenant_access_token"]


def record_to_feedback(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fields") or {}
    feedback = material_feedback(fields)
    return {
        "record_id": record.get("record_id", ""),
        "push_date": parse_feishu_date(fields.get(WRITE_FIELD_NAMES["push_date"])),
        "url": field_url(fields.get(WRITE_FIELD_NAMES["url"])),
        **feedback,
    }


def fetch_feedback_history(days: int = 15, today: date | None = None, limit: int = 500) -> list[dict[str, Any]]:
    env = load_env()
    cfg = resolve_bitable_config()
    app_id = os.environ.get("FEISHU_APP_ID") or env.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET") or env.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret or not cfg.get("app_token") or not cfg.get("table_id"):
        return []
    token = get_tenant_access_token(app_id, app_secret)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{cfg['app_token']}/tables/{cfg['table_id']}/records/search"
    cutoff = (today or date.today()) - timedelta(days=days)
    rows: list[dict[str, Any]] = []
    page_token = ""
    while len(rows) < limit:
        body: dict[str, Any] = {"page_size": min(500, limit - len(rows)), "automatic_fields": True}
        if page_token:
            body["page_token"] = page_token
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to fetch feedback records for hard filter: {data}")
        payload = data.get("data", {})
        for record in payload.get("items", []):
            row = record_to_feedback(record)
            push_date = row.get("push_date")
            if isinstance(push_date, date) and push_date < cutoff:
                continue
            if row.get("url") and (row.get("material_acceptance") or row.get("material_reason")):
                rows.append(row)
        if not payload.get("has_more"):
            break
        page_token = payload.get("page_token") or ""
        if not page_token:
            break
    return rows


def item_url(item: dict[str, Any]) -> str:
    return str(item.get("hotspotUrl") or item.get("url") or item.get("webVideoUrl") or item.get("upsertKey") or "").strip()


def feedback_by_url(history: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in history:
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        existing = result.get(url)
        row_date = row.get("push_date")
        existing_date = existing.get("push_date") if existing else None
        if not existing or (isinstance(row_date, date) and (not isinstance(existing_date, date) or row_date >= existing_date)):
            result[url] = row
    return result


def legacy_hard_block(row: dict[str, Any]) -> bool:
    return normalize_acceptance(row.get("material_acceptance", "")) == "\u5426\u51b3"


def apply_material_feedback_filter(item: dict[str, Any], row: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    if not legacy_hard_block(row):
        updated = dict(item)
        updated["feedbackHardFilter"] = {
            "action": "keep",
            "historyUrl": row.get("url", ""),
            "materialAcceptance": row.get("material_acceptance", ""),
            "materialReason": row.get("material_reason", ""),
        }
        return updated, ""
    updated = dict(item)
    updated["feedbackHardFilter"] = {
        "action": "remove",
        "historyUrl": row.get("url", ""),
        "materialAcceptance": row.get("material_acceptance", ""),
        "materialReason": row.get("material_reason", ""),
    }
    return None, "blocked by historical material feedback"


def apply_feedback_hard_filter(
    items: list[dict[str, Any]],
    variant: str | None = None,
    history: list[dict[str, Any]] | None = None,
    history_days: int = 15,
    label: str = "",
) -> list[dict[str, Any]]:
    resolved_variant = variant or resolve_pipeline_variant()
    try:
        rows = history if history is not None else fetch_feedback_history(days=history_days)
    except Exception as exc:
        print(f"  - Feedback hard filter skipped{f' for {label}' if label else ''}: {exc}", flush=True)
        return items
    by_url = feedback_by_url(rows)
    kept: list[dict[str, Any]] = []
    removed = 0
    retargeted = 0
    for item in items:
        url = item_url(item)
        row = by_url.get(url)
        if not row:
            kept.append(item)
            continue
        if resolved_variant == "legacy":
            if legacy_hard_block(row):
                removed += 1
                continue
            kept.append(item)
            continue
        updated, reason = apply_material_feedback_filter(item, row)
        if updated is None:
            removed += 1
            continue
        kept.append(updated)
    if removed or retargeted:
        suffix = f" for {label}" if label else ""
        print(f"  - Feedback hard filter{suffix}: removed {removed}, retargeted 0, kept {len(kept)}/{len(items)}", flush=True)
    return kept
