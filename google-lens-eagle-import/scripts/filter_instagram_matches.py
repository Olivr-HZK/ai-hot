from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
BASE_DIR = SKILL_DIR.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
MANUAL_DIR = SCRIPTS_DIR / "manual"
INSTAGRAM_DIR = SCRIPTS_DIR / "instagram"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(MANUAL_DIR))
sys.path.insert(0, str(INSTAGRAM_DIR))

from env_utils import load_env
from instagram.ins_rules import load_ins_rules
from instagram.ins_scoring import clean_text, passes_media_policy
from manual.ins_keyword_discovery import (
    DEFAULT_ACCOUNT_COOKIE,
    InstagramAccountSearchClient,
    apply_engagement_gate,
    audit_candidates,
    engagement_score,
    normalize_candidates,
    summarize_item,
)
from pipeline_variant import resolve_pipeline_variant


DEFAULT_MAX_CANDIDATES = 100
DEFAULT_MIN_LIKES = 500
DEFAULT_MIN_COMMENTS = 10
DEFAULT_ENGAGEMENT_TOP_N = 100


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def shortcode_from_url(url: str) -> tuple[str, str]:
    match = re.search(r"instagram\.com/(p|reel|tv)/([^/?#]+)", url or "", flags=re.IGNORECASE)
    if not match:
        return "", ""
    return match.group(1).lower(), match.group(2)


def canonical_instagram_permalink(value: Any) -> str:
    text = unquote(str(value or "").strip())
    if not text:
        return ""
    if text.startswith("/"):
        text = f"https://www.instagram.com{text}"
    match = re.search(r"(?:https?:)?//(?:www\.)?instagram\.com/(p|reel|tv)/([^/?#\s\"']+)", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return f"https://www.instagram.com/{match.group(1).lower()}/{match.group(2)}/"


def extract_urls_from_text(value: Any) -> list[str]:
    text = unquote(str(value or ""))
    urls: list[str] = []
    for match in re.finditer(r"(?:https?:)?//(?:www\.)?instagram\.com/(?:p|reel|tv)/[^/?#\s\"'<>]+", text, flags=re.IGNORECASE):
        url = canonical_instagram_permalink(match.group(0))
        if url and url not in urls:
            urls.append(url)
    return urls


def iter_visual_matches(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in [
        "allVisualMatches",
        "all_visual_matches",
        "visualMatchesCandidates",
        "visualMatches",
        "matches",
        "items",
        "results",
    ]:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for value in payload.values():
        nested = iter_visual_matches(value)
        if nested:
            return nested
    return []


def first_thumbnail_url(match: dict[str, Any]) -> str:
    thumbnails = match.get("thumbnails")
    if isinstance(thumbnails, list):
        for thumbnail in thumbnails:
            if isinstance(thumbnail, dict):
                src = clean_text(thumbnail.get("src") or thumbnail.get("url"))
                if src:
                    return src
            else:
                src = clean_text(thumbnail)
                if src:
                    return src
    return clean_text(match.get("thumbnailUrl") or match.get("thumbnail"))


def candidate_from_match(match: dict[str, Any], index: int) -> dict[str, Any] | None:
    candidate_urls: list[str] = []
    for key in ["sourceUrl", "source_url", "url", "link", "href", "pageUrl", "imageContextUrl"]:
        url = canonical_instagram_permalink(match.get(key))
        if url and url not in candidate_urls:
            candidate_urls.append(url)
        for nested_url in extract_urls_from_text(match.get(key)):
            if nested_url not in candidate_urls:
                candidate_urls.append(nested_url)
    if not candidate_urls:
        for value in match.values():
            for url in extract_urls_from_text(value):
                if url not in candidate_urls:
                    candidate_urls.append(url)
    if not candidate_urls:
        return None
    url = candidate_urls[0]
    media_path, shortcode = shortcode_from_url(url)
    seed_fields = {
        key: match.get(key)
        for key in [
            "seedId",
            "seedKeyword",
            "seedRank",
            "seedImagePath",
            "seedLocalImagePath",
            "seedSourceUrl",
            "seedTitle",
            "seedLensRunDir",
        ]
        if match.get(key) not in (None, "")
    }
    return {
        "rank": int(match.get("rank") or index),
        "url": url,
        "shortcode": shortcode,
        "mediaPath": media_path,
        "status": "found",
        "sourcePage": clean_text(match.get("sourceUrl") or match.get("source_url") or match.get("url")),
        "lensTitle": clean_text(match.get("title"), max_len=500),
        "lensDomain": clean_text(match.get("domain")),
        "lensPlatform": clean_text(match.get("platform")),
        "lensThumbnailUrl": first_thumbnail_url(match),
        **seed_fields,
    }


def extract_instagram_candidates(payload: Any, max_candidates: int = DEFAULT_MAX_CANDIDATES) -> list[dict[str, Any]]:
    matches = iter_visual_matches(payload)
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for index, match in enumerate(matches[: max(1, max_candidates)], 1):
        candidate = candidate_from_match(match, index)
        if not candidate:
            continue
        shortcode = clean_text(candidate.get("shortcode")).lower()
        key = shortcode or clean_text(candidate.get("url")).lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def metadata_block_reason(raw: dict[str, Any]) -> str:
    url = canonical_instagram_permalink(raw.get("url") or raw.get("permalink"))
    if not url:
        return "missing_permalink"
    if not (raw.get("timestamp") or raw.get("taken_at")):
        return "missing_timestamp"
    if not clean_text(raw.get("caption") or raw.get("title") or raw.get("description")):
        return "missing_caption"
    if not clean_text(raw.get("thumbnail") or raw.get("displayUrl") or raw.get("imageUrl")):
        return "missing_media"
    media_path, shortcode = shortcode_from_url(url)
    if not (clean_text(raw.get("ownerUsername") or raw.get("username")) or shortcode):
        return "missing_author_or_shortcode"
    return ""


def fetch_instagram_page_media(url: str, cookie_path: Path) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
        from manual.ins_keyword_discovery import read_netscape_cookies_for_playwright
    except ImportError as exc:
        raise RuntimeError("playwright is not installed; cannot fetch Instagram page media fallback") from exc
    cookies = read_netscape_cookies_for_playwright(cookie_path)
    if not cookies:
        raise RuntimeError(f"Instagram cookies file is empty or invalid: {cookie_path}")
    best: dict[str, Any] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1200})
        context.add_cookies(cookies)
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(6000)
            for index, image in enumerate(page.locator("img").all()):
                try:
                    if not image.is_visible():
                        continue
                    box = image.bounding_box()
                    if not box:
                        continue
                    src = clean_text(image.get_attribute("src") or "")
                    if not src.startswith("http"):
                        continue
                    area = float(box.get("width") or 0) * float(box.get("height") or 0)
                    if area < 40000:
                        continue
                    if area > float(best.get("area") or 0):
                        best = {
                            "src": src,
                            "alt": clean_text(image.get_attribute("alt") or "", max_len=500),
                            "width": box.get("width"),
                            "height": box.get("height"),
                            "area": area,
                            "index": index,
                            "pageUrl": page.url,
                        }
                except Exception:
                    continue
        finally:
            context.close()
            browser.close()
    if not best:
        raise RuntimeError("No visible large Instagram image found")
    return best


def enrich_candidates(
    candidates: list[dict[str, Any]],
    cookie_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enriched: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    if candidates and not cookie_path.exists():
        for candidate in candidates:
            blocked.append({**candidate, "status": "blocked", "reason": "cookie_file_missing", "cookiePath": str(cookie_path)})
        return enriched, blocked
    client = InstagramAccountSearchClient(cookie_path, headless=True, max_scrolls=0, delay_seconds=0)
    for candidate in candidates:
        url = clean_text(candidate.get("url"))
        try:
            raw = client.candidate_from_ytdlp(url)
            raw["shortcode"] = candidate.get("shortcode") or shortcode_from_url(raw.get("url") or url)[1]
            raw["manualDiscovery"] = {
                "workflow": "google_lens_ins_filter",
                "source": "google_lens",
                "sourceQuery": "",
                "lensRank": candidate.get("rank"),
                "lensTitle": candidate.get("lensTitle"),
                "lensDomain": candidate.get("lensDomain"),
                "sourcePage": candidate.get("sourcePage"),
                "lensThumbnailUrl": candidate.get("lensThumbnailUrl"),
                "seedId": candidate.get("seedId"),
                "seedKeyword": candidate.get("seedKeyword"),
                "seedRank": candidate.get("seedRank"),
                "seedImagePath": candidate.get("seedImagePath") or candidate.get("seedLocalImagePath"),
                "seedSourceUrl": candidate.get("seedSourceUrl"),
                "seedTitle": candidate.get("seedTitle"),
                "seedLensRunDir": candidate.get("seedLensRunDir"),
            }
            if not clean_text(raw.get("thumbnail") or raw.get("displayUrl") or raw.get("imageUrl")):
                try:
                    page_media = fetch_instagram_page_media(url, cookie_path)
                    raw["thumbnail"] = page_media["src"]
                    raw["displayUrl"] = page_media["src"]
                    raw["imageUrl"] = page_media["src"]
                    raw["media_type"] = raw.get("media_type") or "image"
                    raw["type"] = raw.get("type") or "image"
                    raw["raw_source"] = {**dict(raw.get("raw_source") or {}), "page_media_fallback": page_media}
                    raw["manualDiscovery"]["pageMediaFallback"] = {
                        "used": True,
                        "width": page_media.get("width"),
                        "height": page_media.get("height"),
                        "pageUrl": page_media.get("pageUrl"),
                    }
                except Exception as media_exc:
                    raw["manualDiscovery"]["pageMediaFallback"] = {
                        "used": False,
                        "error": clean_text(media_exc, max_len=300),
                    }
            reason = metadata_block_reason(raw)
            if reason:
                blocked.append({**candidate, "status": "blocked", "reason": reason, "raw": raw})
                continue
            enriched.append(raw)
        except Exception as exc:
            blocked.append({**candidate, "status": "blocked", "reason": "metadata_fetch_failed", "error": clean_text(exc, max_len=400)})
    return enriched, blocked


def key_for_item(item: dict[str, Any]) -> str:
    return clean_text(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url") or item.get("permalink") or item.get("upsertKey")).lower()


def run_ins_filters(
    enriched: list[dict[str, Any]],
    *,
    min_likes: int,
    min_comments: int,
    engagement_top_n: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    rules = load_ins_rules()
    variant = resolve_pipeline_variant()
    normalized = normalize_candidates(enriched, rules)
    media_passed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in normalized:
        if passes_media_policy(item, rules):
            media_passed.append(item)
        else:
            blocked.append({**item, "googleLensInsFilter": {"rejectReason": "media_policy_failed"}})
    engagement_passed, engagement_blocked = apply_engagement_gate(
        media_passed,
        min_likes=min_likes,
        min_comments=min_comments,
        top_n=engagement_top_n,
    )
    blocked.extend(engagement_blocked)
    approved, audit_stats = audit_candidates(engagement_passed, rules, variant)
    approved = [{**item, "pushObject": "ALL"} for item in approved]
    approved_keys = {key_for_item(item) for item in approved}
    for item in engagement_passed:
        if key_for_item(item) not in approved_keys:
            blocked.append({**item, "googleLensInsFilter": {"rejectReason": "not_approved_after_audit"}})
    approved.sort(key=lambda item: (engagement_score(item), -int((item.get("manualDiscovery") or {}).get("lensRank") or 9999)), reverse=True)
    stats = {
        "variant": variant,
        "normalized": len(normalized),
        "mediaPassed": len(media_passed),
        "mediaBlocked": len(normalized) - len(media_passed),
        "engagementGate": {
            "minLikes": min_likes,
            "minComments": min_comments,
            "topN": engagement_top_n,
            "passed": len(engagement_passed),
            "blocked": len(engagement_blocked),
        },
        "audit": audit_stats,
        "approved": len(approved),
    }
    return approved, blocked, stats


def write_approved_markdown(path: Path, approved: list[dict[str, Any]]) -> None:
    lines = ["# Google Lens Instagram Approved", ""]
    if not approved:
        lines.append("No Instagram posts passed the current filters.")
    for index, item in enumerate(approved, 1):
        summary = summarize_item(item, index)
        manual = item.get("manualDiscovery") if isinstance(item.get("manualDiscovery"), dict) else {}
        lines.extend(
            [
                f"## {index}. {summary.get('url')}",
                f"- Author: {summary.get('author') or ''}",
                f"- Likes/comments: {summary.get('likes') or 0}/{summary.get('comments') or 0}",
                f"- Heat: {summary.get('heat') or 0}",
                f"- Media type: {summary.get('mediaType') or ''}",
                f"- Primary product: {summary.get('primaryProduct') or ''}",
                f"- Lens rank: {manual.get('lensRank') or ''}",
                f"- Seed: {manual.get('seedKeyword') or ''} #{manual.get('seedRank') or ''}",
                f"- Caption: {summary.get('caption') or ''}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def relative_or_absolute(path: Path) -> str:
    try:
        return path.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract Instagram permalinks from a Google Lens run and pass them through existing INS filters.")
    parser.add_argument("--lens-run-dir", type=Path, required=True, help="Directory containing all_visual_matches.json or lens_results_attr.json.")
    parser.add_argument("--matches-json", type=Path, default=None, help="Optional explicit Lens matches JSON path.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory; defaults to --lens-run-dir.")
    parser.add_argument("--cookie-file", type=Path, default=None, help="Instagram Netscape cookie file; defaults to INS_MANUAL_ACCOUNT_COOKIES or www.instagram.com_cookies.txt.")
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument("--min-likes", type=int, default=DEFAULT_MIN_LIKES)
    parser.add_argument("--min-comments", type=int, default=DEFAULT_MIN_COMMENTS)
    parser.add_argument("--engagement-top-n", type=int, default=DEFAULT_ENGAGEMENT_TOP_N)
    return parser.parse_args()


def main() -> int:
    env = load_env()
    args = parse_args()
    lens_run_dir = args.lens_run_dir if args.lens_run_dir.is_absolute() else BASE_DIR / args.lens_run_dir
    output_dir = args.output_dir if args.output_dir else lens_run_dir
    if not output_dir.is_absolute():
        output_dir = BASE_DIR / output_dir
    matches_path = args.matches_json
    if matches_path is None:
        all_matches_path = lens_run_dir / "all_visual_matches.json"
        matches_path = all_matches_path if all_matches_path.exists() else lens_run_dir / "lens_results_attr.json"
    if not matches_path.is_absolute():
        matches_path = BASE_DIR / matches_path
    cookie_path = args.cookie_file
    if cookie_path is None:
        cookie_path = Path(os.environ.get("INS_MANUAL_ACCOUNT_COOKIES") or env.get("INS_MANUAL_ACCOUNT_COOKIES") or DEFAULT_ACCOUNT_COOKIE)
    if not cookie_path.is_absolute():
        cookie_path = BASE_DIR / cookie_path

    payload = load_json(matches_path)
    candidates = extract_instagram_candidates(payload, max_candidates=max(1, args.max_candidates))
    enriched, metadata_blocked = enrich_candidates(candidates, cookie_path)
    approved, filter_blocked, filter_stats = run_ins_filters(
        enriched,
        min_likes=max(0, args.min_likes),
        min_comments=max(0, args.min_comments),
        engagement_top_n=max(1, args.engagement_top_n),
    )
    blocked = [*metadata_blocked, *filter_blocked]

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "instagramCandidates": output_dir / "instagram_candidates.json",
        "instagramEnriched": output_dir / "instagram_enriched.json",
        "instagramBlocked": output_dir / "instagram_blocked.json",
        "instagramApproved": output_dir / "instagram_approved.json",
        "instagramApprovedMarkdown": output_dir / "instagram_approved.md",
        "instagramFilterReport": output_dir / "instagram_filter_report.json",
    }
    write_json(paths["instagramCandidates"], candidates)
    write_json(paths["instagramEnriched"], enriched)
    write_json(paths["instagramBlocked"], blocked)
    write_json(paths["instagramApproved"], approved)
    write_approved_markdown(paths["instagramApprovedMarkdown"], approved)
    report = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "workflow": "google_lens_instagram_filter",
        "writesFeishu": False,
        "pushesFeishu": False,
        "importsEagle": False,
        "matchesPath": relative_or_absolute(matches_path),
        "lensRunDir": relative_or_absolute(lens_run_dir),
        "maxCandidates": max(1, args.max_candidates),
        "instagramCandidateCount": len(candidates),
        "enrichedCount": len(enriched),
        "blockedCount": len(blocked),
        "approvedCount": len(approved),
        "cookiePath": relative_or_absolute(cookie_path),
        "filterStats": filter_stats,
        "paths": {key: relative_or_absolute(path) for key, path in paths.items()},
    }
    write_json(paths["instagramFilterReport"], report)
    print(f"Google Lens INS candidates: {len(candidates)}", flush=True)
    print(f"Enriched: {len(enriched)}; approved: {len(approved)}; blocked: {len(blocked)}", flush=True)
    print(f"Approved markdown: {paths['instagramApprovedMarkdown']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
