from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
BASE_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from env_utils import env_bool, load_env
from feedback_rules import is_excluded_by_rules, load_feedback_rules, ranking_score, video_haystack
from phase1_scrape_x import normalize_x_hotspot
from product_targeting import product_fit_details
from scoring import normalize_hotspot, safe_int
from ua_geo_targeting import passes_relaxed_quality


OUTPUT_DIR = BASE_DIR / "skill_runs" / "us_t1"
RUNS_DIR = OUTPUT_DIR / "runs"
CANDIDATES_PATH = OUTPUT_DIR / "latest_candidates.json"
FILTERED_PATH = OUTPUT_DIR / "latest_filtered.json"
REVIEW_PROGRESS_PATH = OUTPUT_DIR / "latest_review_progress.json"
TIKTOK_RAW = BASE_DIR / "skill_runs" / "scrape_checkpoints" / "tiktok" / "latest_raw.json"
X_RAW = BASE_DIR / "skill_runs" / "scrape_checkpoints" / "x" / "latest_raw.json"

FOCUS_PRODUCTS = {"evoke", "toki", "kavi", "avatar_jigsaw"}
US_KEYWORDS = [
    "united states",
    "usa",
    "u.s.",
    "america",
    "american",
    "new york",
    "los angeles",
    "california",
    "texas",
    "florida",
    "chicago",
    "miami",
    "seattle",
    "san francisco",
    "washington dc",
]

US_REVIEW_MANUAL = """
You are auditing social media posts for a US English paid-growth material pipeline.

Only allow posts that are safe, English, relevant to the United States audience, and useful as ad creative,
template-library material, or product inspiration for one of these products:
- Evoke: photo enhancement/restoration/portrait/style/before-after value.
- Toki: photo-to-video, image-to-video, face animation, couple/family/pet motion, short video templates.
- Kavi: one-photo/selfie-to-video, viral effects, stylized animation, creator persona, custom 3D figure.
- Avatar: Facebook Instant Game avatar generation, clay/profile avatar, jigsaw puzzle, sharing/invite loops.

Reject politics, news-only content, celebrity gossip/leaks, pure IP screenshots, adult/suggestive bait,
crypto/Web3, hardware/news/model launches, generic memes, low-quality content, and anything without a clear
US English advertising or product-template reuse path.
"""


def clean_text(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independent US English TikTok/X content audit and optional Feishu webhook push")
    parser.add_argument("--platforms", default="tiktok,x", help="Comma-separated platforms: tiktok,x")
    parser.add_argument("--source", choices=["cache", "scrape", "resume"], default="")
    parser.add_argument("--enforce-heat", action="store_true", help="Apply relaxed UA geo heat threshold as a hard filter")
    parser.add_argument("--dry-run", action="store_true", help="Write JSON and print Feishu card instead of sending")
    parser.add_argument("--push-feishu", action="store_true", help="Send Feishu webhook. Default is JSON only.")
    parser.add_argument("--per-query", type=int, default=10, help="Scrape mode only: max items per search query")
    parser.add_argument("--review-pool-size", type=int, default=20, help="Review only the top N prefiltered candidates by heat score")
    parser.add_argument("--max-review", type=int, default=0, help="Manual test only: cap model-reviewed candidates; 0 means no cap")
    parser.add_argument("--max-items", type=int, default=5, help="Maximum passed items to include in this independent US T1 push")
    return parser.parse_args()


def parse_platforms(raw: str) -> list[str]:
    platforms: list[str] = []
    for value in re.split(r"[,;\s]+", raw or ""):
        platform = value.strip().lower()
        if platform in {"tt", "tik tok"}:
            platform = "tiktok"
        if platform == "twitter":
            platform = "x"
        if platform in {"tiktok", "x"} and platform not in platforms:
            platforms.append(platform)
    return platforms or ["tiktok", "x"]


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    haystack = text.lower()
    hits: list[str] = []
    for keyword in keywords:
        key = keyword.lower()
        pattern = rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])"
        if re.search(pattern, haystack):
            hits.append(keyword)
    return hits


def item_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("text"),
        item.get("title"),
        item.get("desc"),
        item.get("summary"),
        item.get("hotspotIntro"),
        item.get("video_summary"),
        item.get("searchQuery"),
        item.get("sourceQuery"),
        item.get("search_term"),
    ]
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else item.get("author")
    if isinstance(author, dict):
        parts.extend([author.get("nickName"), author.get("name"), author.get("username"), author.get("display_name")])
    hashtags = item.get("hashtags")
    if isinstance(hashtags, list):
        parts.extend(str(tag.get("title") if isinstance(tag, dict) else tag) for tag in hashtags)
    return clean_text(" ".join(str(part or "") for part in parts if part), max_len=3000)


def item_language_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("text"),
        item.get("title"),
        item.get("desc"),
        item.get("summary"),
        item.get("hotspotIntro"),
        item.get("video_summary"),
    ]
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else item.get("author")
    if isinstance(author, dict):
        parts.extend([author.get("nickName"), author.get("name"), author.get("username"), author.get("display_name")])
    hashtags = item.get("hashtags")
    if isinstance(hashtags, list):
        parts.extend(str(tag.get("title") if isinstance(tag, dict) else tag) for tag in hashtags)
    return clean_text(" ".join(str(part or "") for part in parts if part), max_len=3000)


def item_url(item: dict[str, Any]) -> str:
    return clean_text(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url") or item.get("upsertKey"))


def platform_language(item: dict[str, Any], platform: str) -> str:
    if platform == "tiktok":
        return clean_text(item.get("textLanguage") or item.get("language")).lower()
    raw_source = item.get("raw_source") if isinstance(item.get("raw_source"), dict) else {}
    return clean_text(raw_source.get("lang") or item.get("lang") or item.get("language")).lower()


def english_ratio_from_text(text: str) -> tuple[float, int, int]:
    text = re.sub(r"https?://\S+|www\.\S+", " ", text or "", flags=re.IGNORECASE)
    english_chars = 0
    effective_chars = 0
    for char in text:
        if ("A" <= char <= "Z") or ("a" <= char <= "z"):
            english_chars += 1
            effective_chars += 1
        elif char.isdigit() or char.isalpha():
            effective_chars += 1
    ratio = english_chars / effective_chars if effective_chars else 0.0
    return ratio, english_chars, effective_chars


def language_details(item: dict[str, Any], platform: str) -> dict[str, Any]:
    lang = platform_language(item, platform)
    if lang in {"en", "eng", "english"}:
        return {
            "isEnglish": True,
            "detectedLanguage": lang,
            "englishRatio": 1.0,
            "languageMethod": "platform_lang",
            "languageEffectiveChars": 0,
        }
    ratio, _english_chars, effective_chars = english_ratio_from_text(item_language_text(item))
    is_english = bool(effective_chars >= 10 and ratio >= 0.75)
    return {
        "isEnglish": is_english,
        "detectedLanguage": lang,
        "englishRatio": round(ratio, 4),
        "languageMethod": "text_ratio" if is_english else "failed",
        "languageEffectiveChars": effective_chars,
    }


def us_country_hits(item: dict[str, Any], platform: str) -> list[str]:
    hits = keyword_hits(item_text(item), US_KEYWORDS)
    if platform == "tiktok":
        code = clean_text(item.get("locationCreated") or (item.get("raw_source") or {}).get("locationCreated")).upper()
        if code == "US":
            hits.append("US")
    if platform == "x":
        # X search mode injects US terms, but cache mode still needs evidence in the post/author text.
        raw_source = item.get("raw_source") if isinstance(item.get("raw_source"), dict) else {}
        for key in ["location", "user_location", "place", "country"]:
            hits.extend(keyword_hits(clean_text(raw_source.get(key) or item.get(key)), US_KEYWORDS))
    return list(dict.fromkeys(hits))


def language_ok(item: dict[str, Any], platform: str) -> bool:
    return bool(language_details(item, platform).get("isEnglish"))


def heat_details(item: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    return {"heatPass": passes_relaxed_quality(item, rules), "heatValue": float(item.get("heatValue") or ranking_score(item, rules))}


def annotate(item: dict[str, Any], platform: str, source_mode: str, rules: dict[str, Any]) -> dict[str, Any]:
    updated = dict(item)
    updated["sourcePlatform"] = platform
    updated["hotspotPlatform"] = platform
    updated["platform"] = platform
    hits = us_country_hits(updated, platform)
    lang_details = language_details(updated, platform)
    details = heat_details(updated, rules)
    updated["usT1Targeting"] = {
        "isTarget": bool(hits and lang_details.get("isEnglish")),
        "platform": platform,
        "sourceQuery": clean_text(updated.get("sourceQuery") or updated.get("searchQuery") or updated.get("search_term")),
        "country": "US",
        "language": "en",
        "detectedLanguage": lang_details.get("detectedLanguage", ""),
        "englishRatio": lang_details.get("englishRatio", 0.0),
        "languageMethod": lang_details.get("languageMethod", "failed"),
        "languageEffectiveChars": lang_details.get("languageEffectiveChars", 0),
        "geoHits": hits,
        "sourceMode": source_mode,
        **details,
    }
    return updated


def load_cache_items(platform: str, rules: dict[str, Any]) -> list[dict[str, Any]]:
    if platform == "tiktok":
        raw = read_json(TIKTOK_RAW, [])
        items = raw if isinstance(raw, list) else []
        return [annotate(normalize_hotspot(item, rules=rules), "tiktok", "cache", rules) for item in items if isinstance(item, dict)]
    raw = read_json(X_RAW, [])
    pages = raw if isinstance(raw, list) else []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in pages:
        tweets = page.get("tweets") if isinstance(page, dict) else []
        if not isinstance(tweets, list):
            continue
        for tweet in tweets:
            if not isinstance(tweet, dict):
                continue
            key = clean_text(tweet.get("id") or tweet.get("url"))
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            items.append(annotate(normalize_x_hotspot(tweet, rules=rules), "x", "cache", rules))
    return items


def rapidapi_get(host: str, key: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
    url = f"https://{host}{path}?{urlencode({k: v for k, v in params.items() if v not in (None, '')})}"
    response = requests.get(url, headers={"x-rapidapi-key": key, "x-rapidapi-host": host}, timeout=45)
    response.raise_for_status()
    return response.json()


def normalize_tiktok_rapidapi(item: dict[str, Any], query: str, rules: dict[str, Any]) -> dict[str, Any]:
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else item.get("statsV2") if isinstance(item.get("statsV2"), dict) else {}
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    video = item.get("video") if isinstance(item.get("video"), dict) else {}
    video_id = clean_text(item.get("id"))
    username = clean_text(author.get("uniqueId") or author.get("id") or "user")
    normalized = {
        "id": video_id,
        "text": item.get("desc") or item.get("text") or "",
        "textLanguage": item.get("textLanguage") or item.get("language") or "",
        "createTime": item.get("createTime") or "",
        "locationCreated": item.get("locationCreated") or "",
        "webVideoUrl": f"https://www.tiktok.com/@{username}/video/{video_id}" if video_id else "",
        "videoMeta": {"duration": video.get("duration") or 0, "coverUrl": video.get("cover") or video.get("originCover") or ""},
        "mediaUrls": [video.get("cover") or video.get("originCover") or video.get("dynamicCover")],
        "diggCount": safe_int(stats.get("diggCount") or stats.get("likeCount")),
        "playCount": safe_int(stats.get("playCount")),
        "commentCount": safe_int(stats.get("commentCount")),
        "shareCount": safe_int(stats.get("shareCount")),
        "authorMeta": {"nickName": author.get("nickname") or username, "uniqueId": username},
        "sourceQuery": query,
        "searchQuery": query,
    }
    return annotate(normalize_hotspot(normalized, rules=rules), "tiktok", "scrape", rules)


def scrape_tiktok(rules: dict[str, Any], per_query: int) -> list[dict[str, Any]]:
    env = load_env()
    host = env.get("RAPIDAPI_TIKTOK_HOST", "tiktok-api23.p.rapidapi.com")
    key = env.get("RAPIDAPI_TIKTOK_KEY") or env.get("RAPIDAPI_KEY", "")
    path = env.get("RAPIDAPI_TIKTOK_SEARCH_PATH", "/api/search/video")
    if not key:
        raise RuntimeError("RAPIDAPI_TIKTOK_KEY or RAPIDAPI_KEY is required for US T1 TikTok scrape mode")
    items: list[dict[str, Any]] = []
    for query in rules.get("scrape", {}).get("search_queries", []):
        us_query = f"{query} USA"
        payload = rapidapi_get(host, key, path, {"keyword": us_query, "cursor": 0, "count": per_query, "region": "US", "country": "US", "language": "en"})
        raw_items = payload.get("item_list") if isinstance(payload.get("item_list"), list) else payload.get("itemList") if isinstance(payload.get("itemList"), list) else []
        for raw in raw_items:
            if isinstance(raw, dict):
                items.append(normalize_tiktok_rapidapi(raw, us_query, rules))
    return items


def nested_dict(value: Any, *keys: str) -> dict[str, Any]:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def nested_value(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def unwrap_x_tweet(node: Any) -> dict[str, Any]:
    current = node if isinstance(node, dict) else {}
    while isinstance(current, dict):
        if isinstance(nested_value(current, "tweet_results", "result"), dict):
            current = nested_value(current, "tweet_results", "result")
            continue
        if isinstance(nested_value(current, "tweetResult", "result"), dict):
            current = nested_value(current, "tweetResult", "result")
            continue
        if isinstance(nested_value(current, "itemContent", "tweet_results", "result"), dict):
            current = nested_value(current, "itemContent", "tweet_results", "result")
            continue
        if current.get("__typename") == "TweetWithVisibilityResults" and isinstance(current.get("tweet"), dict):
            current = current.get("tweet")
            continue
        if isinstance(current.get("result"), dict) and current.get("result") is not current:
            inner = current.get("result")
            if inner.get("rest_id") or inner.get("legacy") or inner.get("note_tweet") or inner.get("views") or inner.get("__typename"):
                current = inner
                continue
        break
    return current if isinstance(current, dict) else {}


def extract_x_text(tweet: dict[str, Any]) -> str:
    return clean_text(
        nested_value(tweet, "details", "full_text")
        or nested_value(tweet, "details", "text")
        or nested_value(tweet, "note_tweet", "note_tweet_results", "result", "text")
        or nested_value(tweet, "note_tweet", "note_tweet_results", "result", "richtext")
        or nested_value(tweet, "legacy", "full_text")
        or tweet.get("full_text")
        or tweet.get("text")
    )


def extract_x_author(tweet: dict[str, Any]) -> dict[str, str]:
    user_result = (
        nested_value(tweet, "core", "user_results", "result")
        or nested_value(tweet, "user_results", "result")
        or nested_value(tweet, "author", "result")
        or tweet.get("author")
        or {}
    )
    user_legacy = user_result.get("legacy") if isinstance(user_result, dict) and isinstance(user_result.get("legacy"), dict) else user_result
    user_core = user_result.get("core") if isinstance(user_result, dict) and isinstance(user_result.get("core"), dict) else {}
    username = clean_text(
        user_core.get("screen_name")
        or user_legacy.get("screen_name")
        or user_legacy.get("username")
        or user_legacy.get("userName")
        or tweet.get("userName")
        or tweet.get("username")
    )
    display_name = clean_text(
        user_core.get("name")
        or user_legacy.get("name")
        or user_legacy.get("display_name")
        or user_legacy.get("displayName")
        or tweet.get("authorName")
        or username
    )
    return {"username": username, "display_name": display_name}


def extract_x_media_items(tweet: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [
        tweet.get("media_entities"),
        nested_value(tweet, "legacy", "media_entities"),
        nested_value(tweet, "legacy", "extended_entities", "media"),
        nested_value(tweet, "extended_entities", "media"),
        nested_value(tweet, "legacy", "entities", "media"),
        nested_value(tweet, "entities", "media"),
    ]
    for media in sources:
        if isinstance(media, list) and media:
            return [item for item in media if isinstance(item, dict)]
    return []


def extract_x_media_types(tweet: dict[str, Any]) -> list[str]:
    media_types: list[str] = []
    for media in extract_x_media_items(tweet):
        explicit = clean_text(media.get("type") or media.get("media_type") or media.get("mediaType")).lower()
        if explicit:
            media_types.append(explicit)
            continue
        typename = clean_text(nested_value(media, "media_results", "result", "media_info", "__typename")).lower()
        if "video" in typename:
            media_types.append("video")
        elif "gif" in typename:
            media_types.append("animated_gif")
        elif "image" in typename or "photo" in typename:
            media_types.append("photo")
    return list(dict.fromkeys(media_types))


def extract_x_media_urls(tweet: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for media in extract_x_media_items(tweet):
        candidates = [
            media.get("media_url_https"),
            media.get("media_url"),
            media.get("url"),
            media.get("expanded_url"),
            media.get("preview_image_url"),
            nested_value(media, "original_info", "url"),
            nested_value(media, "media_results", "result", "media_url_https"),
            nested_value(media, "media_results", "result", "mediaUrlHttps"),
            nested_value(media, "media_results", "result", "preview_image_url"),
            nested_value(media, "media_results", "result", "previewImageUrl"),
        ]
        variants = nested_value(media, "video_info", "variants") or nested_value(media, "media_results", "result", "media_info", "variants") or []
        if isinstance(variants, list):
            candidates.extend(variant.get("url") for variant in variants if isinstance(variant, dict))
        for candidate in candidates:
            value = clean_text(candidate)
            if value.startswith("http"):
                urls.append(value)
    return list(dict.fromkeys(urls))


def extract_x_view_count(tweet: dict[str, Any]) -> int:
    return safe_int(
        nested_value(tweet, "views", "count")
        or nested_value(tweet, "ext_views", "count")
        or nested_value(tweet, "legacy", "views", "count")
        or tweet.get("viewCount")
        or tweet.get("impressionCount")
        or tweet.get("views")
    )


def build_x_url(tweet: dict[str, Any], author: dict[str, str]) -> str:
    direct = clean_text(tweet.get("url") or tweet.get("tweetUrl") or tweet.get("postUrl"))
    if direct:
        return direct
    tweet_id = clean_text(tweet.get("rest_id") or tweet.get("id_str") or tweet.get("id") or tweet.get("tweetId"))
    return f"https://x.com/{author.get('username')}/status/{tweet_id}" if author.get("username") and tweet_id else ""


def looks_like_x_tweet(node: Any) -> bool:
    tweet = unwrap_x_tweet(node)
    tweet_id = tweet.get("rest_id") or tweet.get("id_str") or tweet.get("id") or tweet.get("tweetId")
    has_content = bool(extract_x_text(tweet) or tweet.get("legacy") or tweet.get("note_tweet") or tweet.get("views") or tweet.get("core"))
    typename = clean_text(tweet.get("__typename"))
    return bool(tweet_id and (has_content or "Tweet" in typename))


def normalize_x_rapidapi_node(node: dict[str, Any], search_term: str) -> dict[str, Any]:
    tweet = unwrap_x_tweet(node)
    legacy = tweet.get("legacy") if isinstance(tweet.get("legacy"), dict) else {}
    author = extract_x_author(tweet)
    media_types = extract_x_media_types(tweet)
    media_urls = extract_x_media_urls(tweet)
    return {
        "id": clean_text(tweet.get("rest_id") or tweet.get("id_str") or tweet.get("id") or tweet.get("tweetId")),
        "url": build_x_url(tweet, author),
        "text": extract_x_text(tweet),
        "author": author,
        "created_at": legacy.get("created_at") or tweet.get("created_at") or tweet.get("createdAt") or nested_value(tweet, "details", "created_at") or "",
        "like_count": safe_int(nested_value(tweet, "counts", "favorite_count") or legacy.get("favorite_count") or tweet.get("favoriteCount") or tweet.get("likeCount") or tweet.get("likes")),
        "view_count": extract_x_view_count(tweet),
        "reply_count": safe_int(nested_value(tweet, "counts", "reply_count") or legacy.get("reply_count") or tweet.get("replyCount") or tweet.get("replies")),
        "retweet_count": safe_int(nested_value(tweet, "counts", "retweet_count") or legacy.get("retweet_count") or tweet.get("retweetCount") or tweet.get("retweets")),
        "media_types": media_types,
        "media_urls": media_urls,
        "media_count": len(media_types),
        "has_visual_media": bool(media_types),
        "search_term": search_term,
        "raw_source": {
            "lang": legacy.get("lang") or tweet.get("lang") or tweet.get("language") or "en",
            "media_count": len(media_types),
            "media_types": media_types,
            "media_urls": media_urls,
            "has_visual_media": bool(media_types),
        },
    }


def extract_x_tweets(payload: Any, search_term: str = "") -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                collect(item)
            return
        if not isinstance(node, dict):
            return
        if looks_like_x_tweet(node):
            normalized = normalize_x_rapidapi_node(node, search_term)
            key = clean_text(normalized.get("id") or normalized.get("url"))
            if key and key not in seen:
                seen.add(key)
                results.append(normalized)
        for value in node.values():
            collect(value)

    collect(payload)
    return results


def scrape_x(rules: dict[str, Any], per_query: int) -> list[dict[str, Any]]:
    env = load_env()
    host = env.get("X_RAPIDAPI_HOST", "twitter241.p.rapidapi.com")
    key = env.get("X_RAPIDAPI_KEY", "")
    if not key:
        raise RuntimeError("X_RAPIDAPI_KEY is required for US T1 X scrape mode")
    items: list[dict[str, Any]] = []
    for query in rules.get("x_scrape", {}).get("search_queries", []):
        us_query = f'({query}) lang:en ("United States" OR USA OR America OR American)'
        payload = rapidapi_get(host, key, "/search-v3", {"query": us_query, "type": "Top", "count": per_query})
        for raw in extract_x_tweets(payload, us_query):
            items.append(annotate(normalize_x_hotspot(raw, rules=rules), "x", "scrape", rules))
    return items


def product_review_prompt(item: dict[str, Any], fit: dict[str, Any]) -> str:
    return (
        "Audit this social post against the product manual. Return strict JSON with keys: "
        "isAllowed, primaryProduct, confidence, reason. primaryProduct must be evoke, toki, kavi, avatar_jigsaw, or none. "
        "Only allow material that clearly serves Evoke/Toki/Kavi/Avatar as an ad creative, product template, effect, or material-library reference.\n\n"
        f"Product manual summary:\n{US_REVIEW_MANUAL}\n\n"
        f"Keyword product fit:\n{json.dumps(fit, ensure_ascii=False)}\n\n"
        f"Candidate:\n{json.dumps(compact_candidate(item), ensure_ascii=False)}"
    )


def us_review_prompt(item: dict[str, Any]) -> str:
    return (
        "Audit this candidate for a US English UA/product push. Return strict JSON with keys: "
        "isAllowed, confidence, reason, adUseCase. Allow only if it is safe, English, US-relevant, and has clear "
        "advertising or template reuse value for Evoke/Toki/Kavi/Avatar. Reject generic entertainment, celebrity gossip, "
        "news, politics, IP-dependent material, adult/suggestive bait, crypto/Web3, and weakly reusable posts.\n\n"
        f"Manual:\n{US_REVIEW_MANUAL}\n\n"
        f"Candidate:\n{json.dumps(compact_candidate(item), ensure_ascii=False)}"
    )


def compact_candidate(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": item.get("hotspotPlatform"),
        "url": item_url(item),
        "text": item_text(item),
        "views": item.get("playCount"),
        "likes": item.get("diggCount") or item.get("likeCount"),
        "comments": item.get("commentCount"),
        "heatValue": item.get("heatValue"),
        "usT1Targeting": item.get("usT1Targeting"),
        "productFit": item.get("productFit"),
    }


def openrouter_json(prompt: str, model: str) -> dict[str, Any]:
    env = load_env()
    key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    if not key:
        return {"isAllowed": False, "confidence": 0, "reason": "OPENROUTER_API_KEY missing", "model": model}
    last_error = ""
    for attempt in range(3):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}, "max_tokens": 650},
                timeout=45,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"].get("content") or "{}"
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else {"isAllowed": False, "reason": "model returned non-object", "model": model}
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            body = clean_text(exc.response.text if exc.response is not None else str(exc), 240)
            last_error = f"OpenRouter HTTP {status}: {body}"
            if status in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            break
        except (requests.RequestException, json.JSONDecodeError, KeyError, IndexError) as exc:
            last_error = f"OpenRouter error: {clean_text(exc, 240)}"
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            break
    return {"isAllowed": False, "confidence": 0, "reason": last_error or "OpenRouter review failed", "model": model}


def allowed_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "allowed", "pass"}


def normalize_product(value: Any) -> str:
    product = clean_text(value).lower()
    if product == "ai_avatar_jigsaw":
        product = "avatar_jigsaw"
    return product if product in FOCUS_PRODUCTS else "none"


def review_item(item: dict[str, Any], rules: dict[str, Any], model: str) -> dict[str, Any] | None:
    if is_excluded_by_rules(item, rules, include_summary=True):
        return None
    fit = product_fit_details(item, rules)
    item["productFit"] = fit
    primary = normalize_product(fit.get("primaryProduct"))
    if not (fit.get("isProductCandidate") and primary in FOCUS_PRODUCTS):
        # Still require the model manual to agree; deterministic fit alone is not enough.
        pass
    product_raw = openrouter_json(product_review_prompt(item, fit), model)
    product_raw["model"] = model
    product = normalize_product(product_raw.get("primaryProduct") or product_raw.get("recommendedProduct") or primary)
    if not allowed_value(product_raw.get("isAllowed")) or product not in FOCUS_PRODUCTS:
        item["usT1ProductReview"] = product_raw
        return None
    item["usT1ProductReview"] = {**product_raw, "primaryProduct": product}
    us_raw = openrouter_json(us_review_prompt(item), model)
    us_raw["model"] = model
    item["usT1OpenRouterReview"] = us_raw
    if not allowed_value(us_raw.get("isAllowed")):
        return None
    item["pushObject"] = "ALL"
    item["recommendedProduct"] = product
    return item


def candidate_filter(items: list[dict[str, Any]], rules: dict[str, Any], *, enforce_heat: bool) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for item in items:
        details = item.get("usT1Targeting") if isinstance(item.get("usT1Targeting"), dict) else {}
        if not details.get("isTarget"):
            continue
        if enforce_heat and not details.get("heatPass"):
            continue
        if is_excluded_by_rules(item, rules, include_summary=True):
            continue
        kept.append(item)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in sorted(kept, key=lambda value: float(value.get("heatValue") or ranking_score(value, rules)), reverse=True):
        key = item_url(item) or clean_text(item.get("id"))
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(item)
    return deduped


def write_stage_snapshot(path: Path, run_id: str, source: str, platforms: list[str], items: list[dict[str, Any]], extra: dict[str, Any] | None = None) -> None:
    payload = {
        "schemaVersion": 1,
        "runId": run_id,
        "source": source,
        "platforms": platforms,
        "itemCount": len(items),
        "items": items,
    }
    if extra:
        payload.update(extra)
    atomic_write(path, payload)


def load_resume_candidates() -> list[dict[str, Any]]:
    payload = read_json(CANDIDATES_PATH, {})
    items = payload.get("items") if isinstance(payload, dict) else []
    return [item for item in items if isinstance(item, dict)]


def atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def platform_label(platforms: list[str]) -> str:
    labels = {"tiktok": "TikTok", "x": "X"}
    return " / ".join(labels.get(platform, platform.upper()) for platform in platforms)


def build_card(items: list[dict[str, Any]], run_id: str, platforms: list[str]) -> dict[str, Any]:
    label = platform_label(platforms)
    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": f"**平台**: {label}\n**通过数量**: {len(items)}\n**Run ID**: {run_id}",
        },
        {"tag": "hr"},
    ]
    for index, item in enumerate(items, 1):
        url = item_url(item)
        title = clean_text(item.get("title") or item.get("text") or item.get("hotspotIntro") or url, max_len=80)
        product_review = item.get("usT1ProductReview") if isinstance(item.get("usT1ProductReview"), dict) else {}
        us_review = item.get("usT1OpenRouterReview") if isinstance(item.get("usT1OpenRouterReview"), dict) else {}
        elements.append(
            {
                "tag": "markdown",
                "content": (
                    f"**{index}. {clean_text(item.get('hotspotPlatform')).upper()} [{title}]({url})**\n"
                    f"- 热度: {item.get('heatValue', 0)} | 播放: {safe_int(item.get('playCount'))} | "
                    f"点赞: {safe_int(item.get('diggCount') or item.get('likeCount'))} | 评论: {safe_int(item.get('commentCount'))}\n"
                    f"- 产品: {item.get('recommendedProduct', '')} | 推送对象: ALL\n"
                    f"- 产品审核: {clean_text(product_review.get('reason'), 180)}\n"
                    f"- 美国投放审核: {clean_text(us_review.get('reason'), 180)}"
                ),
            }
        )
    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": f"美国内容候选推送 - {label}"}, "template": "blue"},
            "body": {"elements": elements},
        },
    }


def push_webhook(card: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return {"dry_run": True}
    load_env()
    webhook = os.environ.get("FEISHU_WEBHOOK", "")
    if not webhook:
        raise RuntimeError("Missing FEISHU_WEBHOOK")
    response = requests.post(webhook, headers={"Content-Type": "application/json; charset=utf-8"}, json=card, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") not in (0, None):
        raise RuntimeError(f"Feishu webhook push failed: {payload}")
    return payload


def maybe_push_webhook(card: dict[str, Any], *, enabled: bool, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return push_webhook(card, dry_run=True)
    if not enabled:
        return {"skipped": True, "reason": "US T1 Feishu push disabled by default"}
    return push_webhook(card, dry_run=False)


def main() -> int:
    env = load_env()
    args = parse_args()
    rules = load_feedback_rules()
    source = args.source or env.get("US_T1_DEFAULT_SOURCE") or "cache"
    enforce_heat = args.enforce_heat or env_bool("US_T1_ENFORCE_HEAT", False, env)
    model = os.environ.get("US_T1_REVIEW_MODEL") or env.get("US_T1_REVIEW_MODEL") or "qwen/qwen3.7-max"
    platforms = parse_platforms(args.platforms)
    max_items = max(1, int(env.get("US_T1_MAX_ITEMS") or args.max_items or 5))
    push_enabled = bool(args.push_feishu or env_bool("US_T1_PUSH_ENABLED", False, env))
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    candidates: list[dict[str, Any]] = []
    if source == "resume":
        candidates = load_resume_candidates()
    else:
        for platform in platforms:
            if source == "scrape":
                candidates.extend(scrape_tiktok(rules, args.per_query) if platform == "tiktok" else scrape_x(rules, args.per_query))
            else:
                candidates.extend(load_cache_items(platform, rules))
    write_stage_snapshot(CANDIDATES_PATH, run_id, source, platforms, candidates, {"stage": "candidates"})
    filtered = candidate_filter(candidates, rules, enforce_heat=enforce_heat)
    write_stage_snapshot(FILTERED_PATH, run_id, source, platforms, filtered, {"stage": "filtered", "enforceHeat": enforce_heat})
    review_pool_size = max(1, int(args.review_pool_size or 20))
    review_candidates = filtered[:review_pool_size]
    if args.max_review and args.max_review > 0:
        review_candidates = review_candidates[: args.max_review]
    passed: list[dict[str, Any]] = []
    blocked = 0
    review_errors: list[dict[str, Any]] = []
    for index, item in enumerate(review_candidates, 1):
        try:
            reviewed = review_item(dict(item), rules, model)
        except Exception as exc:  # Keep the independent debug pipeline from losing all later candidates.
            reviewed = None
            review_errors.append({"index": index, "url": item_url(item), "error": clean_text(exc, 240)})
        if reviewed:
            passed.append(reviewed)
        else:
            blocked += 1
        write_stage_snapshot(
            REVIEW_PROGRESS_PATH,
            run_id,
            source,
            platforms,
            passed,
            {
                "stage": "review_progress",
                "reviewedSoFar": index,
                "reviewTotal": len(review_candidates),
                "blockedSoFar": blocked,
                "reviewErrors": review_errors,
            },
        )
    passed_before_cap = len(passed)
    passed = sorted(passed, key=lambda item: float(item.get("heatValue") or ranking_score(item, rules)), reverse=True)[:max_items]

    report = {
        "schemaVersion": 1,
        "runId": run_id,
        "source": source,
        "platforms": platforms,
        "enforceHeat": enforce_heat,
        "candidateCount": len(candidates),
        "filteredCount": len(filtered),
        "reviewedCount": len(review_candidates),
        "reviewPoolSize": review_pool_size,
        "maxReview": max(0, int(args.max_review or 0)),
        "maxItems": max_items,
        "passedBeforeCap": passed_before_cap,
        "passedCount": len(passed),
        "cappedCount": max(0, passed_before_cap - len(passed)),
        "blockedAfterReview": blocked,
        "reviewErrors": review_errors,
        "feishuPushEnabled": push_enabled and not args.dry_run,
        "candidateSnapshotPath": str(CANDIDATES_PATH),
        "filteredSnapshotPath": str(FILTERED_PATH),
        "reviewProgressPath": str(REVIEW_PROGRESS_PATH),
        "items": passed,
    }
    atomic_write(OUTPUT_DIR / "latest.json", report)
    atomic_write(RUNS_DIR / f"{run_id}.json", report)
    card = build_card(passed, run_id, platforms)
    push_result = maybe_push_webhook(card, enabled=push_enabled, dry_run=args.dry_run)
    print(json.dumps({"reportPath": str(OUTPUT_DIR / "latest.json"), "push": push_result, "passed": len(passed)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
