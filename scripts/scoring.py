from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from env_utils import env_float, load_env


DEFAULT_SCORING_PARAMETERS = {
    "play_weight": 0.01,
    "like_weight": 1.0,
    "comment_weight": 5.0,
    "gravity": 1.8,
    "high_score_k": 500.0,
}

SCORING_ENV_KEYS = {
    "tiktok": {
        "play_weight": "SCORING_PLAY_WEIGHT",
        "like_weight": "SCORING_LIKE_WEIGHT",
        "comment_weight": "SCORING_COMMENT_WEIGHT",
        "gravity": "SCORING_GRAVITY",
        "high_score_k": "SCORING_HIGH_SCORE_K",
    },
    "x": {
        "play_weight": "X_SCORING_PLAY_WEIGHT",
        "like_weight": "X_SCORING_LIKE_WEIGHT",
        "comment_weight": "X_SCORING_COMMENT_WEIGHT",
        "gravity": "X_SCORING_GRAVITY",
        "high_score_k": "X_SCORING_HIGH_SCORE_K",
    },
}


def normalize_platform(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"x", "twitter"}:
        return "x"
    return "tiktok"


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_video_datetime(video: dict[str, Any]) -> datetime | None:
    create_time = video.get("createTime")
    create_time_iso = video.get("createTimeISO") or video.get("created_at")
    if isinstance(create_time, (int, float)):
        timestamp = float(create_time)
        if timestamp > 1e12:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp)
    if isinstance(create_time, str) and create_time.strip().isdigit():
        timestamp = float(create_time.strip())
        if timestamp > 1e12:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp)
    raw = create_time_iso if isinstance(create_time_iso, str) and create_time_iso else create_time
    if isinstance(raw, str) and raw.strip():
        try:
            return datetime.fromisoformat(raw.strip().replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def published_days(item: dict[str, Any], now: datetime | None = None) -> int:
    dt = parse_video_datetime(item)
    if not dt:
        return safe_int(item.get("publishDays"), 0)
    now = now or datetime.now()
    return max(0, (now.date() - dt.date()).days)


def get_scoring_parameters(
    rules: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    platform: str = "tiktok",
) -> dict[str, float]:
    loaded_env = env if env is not None else load_env()
    platform = normalize_platform(platform)
    env_keys = SCORING_ENV_KEYS[platform]
    params = {
        key: env_float(env_key, DEFAULT_SCORING_PARAMETERS[key], loaded_env)
        for key, env_key in env_keys.items()
    }
    section = "x_scoring" if platform == "x" else "scoring"
    active = ((rules or {}).get(section) or {}).get("active_parameters") or {}
    for key in params:
        try:
            if key in active:
                params[key] = float(active[key])
        except (TypeError, ValueError):
            continue
    params["gravity"] = max(0.0, params["gravity"])
    params["high_score_k"] = max(1.0, params["high_score_k"])
    return params


def heat_score(item: dict[str, Any], rules: dict[str, Any] | None = None, now: datetime | None = None) -> float:
    platform = normalize_platform(item.get("hotspotPlatform") or item.get("sourcePlatform") or item.get("platform"))
    params = get_scoring_parameters(rules, platform=platform)
    plays = safe_int(item.get("playCount") or item.get("views"))
    likes = safe_int(item.get("diggCount") or item.get("likeCount") or item.get("likes"))
    comments = safe_int(item.get("commentCount") or item.get("comments"))
    days = published_days(item, now=now)
    numerator = plays * params["play_weight"] + likes * params["like_weight"] + comments * params["comment_weight"]
    denominator = math.pow(days + 1, params["gravity"]) if params["gravity"] else 1
    ratio = numerator / denominator if denominator else 0.0
    if ratio <= 0:
        return 0.0
    raw_score = 10 * math.log(ratio)
    if raw_score <= 100:
        final_score = raw_score
    else:
        final_score = 100 + 50 * (raw_score - 100) / (raw_score - 100 + params["high_score_k"])
    return round(final_score, 4)


def get_comment_count(item: dict[str, Any]) -> int:
    return safe_int(
        item.get("commentCount")
        or item.get("comment_count")
        or item.get("comments")
        or item.get("stats", {}).get("commentCount")
        or item.get("statsV2", {}).get("commentCount")
    )


def get_video_url(item: dict[str, Any]) -> str:
    video_meta = item.get("videoMeta") or {}
    url = item.get("hotspotUrl") or item.get("webVideoUrl") or video_meta.get("webVideoUrl") or item.get("url") or ""
    if url:
        return str(url)
    video_id = str(item.get("id") or "").strip()
    author = (item.get("authorMeta") or {}).get("nickName") or "user"
    return f"https://www.tiktok.com/@{author}/video/{video_id}" if video_id else ""


def normalize_hotspot(item: dict[str, Any], rules: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = dict(item)
    normalized["sourcePlatform"] = "tiktok"
    normalized["hotspotPlatform"] = "tiktok"
    normalized["commentCount"] = get_comment_count(item)
    normalized["hotspotUrl"] = get_video_url(item)
    normalized["publishDays"] = published_days(item)
    normalized["heatValue"] = heat_score(normalized, rules=rules)
    normalized["upsertKey"] = normalized["hotspotUrl"] or f"tiktok:{normalized.get('id', '')}"
    return normalized
