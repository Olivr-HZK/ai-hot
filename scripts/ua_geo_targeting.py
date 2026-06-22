from __future__ import annotations

import re
from typing import Any

from feedback_rules import ranking_score, video_haystack
from scoring import safe_int


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "daily_min": 1,
    "daily_max": 3,
    "review_pool_size": 5,
    "candidate_multiplier": 3,
    "min_play_count_multiplier": 0.5,
    "min_comment_count_multiplier": 0.5,
    "score_boost": 1.12,
    "geo_keywords": [
        "united states",
        "usa",
        "u.s.",
        "america",
        "american",
        "canada",
        "canadian",
        "australia",
        "australian",
        "new zealand",
        "kiwi",
        "europe",
        "european",
        "uk",
        "britain",
        "british",
        "england",
        "france",
        "french",
        "germany",
        "german",
        "italy",
        "italian",
        "spain",
        "spanish",
        "netherlands",
        "dutch",
        "sweden",
        "swedish",
        "norway",
        "norwegian",
        "denmark",
        "danish",
        "finland",
        "finnish",
        "ireland",
        "irish",
        "scotland",
        "london",
        "paris",
        "berlin",
        "toronto",
        "vancouver",
        "sydney",
        "melbourne",
        "auckland",
    ],
    "geo_country_codes": [
        "US",
        "CA",
        "AU",
        "NZ",
        "GB",
        "UK",
        "IE",
        "FR",
        "DE",
        "IT",
        "ES",
        "NL",
        "SE",
        "NO",
        "DK",
        "FI",
        "AT",
        "BE",
        "CH",
        "PT",
        "PL",
        "CZ",
        "GR",
    ],
    "material_keywords": [
        "portrait",
        "photo",
        "photoshoot",
        "photo shoot",
        "picture",
        "selfie",
        "style",
        "fashion",
        "outfit",
        "lookbook",
        "makeup",
        "hairstyle",
        "wedding",
        "graduation",
        "holiday",
        "festival",
        "family",
        "couple",
        "travel",
        "creative",
        "cinematic",
        "template",
        "effect",
        "generator",
        "transformation",
        "photo to video",
        "\u4eba\u50cf",
        "\u5199\u771f",
        "\u65f6\u5c1a",
        "\u7a7f\u642d",
        "\u60c5\u4fa3",
        "\u5bb6\u5ead",
        "\u8282\u65e5",
        "\u521b\u610f",
    ],
    "exclude_keywords": [
        "news",
        "stock",
        "crypto",
        "web3",
        "election",
        "war",
        "policy",
        "regulator",
        "hardware",
        "benchmark",
        "api",
        "sdk",
        "course",
        "tutorial paywall",
        "fruit dance",
        "animal dance",
        "cartoon",
        "anime",
        "meme coin",
        "robot",
        "hardware",
    ],
}


def config(rules: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    configured = rules.get("ua_geo_targeting", {})
    if isinstance(configured, dict):
        for key, value in configured.items():
            if value is not None:
                merged[key] = value
    return merged


def keyword_hits(haystack: str, keywords: list[str]) -> list[str]:
    hits: list[str] = []
    for keyword in keywords:
        raw = str(keyword or "").strip().lower()
        if not raw:
            continue
        if re.fullmatch(r"[a-z0-9][a-z0-9.\- ]*[a-z0-9.]", raw):
            pattern = rf"(?<![a-z0-9]){re.escape(raw)}(?![a-z0-9])"
            if re.search(pattern, haystack):
                hits.append(raw)
        elif raw in haystack:
            hits.append(raw)
    return hits


def ua_geo_details(item: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    cfg = config(rules)
    haystack = video_haystack(item, include_summary=True)
    geo_hits = keyword_hits(haystack, list(cfg.get("geo_keywords", [])))
    country_code = str(item.get("locationCreated") or (item.get("raw_source") or {}).get("locationCreated") or "").strip().upper()
    country_codes = {str(code or "").strip().upper() for code in cfg.get("geo_country_codes", [])}
    if country_code and country_code in country_codes:
        geo_hits.append(country_code)
    material_hits = keyword_hits(haystack, list(cfg.get("material_keywords", [])))
    exclude_hits = keyword_hits(haystack, list(cfg.get("exclude_keywords", [])))
    is_target = bool(cfg.get("enabled", True) and geo_hits and material_hits and not exclude_hits)
    return {
        "isTarget": is_target,
        "pushObject": "UA",
        "geoHits": geo_hits[:8],
        "materialHits": material_hits[:8],
        "excludeHits": exclude_hits[:8],
        "reason": "target geo material for UA" if is_target else "not a target geo UA material",
    }


def passes_relaxed_quality(item: dict[str, Any], rules: dict[str, Any]) -> bool:
    cfg = config(rules)
    thresholds = rules.get("quality_thresholds", {})
    min_play = int(float(thresholds.get("min_play_count", 0) or 0) * float(cfg.get("min_play_count_multiplier", 0.5) or 0.5))
    min_comments = int(float(thresholds.get("min_comment_count", 0) or 0) * float(cfg.get("min_comment_count_multiplier", 0.5) or 0.5))
    if safe_int(item.get("playCount") or item.get("view_count") or item.get("views")) < min_play:
        return False
    if safe_int(item.get("commentCount") or item.get("reply_count") or item.get("comments")) < min_comments:
        return False
    return True


def mark_ua_geo_candidate(item: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    updated = dict(item)
    details = ua_geo_details(updated, rules)
    updated["uaGeoTargeting"] = details
    updated["pushObject"] = "UA"
    try:
        boost = float(config(rules).get("score_boost", 1.0) or 1.0)
        updated["heatValue"] = round(float(updated.get("heatValue") or ranking_score(updated, rules)) * boost, 4)
    except (TypeError, ValueError):
        pass
    return updated


def select_ua_geo_candidates(items: list[dict[str, Any]], rules: dict[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
    cfg = config(rules)
    if not cfg.get("enabled", True):
        return []
    resolved_limit = int(limit if limit is not None else cfg.get("daily_max", 3) or 3)
    if resolved_limit <= 0:
        return []
    candidates: list[dict[str, Any]] = []
    for item in items:
        details = ua_geo_details(item, rules)
        if not details.get("isTarget"):
            continue
        if not passes_relaxed_quality(item, rules):
            continue
        candidates.append(mark_ua_geo_candidate({**item, "uaGeoTargeting": details}, rules))
    candidates.sort(key=lambda item: float(item.get("heatValue") or ranking_score(item, rules)), reverse=True)
    selected = candidates[:resolved_limit]
    for index, item in enumerate(selected, 1):
        details = dict(item.get("uaGeoTargeting") or {})
        details["reviewPoolRank"] = index
        details["reviewPoolSize"] = resolved_limit
        item["uaGeoTargeting"] = details
    return selected


def merge_unique(primary: list[dict[str, Any]], extras: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*extras, *primary]:
        key = str(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url") or item.get("upsertKey") or item.get("id") or "").strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        merged.append(item)
    return merged


def is_ua_geo_candidate(item: dict[str, Any]) -> bool:
    details = item.get("uaGeoTargeting")
    return isinstance(details, dict) and bool(details.get("isTarget"))
