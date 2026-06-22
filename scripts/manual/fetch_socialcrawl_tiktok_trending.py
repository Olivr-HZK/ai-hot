from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
BASE_DIR = SCRIPTS_DIR.parent

sys.path.insert(0, str(SCRIPTS_DIR))

from env_utils import env_int, load_env
from scrape_checkpoint import now_iso


MANUAL_AUDIT_DIR = BASE_DIR / "skill_runs" / "manual_audits"
DEFAULT_TRENDING_URL = "https://socialcrawl.dev/v1/tiktok/trending"
ESTIMATED_CREDITS_PER_REQUEST = 5


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch TikTok trending posts from SocialCrawl into an isolated manual audit file."
    )
    parser.add_argument("--region", default="US", help="ISO 3166-1 alpha-2 region code. Default: US.")
    parser.add_argument("--trim", default="true", choices=["true", "false"], help="SocialCrawl trim parameter.")
    parser.add_argument("--max-items", type=int, default=None, help="Maximum normalized items to keep.")
    parser.add_argument("--timeout", type=int, default=45, help="Request timeout in seconds.")
    parser.add_argument("--output", default="", help="Optional output JSON path.")
    parser.add_argument(
        "--confirm-spend-credits",
        action="store_true",
        help="Required to call SocialCrawl. One request is expected to cost 5 credits.",
    )
    return parser.parse_args()


def find_first_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    for key in ("items", "videos", "results", "posts", "item_list", "itemList", "aweme_list"):
        nested = value.get(key)
        if isinstance(nested, list):
            return nested
    data = value.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        found = find_first_list(data)
        if found:
            return found
    for nested in value.values():
        if isinstance(nested, dict):
            found = find_first_list(nested)
            if found:
                return found
    return []


def first_value(mapping: dict[str, Any], keys: tuple[str, ...], default: Any = "") -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return default


def first_nested_or_flat(mapping: dict[str, Any], flat_keys: tuple[str, ...], nested: dict[str, Any], nested_keys: tuple[str, ...]) -> Any:
    flat_value = first_value(mapping, flat_keys, None)
    if flat_value not in (None, ""):
        return flat_value
    return first_value(nested, nested_keys, 0)


def nested_value(mapping: dict[str, Any], paths: tuple[tuple[str, ...], ...], default: Any = "") -> Any:
    for path in paths:
        current: Any = mapping
        for key in path:
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current.get(key)
        if current not in (None, ""):
            return current
    return default


def int_value(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def normalize_author(raw: dict[str, Any]) -> dict[str, Any]:
    author = first_value(raw, ("author", "authorMeta", "user", "creator"), {})
    if not isinstance(author, dict):
        author = {}
    username_value = first_value(author, ("username", "uniqueId", "unique_id", "handle"), "")
    username = username_value if isinstance(username_value, str) else ""
    return {
        "username": str(username or "").lstrip("@"),
        "nickName": first_value(author, ("nickName", "nickname", "name", "displayName"), ""),
        "id": first_value(author, ("id", "uid", "userId", "secUid"), ""),
        "followers": int_value(first_value(author, ("followers", "followerCount", "fans"), 0)),
    }


def normalize_item(raw_item: Any, *, region: str) -> dict[str, Any]:
    raw = raw_item if isinstance(raw_item, dict) else {"value": raw_item}
    author = normalize_author(raw)
    stats = first_value(raw, ("stats", "statistics", "engagement"), {})
    if not isinstance(stats, dict):
        stats = {}
    video = first_value(raw, ("video", "videoMeta", "media"), {})
    if not isinstance(video, dict):
        video = {}
    computed = first_value(raw, ("computed", "metadata"), {})
    if not isinstance(computed, dict):
        computed = {}

    cover_value = first_value(
        raw,
        ("coverUrl", "thumbnail", "thumbnailUrl", "cover"),
        nested_value(video, (("cover",), ("coverUrl",), ("thumbnail",))),
    )
    if isinstance(cover_value, dict):
        cover_url = first_value(cover_value, ("uri", "url", "coverUrl", "thumbnailUrl"), "")
        urls = cover_value.get("url_list")
        if not cover_url and isinstance(urls, list) and urls:
            cover_url = urls[0]
    else:
        cover_url = cover_value
    video_id = first_value(raw, ("id", "aweme_id", "videoId", "video_id", "postId"), "")
    author_username = str(author.get("username") or "").strip()
    fallback_url = f"https://www.tiktok.com/@{author_username}/video/{video_id}" if author_username and video_id else ""
    url = first_value(
        raw,
        ("url", "webVideoUrl", "shareUrl", "videoUrl", "postUrl"),
        nested_value(video, (("url",), ("playAddr",), ("downloadAddr",)), fallback_url),
    )
    text = first_value(raw, ("text", "desc", "description", "caption", "title"), "")
    item_id = video_id

    normalized = {
        "id": str(item_id or ""),
        "url": str(url or ""),
        "webVideoUrl": str(url or ""),
        "text": str(text or ""),
        "author": author,
        "authorMeta": author,
        "playCount": int_value(
            first_nested_or_flat(raw, ("playCount", "play_count", "viewCount", "views"), stats, ("playCount", "play_count", "views"))
        ),
        "diggCount": int_value(
            first_nested_or_flat(raw, ("diggCount", "digg_count", "likeCount", "likes"), stats, ("diggCount", "digg_count", "likes"))
        ),
        "commentCount": int_value(
            first_nested_or_flat(raw, ("commentCount", "comment_count", "comments"), stats, ("commentCount", "comment_count", "comments"))
        ),
        "shareCount": int_value(
            first_nested_or_flat(raw, ("shareCount", "share_count", "shares"), stats, ("shareCount", "share_count", "shares"))
        ),
        "coverUrl": str(cover_url or ""),
        "createTime": first_value(raw, ("createTime", "createdAt", "create_time", "timestamp"), ""),
        "language": first_value(raw, ("language", "textLanguage"), first_value(computed, ("language",), "")),
        "contentCategory": first_value(raw, ("contentCategory", "category"), first_value(computed, ("content_category",), "")),
        "engagementRate": first_value(raw, ("engagementRate",), first_value(computed, ("engagement_rate",), "")),
        "captureSource": "hot_feed",
        "sourcePath": "socialcrawl_hot_feed",
        "sourceQuery": "hot_feed",
        "hotFeedProvider": "socialcrawl",
        "region": region.upper(),
        "raw_source": raw,
    }
    normalized["videoMeta"] = {
        "duration": int_value(first_value(raw, ("duration",), first_value(video, ("duration",), 0))),
        "webVideoUrl": normalized["webVideoUrl"],
        "coverUrl": normalized["coverUrl"],
    }
    if normalized["coverUrl"]:
        normalized["mediaUrls"] = [normalized["coverUrl"]]
    return normalized


def fetch_trending(*, url: str, api_key: str, region: str, trim: str, timeout: int) -> tuple[dict[str, Any], dict[str, str]]:
    response = requests.get(
        url,
        params={"region": region.upper(), "trim": trim},
        headers={"x-api-key": api_key},
        timeout=timeout,
    )
    headers = {
        "x_request_id": response.headers.get("X-Request-Id", ""),
        "x_credits_used": response.headers.get("X-Credits-Used", ""),
        "x_credits_remaining": response.headers.get("X-Credits-Remaining", ""),
        "x_cache": response.headers.get("X-Cache", ""),
    }
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        payload = {"success": True, "data": payload}
    return payload, headers


def main() -> int:
    args = parse_args()
    env = load_env()
    api_key = (env.get("SOCIALCRAWL_API_KEY") or "").strip()
    url = (env.get("SOCIALCRAWL_TIKTOK_TRENDING_URL") or DEFAULT_TRENDING_URL).strip()
    max_items = args.max_items if args.max_items is not None else env_int("SOCIALCRAWL_TIKTOK_MAX_ITEMS", 100, env)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output) if args.output else MANUAL_AUDIT_DIR / f"socialcrawl_tiktok_trending_{run_id}.json"
    if not output_path.is_absolute():
        output_path = BASE_DIR / output_path

    if not api_key:
        print("SOCIALCRAWL_API_KEY is missing in .env; no request was sent.", file=sys.stderr)
        return 2

    if not args.confirm_spend_credits:
        print(
            "SocialCrawl TikTok trending request is not sent. "
            f"Estimated cost: {ESTIMATED_CREDITS_PER_REQUEST} credits for 1 request. "
            "Re-run with --confirm-spend-credits to proceed."
        )
        return 0

    report: dict[str, Any] = {
        "schemaVersion": 1,
        "provider": "socialcrawl",
        "endpoint": url,
        "region": args.region.upper(),
        "trim": args.trim,
        "startedAt": now_iso(),
        "estimatedCredits": ESTIMATED_CREDITS_PER_REQUEST,
        "status": "running",
        "itemCount": 0,
        "normalizedItems": [],
        "rawResponse": {},
        "responseHeaders": {},
        "error": "",
    }

    try:
        payload, headers = fetch_trending(
            url=url,
            api_key=api_key,
            region=args.region,
            trim=args.trim,
            timeout=args.timeout,
        )
        raw_items = find_first_list(payload)
        normalized = [normalize_item(item, region=args.region) for item in raw_items[: max(0, max_items)]]
        report.update(
            {
                "finishedAt": now_iso(),
                "status": "success",
                "itemCount": len(normalized),
                "rawItemCount": len(raw_items),
                "normalizedItems": normalized,
                "rawResponse": payload,
                "responseHeaders": headers,
                "creditsUsed": payload.get("credits_used") or headers.get("x_credits_used") or "",
                "creditsRemaining": payload.get("credits_remaining") or headers.get("x_credits_remaining") or "",
                "cached": payload.get("cached", headers.get("x_cache") == "HIT"),
            }
        )
    except (requests.RequestException, json.JSONDecodeError) as exc:
        report.update({"finishedAt": now_iso(), "status": "failed", "error": str(exc)})
        atomic_write_json(output_path, report)
        atomic_write_json(MANUAL_AUDIT_DIR / "socialcrawl_tiktok_trending_latest.json", report)
        print(f"SocialCrawl trending fetch failed; report written to {output_path}", file=sys.stderr)
        return 1

    atomic_write_json(output_path, report)
    atomic_write_json(MANUAL_AUDIT_DIR / "socialcrawl_tiktok_trending_latest.json", report)
    print(f"SocialCrawl trending fetch completed: {report['itemCount']} items; report written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
