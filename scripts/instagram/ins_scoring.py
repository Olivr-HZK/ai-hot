from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def text_from_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in [
            "text",
            "caption",
            "title",
            "description",
            "summary",
            "accessibility_caption",
            "alt",
            "name",
            "full_name",
            "username",
            "value",
            "content",
        ]:
            if key in value:
                text = text_from_value(value.get(key))
                if text:
                    return text
        return ""
    if isinstance(value, list):
        parts = [text_from_value(item) for item in value]
        return " ".join(part for part in parts if part)
    return str(value)


def clean_text(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", text_from_value(value)).strip()
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def first_value(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value: Any = item
        for part in key.split("."):
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, list) and part.isdigit():
                index = int(part)
                value = value[index] if 0 <= index < len(value) else None
            else:
                value = None
                break
        if value not in (None, ""):
            return value
    return None


def first_text_value(item: dict[str, Any], keys: list[str], max_len: int | None = None) -> str:
    for key in keys:
        value = first_value(item, [key])
        text = clean_text(value, max_len=max_len)
        if text:
            return text
    return ""


def parse_ins_datetime(item: dict[str, Any]) -> datetime | None:
    raw = first_value(
        item,
        [
            "timestamp",
            "taken_at",
            "takenAt",
            "taken_at_timestamp",
            "date_posted",
            "created_at",
            "createTimeISO",
            "createTime",
            "time",
        ],
    )
    if isinstance(raw, (int, float)):
        timestamp = float(raw)
        if timestamp > 1e12:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp)
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        if text.isdigit():
            timestamp = float(text)
            if timestamp > 1e12:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp)
        for candidate in [text, text.replace("Z", "+00:00")]:
            try:
                return datetime.fromisoformat(candidate).replace(tzinfo=None)
            except ValueError:
                continue
    return None


def extract_hashtags(text: str) -> list[str]:
    return [match.group(1).lower() for match in re.finditer(r"#([A-Za-z0-9_\u4e00-\u9fff]+)", text or "")]


def normalize_hashtags(item: dict[str, Any], caption: str) -> list[str]:
    tags: list[str] = []
    raw = first_value(item, ["hashtags", "tags", "post_hashtags"])
    if isinstance(raw, list):
        for tag in raw:
            if isinstance(tag, dict):
                value = clean_text(tag.get("name") or tag.get("title") or tag.get("tag"))
            else:
                value = clean_text(tag)
            value = value.lstrip("#").lower()
            if value and value not in tags:
                tags.append(value)
    for tag in extract_hashtags(caption):
        if tag not in tags:
            tags.append(tag)
    return tags


VIDEO_TYPE_MARKERS = {"reel", "video", "igtv", "clip", "graphvideo"}
IMAGE_TYPE_MARKERS = {"image", "photo", "picture", "graphimage"}
CAROUSEL_TYPE_MARKERS = {"carousel", "album", "sidecar", "graphsidecar"}
VIDEO_URL_KEYS = {"videoUrl", "video_url", "video_versions", "video_versions.0.url"}
IMAGE_URL_KEYS = {
    "displayUrl",
    "display_url",
    "imageUrl",
    "image_url",
    "thumbnail",
    "thumbnail_src",
    "thumbnailUrl",
    "display_uri",
}
MEDIA_CONTAINER_KEYS = [
    "images",
    "image_urls",
    "mediaUrls",
    "media_urls",
    "childPosts",
    "children",
    "post_content",
    "carousel_media",
    "display_resources",
    "image_versions2",
    "candidates",
    "thumbnails",
]


def _looks_like_video_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return any(marker in text for marker in [".mp4", ".mov", ".m3u8", "/video/", "video_url", "video_versions"])


def _looks_like_image_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text.startswith("http") or _looks_like_video_url(text):
        return False
    return any(marker in text for marker in [".jpg", ".jpeg", ".png", ".webp", "scontent", "cdninstagram", "fbcdn"])


def _media_type_text(item: dict[str, Any]) -> tuple[Any, str, int]:
    raw = first_value(item, ["type", "content_type", "contentType", "media_type", "mediaType", "product_type", "__typename"])
    return raw, clean_text(raw).lower(), safe_int(raw, -1)


def has_video_signal(item: Any, depth: int = 0) -> bool:
    if depth > 4:
        return False
    if isinstance(item, dict):
        raw, text, numeric = _media_type_text(item)
        if numeric == 2 or item.get("is_video") is True or item.get("isVideo") is True:
            return True
        if any(marker in text for marker in VIDEO_TYPE_MARKERS):
            return True
        for key in VIDEO_URL_KEYS:
            value = first_value(item, [key])
            if value not in (None, ""):
                return True
        for key, value in item.items():
            if key in {"videoUrl", "video_url", "video_versions", "clips_metadata"} and value not in (None, "", []):
                return True
            if key in {"url", "src"} and _looks_like_video_url(value):
                return True
        for key in MEDIA_CONTAINER_KEYS:
            value = item.get(key)
            if isinstance(value, list) and any(has_video_signal(entry, depth + 1) for entry in value):
                return True
            if isinstance(value, dict) and has_video_signal(value, depth + 1):
                return True
        return False
    if isinstance(item, list):
        return any(has_video_signal(entry, depth + 1) for entry in item)
    return _looks_like_video_url(item)


def has_image_signal(item: Any, depth: int = 0) -> bool:
    if depth > 4:
        return False
    if isinstance(item, dict):
        raw, text, numeric = _media_type_text(item)
        if numeric == 1 or any(marker in text for marker in IMAGE_TYPE_MARKERS):
            return True
        for key in IMAGE_URL_KEYS:
            value = first_value(item, [key])
            if value not in (None, ""):
                return True
        for key in MEDIA_CONTAINER_KEYS:
            value = item.get(key)
            if isinstance(value, list) and any(has_image_signal(entry, depth + 1) for entry in value):
                return True
            if isinstance(value, dict) and has_image_signal(value, depth + 1):
                return True
        return False
    if isinstance(item, list):
        return any(has_image_signal(entry, depth + 1) for entry in item)
    text = str(item or "").strip().lower()
    if not text.startswith("http") or _looks_like_video_url(text):
        return False
    return any(marker in text for marker in [".jpg", ".jpeg", ".png", ".webp", "scontent", "cdninstagram"])


def detect_media_type(item: dict[str, Any]) -> str:
    raw, text, numeric = _media_type_text(item)
    if numeric == 1:
        return "image"
    if numeric == 2:
        return "reel"
    if numeric == 8:
        return "carousel"
    if item.get("is_video") is True or item.get("isVideo") is True:
        return "reel"
    if "graphsidecar" in text:
        return "carousel"
    if "graphimage" in text:
        return "image"
    if "graphvideo" in text:
        return "reel"
    if any(marker in text for marker in ["carousel", "album", "sidecar"]):
        return "carousel"
    if any(marker in text for marker in ["reel", "video", "igtv", "clip"]):
        return "reel"
    if any(marker in text for marker in ["image", "photo", "picture"]):
        return "image"
    if has_video_signal(item):
        return "reel"
    if has_image_signal(item):
        return "image"
    return "unknown"


def _append_url(urls: list[str], value: Any) -> None:
    if isinstance(value, dict):
        value = value.get("displayUrl") or value.get("display_url") or value.get("image_url") or value.get("url") or value.get("src")
    text = str(value or "").strip()
    if _looks_like_image_url(text) and text not in urls:
        urls.append(text)


def _collect_image_urls(value: Any, urls: list[str], limit: int, depth: int = 0) -> None:
    if len(urls) >= limit or depth > 6:
        return
    if isinstance(value, dict):
        for key in IMAGE_URL_KEYS:
            _append_url(urls, value.get(key))
            if len(urls) >= limit:
                return
        for key in ["url", "src"]:
            _append_url(urls, value.get(key))
            if len(urls) >= limit:
                return
        for key in MEDIA_CONTAINER_KEYS:
            nested = value.get(key)
            if nested not in (None, "", []):
                _collect_image_urls(nested, urls, limit, depth + 1)
                if len(urls) >= limit:
                    return
        return
    if isinstance(value, list):
        for entry in value:
            _collect_image_urls(entry, urls, limit, depth + 1)
            if len(urls) >= limit:
                return
        return
    _append_url(urls, value)


def media_urls(item: dict[str, Any], limit: int = 6) -> list[str]:
    urls: list[str] = []
    for key in [
        "displayUrl",
        "display_url",
        "imageUrl",
        "image_url",
        "thumbnail",
        "thumbnail_src",
        "thumbnailUrl",
    ]:
        _append_url(urls, item.get(key))
    for key in ["images", "image_urls", "mediaUrls", "media_urls", "childPosts", "children", "post_content", "carousel_media", "display_resources"]:
        value = item.get(key)
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    for nested_key in ["url", "src", "displayUrl", "display_url", "image_url", "thumbnail"]:
                        _append_url(urls, entry.get(nested_key))
                else:
                    _append_url(urls, entry)
                if len(urls) >= limit:
                    return urls
        elif isinstance(value, dict):
            _collect_image_urls(value, urls, limit)
            if len(urls) >= limit:
                return urls
    _collect_image_urls(item.get("raw_source"), urls, limit)
    if len(urls) >= limit:
        return urls[:limit]
    _collect_image_urls(item, urls, limit)
    return urls[:limit]


def normalize_author(item: dict[str, Any]) -> dict[str, Any]:
    username = clean_text(
        first_value(item, ["ownerUsername", "owner.username", "user.username", "username", "author.username", "_insRapidapiUsername"])
    )
    full_name = clean_text(
        first_value(item, ["ownerFullName", "owner.fullName", "user.full_name", "fullName", "author.name"])
    )
    return {"nickName": username, "name": full_name or username, "uniqueId": username}


def canonical_url(item: dict[str, Any], username: str = "") -> str:
    url = clean_text(first_value(item, ["url", "permalink", "postUrl", "link"]))
    if url.startswith("http"):
        return url
    shortcode = clean_text(first_value(item, ["shortCode", "shortcode", "code"]))
    if shortcode:
        return f"https://www.instagram.com/p/{shortcode}/"
    post_id = clean_text(first_value(item, ["id", "pk", "instagram_id"]))
    return f"ins:{username}:{post_id}" if post_id else ""


def base_heat_score(item: dict[str, Any], rules: dict[str, Any]) -> float:
    scoring = rules.get("scoring", {})
    likes = safe_int(item.get("diggCount") or item.get("likeCount") or item.get("likes"))
    comments = safe_int(item.get("commentCount") or item.get("comments"))
    numerator = (
        likes * safe_float(scoring.get("like_weight"), 1.0)
        + comments * safe_float(scoring.get("comment_weight"), 8.0)
    )
    dt = parse_ins_datetime(item)
    hours_old = max(0.0, (datetime.now() - dt).total_seconds() / 3600.0) if dt else 48.0
    recency = math.pow(hours_old + 1.0, safe_float(scoring.get("recency_gravity"), 0.8))
    raw = math.log1p(max(0.0, numerator)) * 10.0 / max(recency, 1.0)
    media_type = clean_text(item.get("mediaType")).lower() or detect_media_type(item)
    weight_key = f"{media_type}_weight"
    raw *= safe_float(scoring.get(weight_key), safe_float(scoring.get("unknown_weight"), 0.9))
    return round(raw, 4)


def normalize_ins_post(item: dict[str, Any], rules: dict[str, Any] | None = None) -> dict[str, Any]:
    rules = rules or {}
    caption = first_text_value(
        item,
        [
            "caption.text",
            "edge_media_to_caption.edges.0.node.text",
            "caption",
            "text",
            "title",
            "description",
        ],
    )
    author = normalize_author(item)
    normalized = dict(item)
    dt = parse_ins_datetime(item)
    if dt:
        normalized["createTime"] = int(dt.timestamp())
        normalized["createTimeISO"] = dt.isoformat()
    normalized["sourcePlatform"] = "ins"
    normalized["hotspotPlatform"] = "ins"
    normalized["platform"] = "ins"
    normalized["authorMeta"] = author
    normalized["title"] = caption
    normalized["text"] = caption
    normalized["desc"] = caption
    normalized["summary"] = first_text_value(item, ["summary", "accessibility_caption", "alt"], max_len=600)
    normalized["hashtags"] = normalize_hashtags(item, caption)
    normalized["mediaType"] = detect_media_type(item)
    normalized["mediaUrls"] = media_urls(item)
    normalized["playCount"] = 0
    normalized["diggCount"] = safe_int(first_value(item, ["likesCount", "like_count", "likes", "likeCount", "edge_media_preview_like.count", "edge_liked_by.count"]))
    normalized["likeCount"] = normalized["diggCount"]
    normalized["commentCount"] = safe_int(first_value(item, ["commentsCount", "comment_count", "comments", "commentCount", "edge_media_to_comment.count", "edge_media_to_parent_comment.count"]))
    normalized["hotspotUrl"] = canonical_url(item, author.get("uniqueId", ""))
    normalized["webVideoUrl"] = normalized["hotspotUrl"]
    normalized["upsertKey"] = normalized["hotspotUrl"] or f"ins:{author.get('uniqueId', '')}:{clean_text(item.get('id'))}"
    normalized["raw_source"] = item
    normalized["heatValue"] = base_heat_score(normalized, rules)
    return normalized


def hours_old(item: dict[str, Any]) -> float | None:
    dt = parse_ins_datetime(item)
    if not dt:
        return None
    return (datetime.now() - dt).total_seconds() / 3600.0


def within_lookback(item: dict[str, Any], lookback_hours: int) -> bool:
    age = hours_old(item)
    return age is not None and 0 <= age <= lookback_hours


def passes_quality(item: dict[str, Any], rules: dict[str, Any]) -> bool:
    quality = rules.get("quality", {})
    likes = safe_int(item.get("diggCount") or item.get("likeCount"))
    comments = safe_int(item.get("commentCount"))
    if likes < safe_int(quality.get("min_like_count"), 0):
        return False
    if comments < safe_int(quality.get("min_comment_count"), 0):
        return False
    return True


def passes_media_policy(item: dict[str, Any], rules: dict[str, Any]) -> bool:
    content_mode = rules.get("content_mode", {}) if isinstance(rules.get("content_mode"), dict) else {}
    if not content_mode.get("image_materials_only", True):
        return True
    if has_video_signal(item):
        return False
    media_type = clean_text(item.get("mediaType")).lower() or detect_media_type(item)
    if media_type == "image":
        return True
    if media_type == "carousel" and has_image_signal(item):
        return True
    if media_type == "unknown" and has_image_signal(item) and media_urls(item, limit=1):
        return True
    return False


def ranking_score(item: dict[str, Any], rules: dict[str, Any]) -> float:
    score = safe_float(item.get("heatValue"), 0.0)
    fit = item.get("insProductFit") if isinstance(item.get("insProductFit"), dict) else {}
    if fit.get("isRelevant"):
        score *= safe_float(rules.get("scoring", {}).get("product_fit_boost"), 1.0)
    return round(score, 4)
