from __future__ import annotations

import os
import re
from typing import Any

import requests

from env_utils import env_int, load_env


TEXT_KEYS = ["text", "full_text", "comment", "content", "reply", "body"]


def clean_comment_text(value: Any, max_len: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def extract_comment_text(value: Any) -> str:
    if isinstance(value, str):
        return clean_comment_text(value)
    if not isinstance(value, dict):
        return ""
    for key in TEXT_KEYS:
        text = clean_comment_text(value.get(key))
        if text:
            return text
    legacy = value.get("legacy")
    if isinstance(legacy, dict):
        for key in TEXT_KEYS:
            text = clean_comment_text(legacy.get(key))
            if text:
                return text
    return ""


def unique_comments(comments: list[str], limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for comment in comments:
        text = clean_comment_text(comment)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def collect_nested_comments(payload: Any, limit: int) -> list[str]:
    comments: list[str] = []

    def walk(value: Any) -> None:
        if len(comments) >= limit:
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
                if len(comments) >= limit:
                    break
            return
        if not isinstance(value, dict):
            return
        text = extract_comment_text(value)
        if text:
            comments.append(text)
            if len(comments) >= limit:
                return
        for child_key in ["comments", "replies", "items", "data", "results", "timeline"]:
            child = value.get(child_key)
            if child is not None:
                walk(child)
                if len(comments) >= limit:
                    return

    walk(payload)
    return unique_comments(comments, limit)


def existing_comments(item: dict[str, Any], limit: int) -> list[str]:
    comments: list[str] = []
    for key in ["topComments", "comments", "latestComments", "commentList", "comment_list", "replies"]:
        value = item.get(key)
        if isinstance(value, list):
            comments.extend(extract_comment_text(comment) for comment in value)
    return unique_comments(comments, limit)


def fetch_tiktok_dataset_comments(item: dict[str, Any], limit: int, timeout: float = 20.0) -> list[str]:
    url = str(item.get("commentsDatasetUrl") or "").strip()
    if not url:
        return []
    headers: dict[str, str] = {}
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return collect_nested_comments(response.json(), limit)


def fetch_x_reply_comments(item: dict[str, Any], limit: int, timeout: float = 20.0) -> list[str]:
    env = load_env()
    api_key = os.environ.get("X_RAPIDAPI_KEY") or env.get("X_RAPIDAPI_KEY", "")
    if not api_key:
        return []
    endpoint = os.environ.get("X_REPLIES_ENDPOINT") or env.get("X_REPLIES_ENDPOINT") or "/tweet/replies"
    host = os.environ.get("X_RAPIDAPI_HOST") or env.get("X_RAPIDAPI_HOST") or "twitter241.p.rapidapi.com"
    id_param = os.environ.get("X_REPLIES_ID_PARAM") or env.get("X_REPLIES_ID_PARAM") or "pid"
    count_param = os.environ.get("X_REPLIES_COUNT_PARAM") or env.get("X_REPLIES_COUNT_PARAM") or "count"
    tweet_id = str(item.get("id") or item.get("tweetId") or "").strip()
    if not tweet_id or not endpoint:
        return []
    url = f"https://{host}{endpoint if endpoint.startswith('/') else '/' + endpoint}"
    response = requests.get(
        url,
        headers={"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": host},
        params={id_param: tweet_id, count_param: limit},
        timeout=timeout,
    )
    response.raise_for_status()
    return collect_nested_comments(response.json(), limit)


def enrich_top_comments(items: list[dict[str, Any]], platform: str, limit: int | None = None) -> list[dict[str, Any]]:
    env = load_env()
    resolved_limit = limit if limit is not None else env_int("TOP_COMMENTS_LIMIT", 20, env)
    resolved_limit = max(0, resolved_limit)
    if resolved_limit <= 0:
        return [dict(item, topComments=[]) for item in items]
    enriched: list[dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        updated = dict(item)
        comments = existing_comments(updated, resolved_limit)
        if not comments:
            try:
                if platform == "x":
                    comments = fetch_x_reply_comments(updated, resolved_limit)
                else:
                    comments = fetch_tiktok_dataset_comments(updated, resolved_limit)
            except Exception as exc:
                print(f"  - Comment fetch skipped for {platform} item {index}/{len(items)}: {exc}", flush=True)
                comments = []
        updated["topComments"] = comments[:resolved_limit]
        enriched.append(updated)
        print(f"  - Top comments collected: {index}/{len(items)} ({len(updated['topComments'])})", flush=True)
    return enriched
