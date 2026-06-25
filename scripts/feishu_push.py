from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from env_utils import env_bool, load_env, resolve_bitable_config
from auto_prompt_extraction import apply_auto_prompt_extraction
from feedback_hard_filter import apply_feedback_hard_filter
from feedback_field_utils import READONLY_FEISHU_FIELDS, field_url
from pipeline_variant import resolve_pipeline_variant
from scoring import safe_int


READONLY_FEEDBACK_FIELDS = READONLY_FEISHU_FIELDS

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
    "auto_prompt": "\u81ea\u52a8\u0070\u0072\u006f\u006d\u0070\u0074\u83b7\u53d6",
}

OPTIONAL_WRITE_FIELDS = {
    WRITE_FIELD_NAMES["auto_prompt"],
}

HOTSPOTS_FILE = BASE_DIR / "skill_runs" / "hotspots.json"

PLATFORM_VALUES = {
    "tt": "tiktok",
    "tiktok": "tiktok",
    "tik tok": "tiktok",
    "x": "x",
    "twitter": "x",
    "reddit": "reddit",
    "ins": "ins",
    "instagram": "ins",
}

PLATFORM_CARD_NAMES = {
    "tiktok": "TikTok",
    "x": "X",
    "reddit": "Reddit",
    "ins": "Instagram",
}

PLATFORM_BITABLE_VALUES = {
    "tiktok": "TikTok",
    "x": "X",
    "reddit": "reddit",
    "ins": "Instagram",
}

PLATFORM_MONITOR_NAMES = {
    "tiktok": "Tiktok",
    "x": "X",
    "reddit": "Reddit",
    "ins": "Instagram",
}

PUSH_OBJECT_DEFAULT = "UA"

LOGIC_MARKER_PATTERN = re.compile(r"\s*\[logic:\s*(legacy|product_v2)\]\s*$", re.IGNORECASE)
GARBLED_TEXT_PATTERN = re.compile(r"\?{3,}|\ufffd")


def feishu_date_ms(dt: datetime | None = None) -> int:
    dt = dt or datetime.now()
    return int(dt.timestamp() * 1000)


def load_hotspots(path: Path = HOTSPOTS_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Hotspots file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise ValueError("Hotspots JSON must contain a list")
    return data


def clean_inline_text(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def markdown_link_text(value: Any, max_len: int = 62) -> str:
    text = clean_inline_text(value, max_len=max_len) or "\u67e5\u770b\u5e16\u5b50"
    return text.replace("[", "\uff3b").replace("]", "\uff3d").replace("(", "\uff08").replace(")", "\uff09")


def get_post_title(item: dict[str, Any], max_len: int | None = None) -> str:
    title = item.get("title") or item.get("text") or item.get("desc") or item.get("hotspotIntro") or "\u793e\u5a92\u70ed\u70b9"
    return clean_inline_text(title, max_len=max_len)


def format_comment_preview(item: dict[str, Any], limit: int = 3) -> str:
    comments = item.get("topComments") or []
    if not isinstance(comments, list):
        return ""
    previews = [clean_inline_text(comment, max_len=80) for comment in comments[:limit]]
    previews = [comment for comment in previews if comment]
    if not previews:
        return ""
    return "\n".join(f"\u00b7 \u8bc4\u8bba: {comment}" for comment in previews)


def normalize_platform(value: Any) -> str:
    raw = clean_inline_text(value).lower()
    return PLATFORM_VALUES.get(raw, raw if raw in {"tiktok", "x", "reddit", "ins"} else "tiktok")


def item_platform(item: dict[str, Any]) -> str:
    return normalize_platform(item.get("hotspotPlatform") or item.get("sourcePlatform") or item.get("platform") or "tiktok")


def card_platform_name(platform: str) -> str:
    return PLATFORM_CARD_NAMES.get(normalize_platform(platform), clean_inline_text(platform) or "TikTok")


def bitable_platform_name(platform: str) -> str:
    normalized = normalize_platform(platform)
    return PLATFORM_BITABLE_VALUES.get(normalized, PLATFORM_BITABLE_VALUES["tiktok"])


def monitor_platforms(hotspots: list[dict[str, Any]]) -> str:
    values: list[str] = []
    for item in hotspots:
        platform = item_platform(item)
        if platform not in values:
            values.append(platform)
    if not values:
        values = ["tiktok"]
    return " / ".join(PLATFORM_MONITOR_NAMES.get(value, card_platform_name(value)) for value in values)


def normalize_push_object(value: Any) -> str:
    text = clean_inline_text(value).lower()
    if text in {"all", "aii"}:
        return "ALL"
    if text == "ua":
        return "UA"
    if text in {"产品", "product"}:
        return "产品"
    return PUSH_OBJECT_DEFAULT


def normalize_bitable_push_object(item: dict[str, Any]) -> str:
    if is_tiktok_product_item(item):
        return "产品"
    return normalize_push_object(item.get("pushObject"))


def append_logic_marker(intro: Any, variant: Any) -> str:
    text = LOGIC_MARKER_PATTERN.sub("", str(intro or "")).strip()
    resolved = clean_inline_text(variant or "legacy").lower()
    if resolved not in {"legacy", "product_v2"}:
        resolved = "legacy"
    suffix = f"[logic: {resolved}]"
    return f"{text} {suffix}".strip() if text else suffix


def looks_garbled_text(value: Any) -> bool:
    text = str(value or "")
    if not text:
        return False
    if GARBLED_TEXT_PATTERN.search(text):
        return True
    question_count = text.count("?")
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return question_count >= 6 and cjk_count == 0


def build_fallback_intro(item: dict[str, Any]) -> str:
    platform = item_platform(item)
    title = clean_inline_text(item.get("title") or item.get("text") or item.get("desc") or item.get("summary"), max_len=140)
    if platform == "ins":
        author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
        author_name = clean_inline_text(author.get("nickName") or author.get("uniqueId") or author.get("name"))
        media = clean_inline_text(item.get("mediaType") or "post")
        author_text = f"@{author_name}" if author_name else "Instagram 博主"
        return (
            f"Instagram 高热素材：{author_text} 的 {media} 内容进入高热候选，"
            f"点赞 {safe_int(item.get('diggCount') or item.get('likeCount'))}、"
            f"评论 {safe_int(item.get('commentCount'))}、热度 {item.get('heatValue', 0)}。"
            f"内容摘要：{title or '无文字说明'}"
        )
    return title or "社媒热点内容进入今日候选。"


def normalized_intro(item: dict[str, Any]) -> str:
    if is_tiktok_product_item(item):
        return normalized_tiktok_product_effect_intro(item)
    intro = item.get("hotspotIntro") or ""
    if looks_garbled_text(intro):
        intro = build_fallback_intro(item)
    return append_logic_marker(intro, item.get("pipelineVariant"))


def is_tiktok_product_item(item: dict[str, Any]) -> bool:
    if item_platform(item) != "tiktok":
        return False
    route = clean_inline_text(item.get("tiktokRoute")).lower()
    return route in {"product", "both"} or isinstance(item.get("tiktokProductRoute"), dict) or bool(item.get("tiktokProductEffectName"))


def normalized_tiktok_product_effect_intro(item: dict[str, Any]) -> str:
    try:
        from tiktok_product_effect_name import fallback_effect_name, validate_effect_name
    except Exception:
        effect_name = clean_inline_text(item.get("tiktokProductEffectName") or item.get("hotspotIntro"), max_len=40)
        return effect_name or "Dance Move"
    for value in [item.get("tiktokProductEffectName"), item.get("hotspotIntro")]:
        try:
            return validate_effect_name(value)
        except ValueError:
            continue
    return fallback_effect_name(item)


def build_bitable_fields(item: dict[str, Any], push_time: datetime | None = None) -> dict[str, Any]:
    platform = item_platform(item)
    intro = normalized_intro(item)
    fields = {
        WRITE_FIELD_NAMES["push_date"]: feishu_date_ms(push_time),
        WRITE_FIELD_NAMES["intro"]: intro,
        WRITE_FIELD_NAMES["platform"]: bitable_platform_name(platform),
        WRITE_FIELD_NAMES["url"]: {"text": "\u67e5\u770b\u70ed\u70b9", "link": str(item.get("hotspotUrl") or "")},
        WRITE_FIELD_NAMES["plays"]: safe_int(item.get("playCount")),
        WRITE_FIELD_NAMES["likes"]: safe_int(item.get("diggCount") or item.get("likeCount")),
        WRITE_FIELD_NAMES["comments"]: safe_int(item.get("commentCount")),
        WRITE_FIELD_NAMES["publish_days"]: safe_int(item.get("publishDays")),
        WRITE_FIELD_NAMES["heat"]: float(item.get("heatValue") or 0),
        WRITE_FIELD_NAMES["push_object"]: normalize_bitable_push_object(item),
        WRITE_FIELD_NAMES["auto_prompt"]: clean_inline_text(item.get("autoPromptText")),
    }
    return {key: value for key, value in fields.items() if key not in READONLY_FEEDBACK_FIELDS}


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


def _field_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or "")
    if isinstance(value, list):
        return " ".join(_field_to_text(item) for item in value if item is not None)
    return str(value)


def _field_to_url(value: Any) -> str:
    return field_url(value)


def fetch_existing_records(token: str, app_token: str, table_id: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/search"
    body: dict[str, Any] = {"page_size": 500, "automatic_fields": True}
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Failed to search existing records: {data}")
    mapping: dict[str, str] = {}
    for record in data.get("data", {}).get("items", []):
        fields = record.get("fields") or {}
        link_text = _field_to_url(fields.get(WRITE_FIELD_NAMES["url"]))
        if link_text:
            mapping[link_text] = record.get("record_id", "")
    return mapping


def fetch_table_field_names(token: str, app_token: str, table_id: str) -> set[str]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    names: set[str] = set()
    page_token = ""
    while True:
        params: dict[str, Any] = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to fetch bitable fields: {data}")
        payload = data.get("data") or {}
        for item in payload.get("items") or []:
            name = clean_inline_text(item.get("field_name") or item.get("fieldName"))
            if name:
                names.add(name)
        if not payload.get("has_more"):
            break
        page_token = clean_inline_text(payload.get("page_token"))
        if not page_token:
            break
    return names


def filter_fields_for_schema(fields: dict[str, Any], available_fields: set[str] | None) -> dict[str, Any]:
    if available_fields is None:
        return fields
    filtered = dict(fields)
    for field_name in OPTIONAL_WRITE_FIELDS:
        if field_name not in available_fields and field_name in filtered:
            filtered.pop(field_name, None)
    return filtered


def split_batches(items: list[Any], size: int = 500) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def write_to_bitable(hotspots: list[dict[str, Any]], dry_run: bool = False) -> dict[str, int]:
    load_env()
    cfg = resolve_bitable_config()
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret or not cfg["app_token"] or not cfg["table_id"]:
        raise RuntimeError("Missing FEISHU_APP_ID / FEISHU_APP_SECRET / BITABLE_APP_TOKEN / BITABLE_TABLE_ID")
    push_time = datetime.now()
    token = ""
    available_fields: set[str] | None = None
    auto_prompt_field = WRITE_FIELD_NAMES["auto_prompt"]
    should_extract_prompt = dry_run
    if not dry_run:
        token = get_tenant_access_token(app_id, app_secret)
        try:
            available_fields = fetch_table_field_names(token, cfg["app_token"], cfg["table_id"])
        except Exception as exc:
            print(
                f"Warning: failed to fetch bitable field schema; skipping optional auto prompt field: {exc}",
                flush=True,
            )
            available_fields = set()
        should_extract_prompt = auto_prompt_field in available_fields
        if not should_extract_prompt:
            print(
                f"Warning: bitable field '{auto_prompt_field}' does not exist; skipping auto prompt write field.",
                flush=True,
            )
    if should_extract_prompt:
        hotspots = apply_auto_prompt_extraction(hotspots)
    else:
        hotspots = [{**item, "autoPromptText": ""} for item in hotspots]
    records = []
    for item in hotspots:
        fields = build_bitable_fields(item, push_time=push_time)
        fields = filter_fields_for_schema(fields, available_fields)
        records.append({"key": str(item.get("hotspotUrl") or item.get("upsertKey") or ""), "fields": fields})
    if dry_run:
        print(json.dumps({"dry_run_records": records}, ensure_ascii=False, indent=2))
        return {"created": 0, "updated": 0}
    existing = fetch_existing_records(token, cfg["app_token"], cfg["table_id"])
    to_create: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []
    for record in records:
        record_id = existing.get(record["key"])
        if record_id:
            to_update.append({"record_id": record_id, "fields": record["fields"]})
        else:
            to_create.append({"fields": record["fields"]})
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    created = 0
    updated = 0
    if to_create:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{cfg['app_token']}/tables/{cfg['table_id']}/records/batch_create"
        for batch in split_batches(to_create):
            resp = requests.post(url, headers=headers, json={"records": batch}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Bitable batch_create failed: {data}")
            created += len(data.get("data", {}).get("records", []))
    if to_update:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{cfg['app_token']}/tables/{cfg['table_id']}/records/batch_update"
        for batch in split_batches(to_update):
            resp = requests.post(url, headers=headers, json={"records": batch}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"Bitable batch_update failed: {data}")
            updated += len(data.get("data", {}).get("records", []))
    return {"created": created, "updated": updated}


def build_card(hotspots: list[dict[str, Any]]) -> dict[str, Any]:
    bitable_url = resolve_bitable_config().get("url") or os.environ.get("FEISHU_BITABLE_URL", "")
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": (
                f"**\u76d1\u63a7\u5e73\u53f0**: {monitor_platforms(hotspots)}\n"
                f"**\u70ed\u70b9\u6570\u91cf**: {len(hotspots)}\n"
                f"**\u751f\u6210\u65f6\u95f4**: {generated_at}"
            ),
        },
        {"tag": "hr"},
    ]
    hotspot_elements: list[dict[str, Any]] = []
    for index, item in enumerate(hotspots, 1):
        platform = item_platform(item)
        platform_name = card_platform_name(platform)
        url = str(item.get("hotspotUrl") or "")
        title = markdown_link_text(get_post_title(item), max_len=58)
        comment_preview = format_comment_preview(item)
        comment_block = f"\n{comment_preview}" if comment_preview else ""
        hotspot_elements.append(
            {
                "tag": "markdown",
                "content": (
                    f"**{index}. {platform_name}\uff1a[{title}]({url})**\n"
                    f"\u00b7 \u70ed\u5ea6\u503c: {item.get('heatValue', 0)} | \u64ad\u653e: {safe_int(item.get('playCount'))} "
                    f"| \u70b9\u8d5e: {safe_int(item.get('diggCount') or item.get('likeCount'))} "
                    f"| \u8bc4\u8bba: {safe_int(item.get('commentCount'))}"
                    f"{comment_block}"
                ),
            }
        )
    elements.append(
        {
            "tag": "collapsible_panel",
            "expanded": False,
            "header": {
                "title": {"tag": "plain_text", "content": "\u70ed\u70b9\u5217\u8868"},
                "icon": {"tag": "standard_icon", "token": "down-small-ccm_outlined", "size": "16px 16px"},
                "icon_position": "right",
                "icon_expanded_angle": -180,
            },
            "border": {"color": "grey", "corner_radius": "5px"},
            "elements": hotspot_elements,
        }
    )
    if bitable_url:
        elements.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "\u98de\u4e66\u591a\u7ef4\u8868\u683c"},
                "type": "primary",
                "behaviors": [
                    {
                        "type": "open_url",
                        "default_url": bitable_url,
                        "pc_url": bitable_url,
                        "ios_url": bitable_url,
                        "android_url": bitable_url,
                    }
                ],
            }
        )
    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "\u793e\u5a92\u70ed\u70b9\u65e5\u62a5"}, "template": "blue"},
            "body": {"elements": elements},
        },
    }


def push_webhook(payload: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    webhook = os.environ.get("FEISHU_WEBHOOK", "")
    if not webhook:
        raise RuntimeError("Missing FEISHU_WEBHOOK")
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return {"dry_run": True}
    resp = requests.post(webhook, headers={"Content-Type": "application/json; charset=utf-8"}, json=payload, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") not in (0, None):
        raise RuntimeError(f"Feishu webhook push failed: {data}")
    return data


def push_and_write(hotspots_path: Path = HOTSPOTS_FILE, dry_run: bool | None = None) -> dict[str, Any]:
    env = load_env()
    resolved_dry_run = env_bool("FEISHU_DRY_RUN", False, env) if dry_run is None else dry_run
    hotspots = load_hotspots(hotspots_path)
    variant = resolve_pipeline_variant()
    hotspots = apply_feedback_hard_filter(hotspots, variant=variant, label="feishu")
    card = build_card(hotspots)
    bitable_result = write_to_bitable(hotspots, dry_run=resolved_dry_run)
    push_result = push_webhook(card, dry_run=resolved_dry_run)
    return {"push": push_result, "bitable": bitable_result}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Push social media hotspots to Feishu")
    parser.add_argument("--hotspots", type=Path, default=HOTSPOTS_FILE)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = push_and_write(args.hotspots, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
