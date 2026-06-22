from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / "scripts"))

from env_utils import load_env, resolve_bitable_config
from feedback_field_utils import (
    MATERIAL_ACCEPTANCE_FIELD,
    MATERIAL_REASON_FIELD,
    material_feedback,
)
from feishu_push import WRITE_FIELD_NAMES, get_tenant_access_token


FEEDBACK_FIELDS = [
    MATERIAL_ACCEPTANCE_FIELD,
    MATERIAL_REASON_FIELD,
]

LOGIC_MARKER_PATTERN = re.compile(r"\[logic:\s*(legacy|product_v2)\]", re.IGNORECASE)


def normalize_field_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or value.get("link") or "").strip()
    if isinstance(value, list):
        return " ".join(normalize_field_value(item) for item in value if item is not None).strip()
    return str(value).strip()


def normalize_url_field(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or "").strip()
    if isinstance(value, list):
        for item in value:
            text = normalize_url_field(item)
            if text.startswith("http"):
                return text
        return " ".join(normalize_url_field(item) for item in value if item is not None).strip()
    return normalize_field_value(value)


def logic_variant_from_intro(value: Any) -> str:
    match = LOGIC_MARKER_PATTERN.search(normalize_field_value(value))
    return match.group(1).lower() if match else ""


def parse_feishu_date(value: Any) -> date | None:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000).date()
    text = normalize_field_value(value)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def fetch_records(limit: int = 500) -> list[dict[str, Any]]:
    load_env()
    cfg = resolve_bitable_config()
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret or not cfg["app_token"] or not cfg["table_id"]:
        raise RuntimeError("Missing Feishu bitable credentials")
    token = get_tenant_access_token(app_id, app_secret)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{cfg['app_token']}/tables/{cfg['table_id']}/records/search"
    body: dict[str, Any] = {"page_size": min(limit, 500), "automatic_fields": True}
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Failed to fetch feedback records: {data}")
    return data.get("data", {}).get("items", [])


def record_to_feedback(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fields") or {}
    intro = normalize_field_value(fields.get(WRITE_FIELD_NAMES["intro"]))
    feedback = material_feedback(fields)
    return {
        "record_id": record.get("record_id", ""),
        "push_date": parse_feishu_date(fields.get(WRITE_FIELD_NAMES["push_date"])),
        "intro": intro,
        "logic_variant": logic_variant_from_intro(intro),
        "platform": normalize_field_value(fields.get(WRITE_FIELD_NAMES["platform"])),
        "url": normalize_url_field(fields.get(WRITE_FIELD_NAMES["url"])),
        "plays": normalize_field_value(fields.get(WRITE_FIELD_NAMES["plays"])),
        "likes": normalize_field_value(fields.get(WRITE_FIELD_NAMES["likes"])),
        "comments": normalize_field_value(fields.get(WRITE_FIELD_NAMES["comments"])),
        "publish_days": normalize_field_value(fields.get(WRITE_FIELD_NAMES["publish_days"])),
        "heat": normalize_field_value(fields.get(WRITE_FIELD_NAMES["heat"])),
        **feedback,
    }


def has_feedback(row: dict[str, Any]) -> bool:
    return any(row.get(key) for key in ["material_acceptance", "material_reason"])


def collect_recent_feedback(days: int = 1, today: date | None = None) -> list[dict[str, Any]]:
    today = today or date.today()
    cutoff = today - timedelta(days=days)
    end_date = today - timedelta(days=1)
    rows = []
    for record in fetch_records():
        row = record_to_feedback(record)
        push_date = row.get("push_date")
        if isinstance(push_date, date) and (push_date < cutoff or push_date > end_date):
            continue
        if has_feedback(row):
            rows.append(row)
    return rows
