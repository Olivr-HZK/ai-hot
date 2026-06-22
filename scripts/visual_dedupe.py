from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from env_utils import env_int, load_env, resolve_bitable_config
from scoring import safe_int


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
DEBUG_DIR = BASE_DIR / "skill_runs" / "visual_dedupe"

DEFAULT_MODEL = "qwen/qwen3.6-flash"
MODEL_FALLBACKS = ["qwen/qwen3.6-plus", "z-ai/glm-5v-turbo", "bytedance-seed/seed-2.0-lite"]
BLOCKED_MODEL_MARKERS = ["openai", "anthropic", "claude", "gemini", "google"]

MATERIAL_PATTERNS: dict[str, list[str]] = {
    "retro_movie_poster": [
        "retro poster",
        "retro movie",
        "movie poster",
        "street poster",
        "\u590d\u53e4",
        "\u7535\u5f71\u6d77\u62a5",
        "\u8857\u5934",
        "\u6d77\u62a5",
    ],
    "rainy_couple": ["rain", "rainy", "\u96e8\u591c", "\u96e8\u4e2d", "\u60c5\u4fa3", "couple"],
    "fashion_illustration": [
        "vogue-style fashion illustration",
        "vogue style fashion illustration",
        "fashion illustration",
        "fashion sketch",
        "hand-drawn fashion",
        "editorial fashion illustration",
        "minimalist hand-drawn sketch",
        "preserving identity",
        "vogue",
        "\u65f6\u5c1a\u63d2\u753b",
        "\u624b\u7ed8\u65f6\u5c1a",
        "\u65f6\u5c1a\u624b\u7ed8",
        "\u65f6\u5c1a\u8349\u56fe",
        "\u6742\u5fd7\u63d2\u753b",
        "\u4fdd\u7559\u8eab\u4efd",
        "\u4fdd\u7559\u4e94\u5b98",
    ],
    "outfit_beauty_tryon": [
        "outfit",
        "makeup",
        "hair",
        "\u53d8\u88c5",
        "\u6362\u88c5",
        "\u7f8e\u5986",
        "\u53d1\u578b",
        "\u8bd5\u5986",
    ],
    "growth_birthday_compare": [
        "birthday",
        "before after",
        "old photo",
        "\u751f\u65e5",
        "\u7ae5\u5e74",
        "\u6210\u957f",
        "\u5341\u5e74",
        "\u5bf9\u6bd4",
        "\u540c\u6846",
    ],
    "sticker_mini_doll": [
        "sticker",
        "mini doll",
        "3d q",
        "figurine",
        "\u8d34\u7eb8",
        "\u8ff7\u4f60\u4eba\u5076",
        "\u4eba\u5076",
        "q\u7248",
    ],
    "baseball_broadcast": ["baseball", "\u68d2\u7403", "\u770b\u53f0", "\u76f4\u64ad", "\u8d5b\u573a"],
    "ai_dance_bgm_ip": ["dance", "bgm", "\u821e\u8e48", "\u5361\u70b9", "\u97f3\u4e50", "\u52a8\u4f5c\u8fc1\u79fb"],
}

SUBJECT_PATTERNS: dict[str, list[str]] = {
    "real_person": [
        "person",
        "people",
        "portrait",
        "selfie",
        "couple",
        "family",
        "\u771f\u4eba",
        "\u4eba\u50cf",
        "\u4eba\u7269",
        "\u7167\u7247",
        "\u8096\u50cf",
        "\u60c5\u4fa3",
        "\u5355\u4eba",
    ],
    "anime_or_ai_girl": ["anime", "ai girl", "\u4e8c\u6b21\u5143", "\u52a8\u6f2b", "\u7f8e\u5973"],
    "animal_or_pet": ["animal", "pet", "dog", "cat", "panda", "penguin", "\u52a8\u7269", "\u5ba0\u7269", "\u718a\u732b", "\u4f01\u9e45"],
    "toy_or_character": ["toy", "mascot", "character", "cartoon", "clay", "\u73a9\u5177", "\u5361\u901a", "\u7c98\u571f", "\u89d2\u8272"],
}


def clean_text(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def normalize_key(value: str) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def item_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("title"),
        item.get("text"),
        item.get("desc"),
        item.get("hotspotIntro"),
        item.get("summary"),
        item.get("video_summary"),
        " ".join(str(comment) for comment in (item.get("topComments") or [])[:5]),
    ]
    hashtags = item.get("hashtags") or []
    if isinstance(hashtags, list):
        parts.extend(str(tag.get("name") if isinstance(tag, dict) else tag) for tag in hashtags)
    return clean_text(" ".join(str(part or "") for part in parts if part))


def match_pattern(text: str, patterns: dict[str, list[str]], default: str) -> str:
    lowered = text.lower()
    for name, keywords in patterns.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            return name
    return default


def media_urls(item: dict[str, Any], limit: int = 3) -> list[str]:
    values: list[Any] = []
    video_meta = item.get("videoMeta") or {}
    raw_source = item.get("raw_source") or {}
    for key in ["coverUrl", "originalCoverUrl", "imageUrl", "thumbnailUrl", "webVideoUrl", "downloadAddr"]:
        values.append(item.get(key))
        values.append(video_meta.get(key))
        values.append(raw_source.get(key))
    for key in ["mediaUrls", "media_urls", "image_urls", "images"]:
        value = item.get(key) or raw_source.get(key)
        if isinstance(value, list):
            values.extend(value)
    urls: list[str] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("url") or value.get("media_url_https") or value.get("media_url")
        text = str(value or "").strip()
        if text.startswith("http") and text not in urls:
            urls.append(text)
        if len(urls) >= limit:
            break
    return urls


def image_input_urls(item: dict[str, Any], limit: int = 2) -> list[str]:
    blocked_suffixes = (".mp4", ".m3u8", ".mov", ".webm")
    urls: list[str] = []
    for url in media_urls(item, limit=8):
        lowered = url.lower().split("?", 1)[0]
        if lowered.endswith(blocked_suffixes):
            continue
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def cheap_signature(item: dict[str, Any]) -> dict[str, Any]:
    text = item_text(item)
    material = match_pattern(text, MATERIAL_PATTERNS, "other")
    subject = match_pattern(text, SUBJECT_PATTERNS, "unknown")
    normalized = normalize_key(text)
    tokens = [token for token in normalized.split() if len(token) > 1][:16]
    signature = " ".join(tokens[:10])
    return {
        "materialType": material,
        "subjectType": subject,
        "signature": signature,
        "duplicateGroupKey": f"{material}:{subject}:{' '.join(tokens[:5])}",
    }


def representative_score(item: dict[str, Any]) -> float:
    heat = float(item.get("heatValue") or item.get("heat") or 0)
    comments = safe_int(item.get("commentCount") or item.get("comments"))
    likes = safe_int(item.get("diggCount") or item.get("likeCount") or item.get("likes"))
    plays = safe_int(item.get("playCount") or item.get("plays"))
    human_bonus = 10 if cheap_signature(item)["subjectType"] == "real_person" else 0
    return round(heat + min(comments, 500) * 0.02 + min(likes, 10000) * 0.0005 + min(plays, 1000000) * 0.000001 + human_bonus, 4)


def parse_feishu_date(value: Any) -> date | None:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000).date()
    text = clean_text(value)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or value.get("link") or "").strip()
    if isinstance(value, list):
        return " ".join(field_text(item) for item in value if item is not None).strip()
    return str(value).strip()


def url_text(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        return text if text.startswith(("http://", "https://")) else ""
    if isinstance(value, dict):
        for key in ("link", "url", "href", "value"):
            found = url_text(value.get(key))
            if found:
                return found
        for child in value.values():
            found = url_text(child)
            if found:
                return found
        return ""
    if isinstance(value, list):
        for item in value:
            found = url_text(item)
            if found:
                return found
    text = field_text(value)
    return text if text.startswith(("http://", "https://")) else ""


def fetch_history_items(days: int, today: date | None = None) -> list[dict[str, Any]]:
    env = load_env()
    app_id = os.environ.get("FEISHU_APP_ID") or env.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET") or env.get("FEISHU_APP_SECRET", "")
    cfg = resolve_bitable_config()
    if not app_id or not app_secret or not cfg.get("app_token") or not cfg.get("table_id"):
        return []
    from feishu_push import WRITE_FIELD_NAMES, get_tenant_access_token
    from feedback_field_utils import material_feedback

    token = get_tenant_access_token(app_id, app_secret)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{cfg['app_token']}/tables/{cfg['table_id']}/records/search"
    cutoff = (today or date.today()) - timedelta(days=days)
    records: list[dict[str, Any]] = []
    page_token = ""
    while True:
        body: dict[str, Any] = {"page_size": 500, "automatic_fields": True}
        if page_token:
            body["page_token"] = page_token
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to fetch Feishu history for visual dedupe: {data}")
        payload = data.get("data", {})
        records.extend(payload.get("items", []))
        if not payload.get("has_more"):
            break
        page_token = payload.get("page_token") or ""
        if not page_token:
            break
    history: list[dict[str, Any]] = []
    for record in records:
        fields = record.get("fields") or {}
        push_date = parse_feishu_date(fields.get(WRITE_FIELD_NAMES["push_date"]))
        if push_date and push_date < cutoff:
            continue
        feedback = material_feedback(fields)
        item = {
            "historyRecordId": record.get("record_id", ""),
            "pushDate": push_date.isoformat() if push_date else "",
            "platform": field_text(fields.get(WRITE_FIELD_NAMES["platform"])),
            "hotspotIntro": field_text(fields.get(WRITE_FIELD_NAMES["intro"])),
            "hotspotUrl": url_text(fields.get(WRITE_FIELD_NAMES["url"])),
            "playCount": field_text(fields.get(WRITE_FIELD_NAMES["plays"])),
            "diggCount": field_text(fields.get(WRITE_FIELD_NAMES["likes"])),
            "commentCount": field_text(fields.get(WRITE_FIELD_NAMES["comments"])),
            "heatValue": field_text(fields.get(WRITE_FIELD_NAMES["heat"])),
            **feedback,
        }
        item["visualDedupe"] = {**cheap_signature(item), "isDuplicate": False, "duplicateReason": "history"}
        history.append(item)
    return history


def allowed_model(model: str) -> bool:
    lowered = model.lower()
    return bool(model.strip()) and not any(marker in lowered for marker in BLOCKED_MODEL_MARKERS)


def openrouter_models() -> list[str]:
    try:
        response = requests.get("https://openrouter.ai/api/v1/models", timeout=20)
        response.raise_for_status()
        models = []
        for model in response.json().get("data", []):
            model_id = str(model.get("id") or "")
            modalities = set(((model.get("architecture") or {}).get("input_modalities") or []))
            if allowed_model(model_id) and ("image" in modalities or "video" in modalities):
                models.append(model_id)
        return models
    except Exception:
        return []


def resolve_model() -> str:
    env = load_env()
    configured = os.environ.get("VISUAL_DEDUPE_MODEL") or env.get("VISUAL_DEDUPE_MODEL") or DEFAULT_MODEL
    candidates = [configured, *MODEL_FALLBACKS]
    available = set(openrouter_models())
    for model in candidates:
        if allowed_model(model) and (not available or model in available):
            return model
    return DEFAULT_MODEL


def multimodal_refine(candidate: dict[str, Any], duplicates: list[dict[str, Any]], model: str) -> dict[str, Any] | None:
    env = load_env()
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    if not api_key or not duplicates or not allowed_model(model):
        return None
    candidate_sig = cheap_signature(candidate)
    compact_duplicates = [
        {
            "materialType": (item.get("visualDedupe") or cheap_signature(item)).get("materialType"),
            "subjectType": (item.get("visualDedupe") or cheap_signature(item)).get("subjectType"),
            "intro": clean_text(item_text(item), max_len=420),
            "material_acceptance": item.get("material_acceptance", ""),
            "material_reason": item.get("material_reason", ""),
            "score": representative_score(item),
        }
        for item in duplicates[:6]
    ]
    prompt = (
        "You are a multimodal duplicate detector for social AI creative materials. "
        "Decide whether the candidate is substantially the same visual material pattern as the history/candidate examples. "
        "Treat repeated retro poster, rainy couple, outfit/beauty, growth comparison, sticker/mini doll, baseball broadcast, "
        "and AI dance+BGM/IP formats as duplicates unless there is a clearly new visual mechanism, subject, or use case. "
        "Return strict JSON with keys: isDuplicate, materialType, subjectType, signature, duplicateGroupKey, duplicateReason."
    )
    content: list[dict[str, Any]] = [
        {"type": "text", "text": f"{prompt}\nCandidate cheap signature: {json.dumps(candidate_sig, ensure_ascii=False)}\nCandidate text: {clean_text(item_text(candidate), max_len=900)}\nPotential duplicates: {json.dumps(compact_duplicates, ensure_ascii=False)}"}
    ]
    for url in image_input_urls(candidate, limit=2):
        content.append({"type": "image_url", "image_url": {"url": url}})
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
            "max_tokens": 600,
        },
        timeout=45,
    )
    response.raise_for_status()
    text = response.json()["choices"][0]["message"].get("content") or "{}"
    return json.loads(text)


def likely_duplicates(candidate: dict[str, Any], pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sig = cheap_signature(candidate)
    normalized = set(normalize_key(item_text(candidate)).split())
    candidate_url = str(candidate.get("hotspotUrl") or candidate.get("url") or "").strip()
    matches: list[dict[str, Any]] = []
    for item in pool:
        item_url = str(item.get("hotspotUrl") or item.get("url") or "").strip()
        if candidate_url and item_url and candidate_url == item_url:
            continue
        other = item.get("visualDedupe") or cheap_signature(item)
        if other.get("materialType") == "other" or sig.get("materialType") == "other":
            continue
        if other.get("materialType") != sig.get("materialType"):
            continue
        if other.get("subjectType") != sig.get("subjectType") and "real_person" not in {other.get("subjectType"), sig.get("subjectType")}:
            continue
        other_tokens = set(normalize_key(item_text(item)).split())
        overlap = len(normalized & other_tokens) / max(1, min(len(normalized), len(other_tokens)))
        if overlap >= 0.18 or other.get("materialType") in {
            "retro_movie_poster",
            "ai_dance_bgm_ip",
            "baseball_broadcast",
            "fashion_illustration",
        }:
            matches.append(item)
    return matches


def apply_visual_dedupe(items: list[dict[str, Any]], platform: str, top_n: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    env = load_env()
    if str(os.environ.get("VISUAL_DEDUPE_DISABLE") or env.get("VISUAL_DEDUPE_DISABLE") or "").lower() in {"1", "true", "yes"}:
        return items[:top_n], []
    history_days = env_int("VISUAL_DEDUPE_HISTORY_DAYS", 15, env)
    model = resolve_model()
    try:
        history = fetch_history_items(history_days)
    except Exception as exc:
        print(f"  - Visual dedupe history skipped: {exc}", flush=True)
        history = []
    kept: list[dict[str, Any]] = []
    debug: list[dict[str, Any]] = []
    comparison_pool = list(history)
    for item in items:
        updated = dict(item)
        sig = cheap_signature(updated)
        duplicates = likely_duplicates(updated, comparison_pool + kept)
        refined: dict[str, Any] | None = None
        if duplicates:
            try:
                refined = multimodal_refine(updated, duplicates, model)
            except Exception as exc:
                print(f"  - Visual dedupe model skipped for {platform} item: {exc}", flush=True)
        visual = {
            **sig,
            **(refined or {}),
            "isDuplicate": bool((refined or {}).get("isDuplicate")) if refined else bool(duplicates),
            "duplicateReason": (refined or {}).get("duplicateReason") if refined else ("matched recent visual material pattern" if duplicates else ""),
            "representativeScore": representative_score(updated),
            "model": model if duplicates else "",
            "historyWindowDays": history_days,
        }
        updated["visualDedupe"] = visual
        if visual["isDuplicate"]:
            duplicate_scores = [representative_score(dup) for dup in duplicates]
            if duplicate_scores and representative_score(updated) > max(duplicate_scores) + 8 and len(kept) < top_n:
                updated["visualDedupe"]["isDuplicate"] = False
                updated["visualDedupe"]["duplicateReason"] = "kept as stronger representative"
                kept.append(updated)
            else:
                debug.append(updated)
                continue
        else:
            kept.append(updated)
        if len(kept) >= top_n:
            break
    if debug:
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            (DEBUG_DIR / f"{platform}_{timestamp}_deduped.json").write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"  - Visual dedupe debug write skipped: {exc}", flush=True)
    print(f"  - Visual dedupe kept {len(kept)}/{len(items)} {platform} items; removed {len(debug)}", flush=True)
    return kept, debug
