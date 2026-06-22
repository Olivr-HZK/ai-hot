from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
BASE_DIR = SKILL_DIR.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
MANUAL_DIR = SCRIPTS_DIR / "manual"
INSTAGRAM_DIR = SCRIPTS_DIR / "instagram"

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(MANUAL_DIR))
sys.path.insert(0, str(INSTAGRAM_DIR))

import filter_instagram_matches as ins_filter
from env_utils import load_env
from instagram.ins_rules import load_ins_rules
from manual.ins_keyword_discovery import DEFAULT_ACCOUNT_COOKIE
from visual_dedupe import apply_visual_dedupe
from x_safety_review import apply_x_image_safety_review
from x_team_product_review import apply_x_team_product_review


DEFAULT_MAX_KEYWORDS = 5
DEFAULT_IMAGES_PER_KEYWORD = 30
DEFAULT_SEEDS_PER_KEYWORD = 3
DEFAULT_LENS_CANDIDATES = 100
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_CAPTCHA_WAIT_SECONDS = 300
DEFAULT_MIN_LIKES = 500
DEFAULT_MIN_COMMENTS = 10
DEFAULT_ENGAGEMENT_TOP_N = 100
MIN_LENS_IMAGE_BYTES = 20_000
MIN_LENS_IMAGE_SIDE = 300
RUN_ROOT = BASE_DIR / "skill_runs" / "google_lens_eagle_import" / "keyword_lens_runs"
PROFILE_DIR = BASE_DIR / "skill_runs" / "browser_profiles" / "google_images_keyword_lens"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
GOOGLE_UI_TITLE_MARKERS = [
    "google",
    "sign in",
    "settings",
    "tools",
    "images",
    "videos",
    "news",
    "maps",
    "shopping",
    "accessibility",
    "help",
    "feedback",
    "关闭",
    "无障碍",
    "设置",
    "工具",
    "登录",
    "图片",
    "首页",
]


class GoogleVerificationRequired(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean_text(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_list(path: Path) -> list[Any]:
    if not path.exists():
        return []
    payload = load_json(path)
    return payload if isinstance(payload, list) else []


def absolute_path(value: Path, base: Path = BASE_DIR) -> Path:
    return value if value.is_absolute() else base / value


def relative_or_absolute(path: Path) -> str:
    try:
        return path.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return str(path)


def seed_local_image_path(seed: dict[str, Any]) -> Path:
    google_images = seed.get("googleImages") if isinstance(seed.get("googleImages"), dict) else {}
    for raw_path in (
        seed.get("localImagePath"),
        seed.get("localImageRelativePath"),
        google_images.get("localImagePath"),
        google_images.get("localImageRelativePath"),
    ):
        text = clean_text(raw_path)
        if text:
            return absolute_path(Path(text))
    return Path()


def prepare_lens_upload_image(seed: dict[str, Any], seed_dir: Path) -> tuple[Path, Path]:
    source = seed_local_image_path(seed)
    if not source.exists():
        return source, Path()
    suffix = source.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
        suffix = ".jpg"
    upload_path = seed_dir / f"upload{suffix}"
    if source.resolve() != upload_path.resolve():
        shutil.copyfile(source, upload_path)
    return source, upload_path


def save_page_debug_artifacts(page: Any, output_dir: Path, prefix: str) -> None:
    try:
        (output_dir / f"{prefix}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        page.screenshot(path=str(output_dir / f"{prefix}.png"), full_page=True)
    except Exception:
        pass


def stable_id(*parts: Any) -> str:
    joined = "\n".join(clean_text(part) for part in parts if part not in (None, ""))
    return hashlib.sha1(joined.encode("utf-8", errors="ignore")).hexdigest()[:16]


def safe_slug(value: str, fallback: str = "item") -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    if not text:
        text = fallback
    return f"{text[:50]}-{stable_id(value)[:8]}"


def domain_from_url(value: Any) -> str:
    try:
        return urlparse(str(value or "")).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def is_google_domain(domain: str) -> bool:
    domain = domain.lower().removeprefix("www.")
    return (
        domain.startswith("google.")
        or ".google." in domain
        or domain == "gstatic.com"
        or domain.endswith(".gstatic.com")
        or domain == "googleusercontent.com"
        or domain.endswith(".googleusercontent.com")
    )


def is_google_search_page_url(value: Any) -> bool:
    parsed = urlparse(str(value or ""))
    domain = parsed.netloc.lower().removeprefix("www.")
    return domain == "google.com" or domain.endswith(".google.com")


def is_probably_image_fetch_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if text.startswith("data:image/"):
        return True
    if not text.startswith(("http://", "https://")):
        return False
    parsed = urlparse(text)
    domain = parsed.netloc.lower()
    if parsed.path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")):
        return True
    return any(marker in domain for marker in ["gstatic.com", "googleusercontent.com", "fbcdn.net", "cdninstagram.com", "twimg.com", "pinimg.com"])


def is_google_ui_title(value: Any) -> bool:
    text = clean_text(value).lower()
    if not text:
        return False
    return any(marker in text for marker in GOOGLE_UI_TITLE_MARKERS) and len(text) <= 80


def first_http(values: list[Any]) -> str:
    for value in values:
        text = clean_google_result_url(value)
        if text.startswith(("http://", "https://", "data:image/")):
            return text
    return ""


def decoded_text(value: Any) -> str:
    text = str(value or "").strip()
    for _ in range(3):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    return text


def clean_google_result_url(value: Any, preferred_params: list[str] | None = None) -> str:
    text = decoded_text(value)
    if not text:
        return ""
    if text.startswith("data:image/"):
        return text
    if text.startswith("//"):
        text = f"https:{text}"
    if text.startswith("/"):
        text = f"https://www.google.com{text}"
    if not text.startswith(("http://", "https://")):
        return ""

    params = preferred_params or ["imgurl", "imgrefurl", "url", "q"]
    parsed = urlparse(text)
    query = parse_qs(parsed.query)
    for key in params:
        for raw in query.get(key, []):
            nested = clean_google_result_url(raw, preferred_params=["url", "q"])
            if nested.startswith(("http://", "https://")):
                return nested
    return text


def clean_source_url(value: Any) -> str:
    return clean_google_result_url(value, preferred_params=["imgrefurl", "url", "q"])


def clean_image_url(value: Any) -> str:
    return clean_google_result_url(value, preferred_params=["imgurl", "url", "q"])


def normalize_google_image_candidate(row: dict[str, Any], keyword: str, rank: int, keyword_rank: int) -> dict[str, Any] | None:
    source_url = first_http(
        [
            clean_source_url(row.get("sourceUrl")),
            clean_source_url(row.get("pageUrl")),
            clean_source_url(row.get("contextUrl")),
            clean_source_url(row.get("imageContextUrl")),
            clean_source_url(row.get("href")),
        ]
    )
    image_url = first_http(
        [
            clean_image_url(row.get("imageUrl")),
            clean_image_url(row.get("originalImageUrl")),
            clean_image_url(row.get("imgUrl")),
            clean_image_url(row.get("fullSizeUrl")),
            clean_image_url(row.get("href")),
        ]
    )
    thumbnail_url = first_http(
        [
            row.get("thumbnailUrl"),
            row.get("thumbnail"),
            row.get("src"),
            row.get("currentSrc"),
            row.get("dataSrc"),
            image_url,
        ]
    )
    if source_url and is_google_domain(domain_from_url(source_url)):
        source_url = ""
    if image_url and (is_google_search_page_url(image_url) or not is_probably_image_fetch_url(image_url)):
        image_url = ""
    if thumbnail_url and (is_google_search_page_url(thumbnail_url) or not is_probably_image_fetch_url(thumbnail_url)):
        thumbnail_url = ""
    if not (image_url or thumbnail_url):
        return None
    title = clean_text(
        row.get("title")
        or row.get("alt")
        or row.get("ariaLabel")
        or row.get("text")
        or row.get("caption")
        or keyword,
        max_len=500,
    )
    if is_google_ui_title(title):
        title = keyword
    candidate_id = stable_id(keyword, source_url, image_url, thumbnail_url, rank)
    return {
        "id": f"gimg_{candidate_id}",
        "keyword": keyword,
        "keywordRank": keyword_rank,
        "rank": rank,
        "title": title,
        "sourceUrl": source_url,
        "imageUrl": image_url,
        "thumbnailUrl": thumbnail_url,
        "domain": domain_from_url(source_url or image_url or thumbnail_url),
        "status": "discovered",
        "raw": row,
    }


def extract_google_image_candidates_from_rows(
    rows: list[dict[str, Any]],
    keyword: str,
    limit: int,
    keyword_rank: int = 1,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        rank = int(row.get("rank") or row_index)
        candidate = normalize_google_image_candidate(row, keyword, rank, keyword_rank)
        if not candidate:
            continue
        key = clean_text(candidate.get("sourceUrl") or "") + "\n" + clean_text(candidate.get("imageUrl") or candidate.get("thumbnailUrl") or "")
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
        if len(candidates) >= max(1, limit):
            break
    return candidates


def extract_google_image_candidates_from_html(
    html: str,
    keyword: str,
    limit: int,
    keyword_rank: int = 1,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, match in enumerate(re.finditer(r"imgurl=([^&\"'<>]+).*?imgrefurl=([^&\"'<>]+)", html or "", re.IGNORECASE), 1):
        rows.append(
            {
                "rank": index,
                "imageUrl": match.group(1),
                "sourceUrl": match.group(2),
                "title": keyword,
            }
        )
    for index, match in enumerate(re.finditer(r"https?:\\?/\\?/[^\"'<> ]+\.(?:jpg|jpeg|png|webp)(?:[^\"'<> ]*)?", html or "", re.IGNORECASE), len(rows) + 1):
        url = match.group(0).replace("\\/", "/")
        rows.append({"rank": index, "imageUrl": url, "thumbnailUrl": url, "title": keyword})
        if len(rows) >= limit * 3:
            break
    return extract_google_image_candidates_from_rows(rows, keyword, limit, keyword_rank)


def candidate_to_review_item(candidate: dict[str, Any]) -> dict[str, Any]:
    media_url = first_http([candidate.get("imageUrl"), candidate.get("thumbnailUrl")])
    text = clean_text(
        " ".join(
            part
            for part in [
                candidate.get("title"),
                candidate.get("keyword"),
                candidate.get("domain"),
                candidate.get("sourceUrl"),
            ]
            if part
        ),
        max_len=1200,
    )
    return {
        "id": candidate.get("id"),
        "sourcePlatform": "google_images",
        "hotspotPlatform": "google_images",
        "platform": "google_images",
        "searchQuery": candidate.get("keyword"),
        "search_term": candidate.get("keyword"),
        "keyword": candidate.get("keyword"),
        "keywordRank": candidate.get("keywordRank"),
        "rank": candidate.get("rank"),
        "title": candidate.get("title") or candidate.get("keyword"),
        "text": text,
        "desc": text,
        "summary": text,
        "hotspotIntro": text,
        "hotspotUrl": candidate.get("sourceUrl") or candidate.get("imageUrl") or candidate.get("thumbnailUrl"),
        "webVideoUrl": candidate.get("sourceUrl") or candidate.get("imageUrl") or candidate.get("thumbnailUrl"),
        "mediaType": "image",
        "type": "image",
        "mediaUrls": [media_url] if media_url else [],
        "imageUrl": media_url,
        "thumbnailUrl": candidate.get("thumbnailUrl") or media_url,
        "displayUrl": media_url,
        "localImagePath": candidate.get("localImagePath"),
        "downloadedBytes": candidate.get("downloadedBytes"),
        "imageWidth": candidate.get("imageWidth"),
        "imageHeight": candidate.get("imageHeight"),
        "lensSeedEligible": candidate.get("lensSeedEligible"),
        "lensSeedBlockedReason": candidate.get("lensSeedBlockedReason"),
        "sourceUrl": candidate.get("sourceUrl"),
        "domain": candidate.get("domain"),
        "heatValue": max(1, 10000 - int(candidate.get("keywordRank") or 1) * 100 - int(candidate.get("rank") or 999)),
        "googleImages": candidate,
    }


def limit_reviewable_per_keyword(items: list[dict[str, Any]], per_keyword: int) -> list[dict[str, Any]]:
    if per_keyword <= 0:
        return items
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[clean_text(item.get("keyword") or item.get("searchQuery") or "unknown")].append(item)
    limited: list[dict[str, Any]] = []
    for keyword in sorted(grouped):
        ranked = sorted(grouped[keyword], key=lambda entry: int(entry.get("rank") or 9999))
        limited.extend(ranked[:per_keyword])
    return sorted(limited, key=lambda entry: (int(entry.get("keywordRank") or 999), int(entry.get("rank") or 9999)))


def decode_data_uri(value: str) -> tuple[bytes, str]:
    header, encoded = value.split(",", 1)
    mime = header.split(";", 1)[0].replace("data:", "") or "image/jpeg"
    suffix = mimetypes.guess_extension(mime) or ".jpg"
    return base64.b64decode(encoded), suffix


def extension_from_response(url: str, content_type: str = "") -> str:
    suffix = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    if suffix:
        return ".jpg" if suffix == ".jpe" else suffix
    path_suffix = Path(urlparse(url).path).suffix.lower()
    if path_suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return path_suffix
    return ".jpg"


def is_image_content_type(value: str) -> bool:
    return value.lower().split(";", 1)[0].strip().startswith("image/")


def image_dimensions(content: bytes) -> tuple[int, int]:
    if content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24:
        return int.from_bytes(content[16:20], "big"), int.from_bytes(content[20:24], "big")
    if content.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(content):
            if content[index] != 0xFF:
                index += 1
                continue
            marker = content[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(content):
                break
            length = int.from_bytes(content[index : index + 2], "big")
            if length < 2:
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and index + 7 < len(content):
                return int.from_bytes(content[index + 5 : index + 7], "big"), int.from_bytes(content[index + 3 : index + 5], "big")
            index += length
    if content.startswith(b"RIFF") and len(content) >= 30 and content[8:12] == b"WEBP":
        if content[12:16] == b"VP8X" and len(content) >= 30:
            width = 1 + int.from_bytes(content[24:27], "little")
            height = 1 + int.from_bytes(content[27:30], "little")
            return width, height
    return 0, 0


def lens_ready_reason(candidate: dict[str, Any]) -> str:
    image_url = clean_text(candidate.get("imageUrl"))
    if not image_url.startswith(("http://", "https://")):
        return "missing_original_http_image_url"
    bytes_count = int(candidate.get("downloadedBytes") or 0)
    if bytes_count and bytes_count < MIN_LENS_IMAGE_BYTES:
        return "image_file_too_small_for_lens"
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
    width = int(candidate.get("imageWidth") or raw.get("naturalWidth") or 0)
    height = int(candidate.get("imageHeight") or raw.get("naturalHeight") or 0)
    if width and height and (width < MIN_LENS_IMAGE_SIDE or height < MIN_LENS_IMAGE_SIDE):
        return "image_dimensions_too_small_for_lens"
    return ""


def is_lens_ready_candidate(candidate: dict[str, Any]) -> bool:
    return candidate.get("downloadStatus") == "downloaded" and not lens_ready_reason(candidate)


def seed_item_is_lens_ready(item: dict[str, Any]) -> bool:
    candidate = item.get("googleImages") if isinstance(item.get("googleImages"), dict) else item
    local_path = seed_local_image_path(item)
    return is_lens_ready_candidate(candidate) and local_path.exists()


def download_google_image_candidate(candidate: dict[str, Any], output_dir: Path, timeout_seconds: int) -> dict[str, Any]:
    updated = dict(candidate)
    url = clean_text(candidate.get("imageUrl"))
    if not url.startswith(("http://", "https://")):
        updated.update({"downloadStatus": "failed", "downloadError": "missing_original_http_image_url", "lensSeedEligible": False})
        return updated
    if not url:
        updated.update({"downloadStatus": "failed", "downloadError": "missing_image_url"})
        return updated
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=max(5, timeout_seconds))
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if not is_image_content_type(content_type):
            raise RuntimeError(f"non-image response content-type: {content_type or 'unknown'}")
        content = response.content
        suffix = extension_from_response(url, content_type)
        if len(content) < 512:
            raise RuntimeError("image response too small")
        width, height = image_dimensions(content)
        keyword_dir = output_dir / safe_slug(clean_text(candidate.get("keyword") or "keyword"))
        keyword_dir.mkdir(parents=True, exist_ok=True)
        file_path = keyword_dir / f"{int(candidate.get('rank') or 0):03d}_{candidate.get('id') or stable_id(url)}{suffix}"
        file_path.write_bytes(content)
        updated.update(
            {
                "downloadStatus": "downloaded",
                "localImagePath": str(file_path),
                "localImageRelativePath": relative_or_absolute(file_path),
                "downloadedAt": now_iso(),
                "downloadedBytes": len(content),
                "imageWidth": width,
                "imageHeight": height,
            }
        )
        reason = lens_ready_reason(updated)
        updated["lensSeedEligible"] = not reason
        if reason:
            updated["lensSeedBlockedReason"] = reason
    except Exception as exc:
        updated.update({"downloadStatus": "failed", "downloadError": clean_text(exc, max_len=300), "lensSeedEligible": False})
    return updated


def is_google_verification_page(page: Any) -> bool:
    try:
        url = (page.url or "").lower()
        if "google.com/sorry" in url or "/sorry/" in url:
            return True
        body = page.locator("body").inner_text(timeout=1500).lower()
    except Exception:
        return False
    markers = [
        "unusual traffic",
        "not a robot",
        "captcha",
        "recaptcha",
        "confirm this search was made by a human",
        "please complete the following challenge",
    ]
    return any(marker in body for marker in markers)


def wait_for_google_verification_if_needed(page: Any, state: dict[str, Any], wait_seconds: int) -> None:
    if not is_google_verification_page(page):
        return
    if int(state.get("attempts") or 0) >= 1:
        state["degraded"] = True
        state["reason"] = "repeated_google_verification"
        raise GoogleVerificationRequired("Google verification appeared more than once")
    state["attempts"] = int(state.get("attempts") or 0) + 1
    state["firstSeenAt"] = now_iso()
    print("Google verification page detected. Complete it in the visible browser; waiting once for manual handling.", flush=True)
    deadline = time.time() + max(10, wait_seconds)
    while time.time() < deadline:
        page.wait_for_timeout(2500)
        if not is_google_verification_page(page):
            state["resolvedAt"] = now_iso()
            return
    state["degraded"] = True
    state["reason"] = "google_verification_timeout"
    raise GoogleVerificationRequired("Google verification was not resolved before timeout")


def lens_unavailable_reason(page: Any) -> str:
    try:
        body = page.locator("body").inner_text(timeout=2000).lower()
    except Exception:
        return ""
    expired_markers = [
        "视觉搜索的内容已过期",
        "visual search has expired",
        "visual search content has expired",
        "this visual search has expired",
        "search content has expired",
    ]
    if any(marker in body for marker in expired_markers):
        return "google_lens_visual_search_expired"
    missing_markers = [
        "图片未找到",
        "image not found",
        "please reupload",
        "请重新上传图片",
        "not associated with your account",
    ]
    if any(marker in body for marker in missing_markers):
        return "google_lens_image_not_found"
    return ""


def accept_google_consent_if_present(page: Any) -> None:
    for label in ["Accept all", "I agree", "Reject all"]:
        try:
            page.get_by_role("button", name=re.compile(label, re.IGNORECASE)).click(timeout=1500)
            page.wait_for_timeout(1000)
            return
        except Exception:
            continue


def scrape_google_images_keyword(
    context: Any,
    keyword: str,
    keyword_rank: int,
    run_dir: Path,
    images_per_keyword: int,
    timeout_seconds: int,
    verification_state: dict[str, Any],
    captcha_wait_seconds: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    page = context.new_page()
    page_dir = run_dir / "google_images_pages" / f"{keyword_rank:03d}_{safe_slug(keyword)}"
    page_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://www.google.com/search?udm=2&tbm=isch&q={quote_plus(keyword)}"
    report: dict[str, Any] = {
        "keyword": keyword,
        "keywordRank": keyword_rank,
        "url": url,
        "status": "started",
        "startedAt": now_iso(),
        "candidateCount": 0,
    }
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=max(10, timeout_seconds) * 1000)
        accept_google_consent_if_present(page)
        wait_for_google_verification_if_needed(page, verification_state, captcha_wait_seconds)
        for _ in range(5):
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(900)
            if len(page.locator("img").all()) >= images_per_keyword:
                break
        page.screenshot(path=str(page_dir / "search.png"), full_page=True)
        html = page.content()
        (page_dir / "search.html").write_text(html, encoding="utf-8")
        rows = page.evaluate(
            """
            () => Array.from(document.images)
              .filter((img) => {
                const src = img.currentSrc || img.src || '';
                const width = img.naturalWidth || img.width || 0;
                const height = img.naturalHeight || img.height || 0;
                return src && width >= 80 && height >= 80;
              })
              .map((img, index) => {
              const a = img.closest('a[href]');
              const container = img.closest('[data-ved], div');
              return {
                rank: index + 1,
                href: a ? (a.href || '') : '',
                sourceUrl: a ? (a.href || '') : '',
                title: img.alt || (a ? (a.getAttribute('aria-label') || a.title || a.innerText || '') : '') || (container ? container.innerText || '' : ''),
                thumbnailUrl: img.currentSrc || img.src || '',
                src: img.currentSrc || img.src || '',
                currentSrc: img.currentSrc || img.src || '',
                naturalWidth: img.naturalWidth || img.width || 0,
                naturalHeight: img.naturalHeight || img.height || 0
              };
            })
            """
        )
        candidates = extract_google_image_candidates_from_rows(rows, keyword, images_per_keyword, keyword_rank)
        if len(candidates) < images_per_keyword:
            html_candidates = extract_google_image_candidates_from_html(html, keyword, images_per_keyword, keyword_rank)
            seen = {candidate["id"] for candidate in candidates}
            for candidate in html_candidates:
                if candidate["id"] in seen:
                    continue
                candidates.append(candidate)
                seen.add(candidate["id"])
                if len(candidates) >= images_per_keyword:
                    break
        report.update({"status": "ok", "candidateCount": len(candidates), "finishedAt": now_iso(), "pageDir": relative_or_absolute(page_dir)})
        return candidates, report
    except GoogleVerificationRequired:
        report.update({"status": "degraded", "error": verification_state.get("reason") or "google_verification_required", "finishedAt": now_iso()})
        raise
    except Exception as exc:
        report.update({"status": "failed", "error": clean_text(exc, max_len=500), "finishedAt": now_iso()})
        return [], report
    finally:
        try:
            page.close()
        except Exception:
            pass


def run_seed_reviews(
    downloaded_candidates: list[dict[str, Any]],
    run_dir: Path,
    seeds_per_keyword: int,
    review_pool_per_keyword: int = DEFAULT_IMAGES_PER_KEYWORD,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    reviewable_all = [
        candidate_to_review_item(candidate)
        for candidate in downloaded_candidates
        if is_lens_ready_candidate(candidate)
    ]
    seed_input_blocked = [
        {
            **candidate,
            "seedReviewBlockedReason": lens_ready_reason(candidate) or candidate.get("downloadError") or "not_lens_ready",
        }
        for candidate in downloaded_candidates
        if candidate.get("downloadStatus") == "downloaded" and not is_lens_ready_candidate(candidate)
    ]
    reviewable = limit_reviewable_per_keyword(reviewable_all, max(0, review_pool_per_keyword))
    write_json(run_dir / "seed_review_candidates.json", reviewable)
    write_json(run_dir / "seed_input_blocked.json", seed_input_blocked)
    rules = load_ins_rules()
    product_passed: list[dict[str, Any]] = []
    product_blocked: list[dict[str, Any]] = []
    for index, item in enumerate(reviewable, 1):
        kept, blocked = apply_x_team_product_review([item], rules)
        product_passed.extend(kept)
        product_blocked.extend(blocked)
        write_json(run_dir / "seed_product_passed.json", product_passed)
        write_json(run_dir / "seed_product_blocked.json", product_blocked)
        print(f"  - Seed product review progress {index}/{len(reviewable)}; kept {len(product_passed)}", flush=True)

    safety_passed: list[dict[str, Any]] = []
    safety_blocked: list[dict[str, Any]] = []
    for index, item in enumerate(product_passed, 1):
        kept, blocked = apply_x_image_safety_review([item])
        safety_passed.extend(kept)
        safety_blocked.extend(blocked)
        write_json(run_dir / "seed_safety_passed.json", safety_passed)
        write_json(run_dir / "seed_safety_blocked.json", safety_blocked)
        print(f"  - Seed safety review progress {index}/{len(product_passed)}; kept {len(safety_passed)}", flush=True)
    if not product_passed:
        write_json(run_dir / "seed_safety_passed.json", [])
        write_json(run_dir / "seed_safety_blocked.json", [])

    sorted_safety = sorted(safety_passed, key=lambda item: (int(item.get("keywordRank") or 999), int(item.get("rank") or 9999)))
    visual_kept, visual_deduped = apply_visual_dedupe(sorted_safety, platform="google_images", top_n=max(1, len(sorted_safety)) if sorted_safety else 1)

    per_keyword_count: dict[str, int] = defaultdict(int)
    visual_approved: list[dict[str, Any]] = []
    seed_limit_blocked: list[dict[str, Any]] = []
    for item in sorted(visual_kept, key=lambda entry: (int(entry.get("keywordRank") or 999), int(entry.get("rank") or 9999))):
        keyword = clean_text(item.get("keyword") or item.get("searchQuery"))
        if per_keyword_count[keyword] >= max(1, seeds_per_keyword):
            blocked = dict(item)
            blocked["seedReviewBlockedReason"] = "seed_limit_per_keyword"
            seed_limit_blocked.append(blocked)
            continue
        per_keyword_count[keyword] += 1
        updated = dict(item)
        updated["seedRank"] = per_keyword_count[keyword]
        updated["seedId"] = updated.get("id") or stable_id(keyword, updated.get("rank"), updated.get("hotspotUrl"))
        updated["seedStatus"] = "approved_for_lens"
        visual_approved.append(updated)
    visual_deduped_all = [*visual_deduped, *seed_limit_blocked]
    write_json(run_dir / "seed_visual_approved.json", visual_approved)
    write_json(run_dir / "seed_visual_deduped.json", visual_deduped_all)
    return visual_approved, {
        "reviewable": len(reviewable),
        "reviewableTotal": len(reviewable_all),
        "seedInputBlocked": len(seed_input_blocked),
        "reviewPoolPerKeyword": review_pool_per_keyword,
        "productPassed": len(product_passed),
        "productBlocked": len(product_blocked),
        "safetyPassed": len(safety_passed),
        "safetyBlocked": len(safety_blocked),
        "visualApproved": len(visual_approved),
        "visualDeduped": len(visual_deduped_all),
    }


def platform_from_domain(domain: str) -> str:
    domain = domain.lower().removeprefix("www.")
    if "instagram.com" in domain:
        return "instagram"
    if "tiktok.com" in domain:
        return "tiktok"
    if "youtube.com" in domain or "youtu.be" in domain:
        return "youtube"
    if "pinterest." in domain:
        return "pinterest"
    if "facebook.com" in domain:
        return "facebook"
    if "x.com" in domain or "twitter.com" in domain:
        return "x"
    return domain.split(".", 1)[0] if domain else ""


def normalize_lens_match(row: dict[str, Any], seed: dict[str, Any], rank: int) -> dict[str, Any] | None:
    source_url = first_http([row.get("sourceUrl"), row.get("href"), row.get("url"), row.get("pageUrl")])
    if not source_url:
        return None
    domain = domain_from_url(source_url)
    if is_google_domain(domain):
        return None
    thumbnail_url = first_http([row.get("thumbnailUrl"), row.get("thumbnail"), row.get("src"), row.get("currentSrc")])
    platform = clean_text(row.get("platform")) or platform_from_domain(domain)
    seed_google = seed.get("googleImages") if isinstance(seed.get("googleImages"), dict) else {}
    return {
        "rank": rank,
        "title": clean_text(row.get("title") or row.get("text") or row.get("ariaLabel") or source_url, max_len=500),
        "sourceUrl": source_url,
        "domain": domain,
        "platform": platform,
        "isSocial": platform in {"instagram", "tiktok", "youtube", "pinterest", "facebook", "x"},
        "thumbnailUrl": thumbnail_url,
        "thumbnails": [{"src": thumbnail_url}] if thumbnail_url else [],
        "seedId": seed.get("seedId") or seed.get("id"),
        "seedKeyword": seed.get("keyword") or seed.get("searchQuery"),
        "seedRank": seed.get("seedRank") or seed.get("rank"),
        "seedImagePath": seed.get("localImagePath"),
        "seedLocalImagePath": seed.get("localImagePath"),
        "seedSourceUrl": seed.get("sourceUrl") or seed_google.get("sourceUrl") or seed.get("hotspotUrl"),
        "seedTitle": seed.get("title"),
    }


def extract_lens_matches_from_rows(rows: list[dict[str, Any]], seed: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        match = normalize_lens_match(row, seed, len(matches) + 1)
        if not match:
            continue
        key = canonical_match_key(match.get("sourceUrl"))
        if key in seen:
            continue
        seen.add(key)
        matches.append(match)
        if len(matches) >= max(1, limit):
            break
    return matches


def canonical_match_key(value: Any) -> str:
    url = clean_google_result_url(value)
    if not url:
        return ""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def run_google_lens_for_seed(
    context: Any,
    seed: dict[str, Any],
    run_dir: Path,
    lens_candidates: int,
    timeout_seconds: int,
    verification_state: dict[str, Any],
    captcha_wait_seconds: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seed_id = clean_text(seed.get("seedId") or seed.get("id") or stable_id(seed.get("localImagePath"), seed.get("hotspotUrl")))
    seed_dir = run_dir / "lens_seeds" / f"{int(seed.get('keywordRank') or 0):03d}_{int(seed.get('seedRank') or 0):02d}_{safe_slug(seed_id)}"
    seed_dir.mkdir(parents=True, exist_ok=True)
    write_json(seed_dir / "seed.json", seed)
    source_image_path, upload_image_path = prepare_lens_upload_image(seed, seed_dir)
    report: dict[str, Any] = {
        "seedId": seed_id,
        "seedKeyword": seed.get("keyword") or seed.get("searchQuery"),
        "seedRank": seed.get("seedRank"),
        "status": "started",
        "startedAt": now_iso(),
        "matchCount": 0,
        "seedDir": relative_or_absolute(seed_dir),
        "seedSourceImagePath": relative_or_absolute(source_image_path) if source_image_path else "",
        "lensUploadPath": relative_or_absolute(upload_image_path) if upload_image_path else "",
    }
    if not source_image_path.exists() or not upload_image_path.exists():
        report.update({"status": "failed", "error": "seed_local_image_missing", "finishedAt": now_iso()})
        write_json(seed_dir / "lens_results_attr.json", {"visualMatches": [], "report": report})
        write_json(seed_dir / "all_visual_matches.json", [])
        return [], report

    page = None
    try:
        page = context.new_page()
        page.goto("https://lens.google.com/", wait_until="domcontentloaded", timeout=max(10, timeout_seconds) * 1000)
        accept_google_consent_if_present(page)
        wait_for_google_verification_if_needed(page, verification_state, captcha_wait_seconds)
        inputs = page.locator("input[type=file]")
        count = inputs.count()
        if count < 1:
            raise RuntimeError("Google Lens file input not found")
        inputs.nth(count - 1).set_input_files(str(upload_image_path))
        page.wait_for_timeout(6000)
        wait_for_google_verification_if_needed(page, verification_state, captcha_wait_seconds)
        unavailable_reason = lens_unavailable_reason(page)
        if unavailable_reason:
            raise RuntimeError(unavailable_reason)
        for _ in range(5):
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(1000)
        html = page.content()
        (seed_dir / "lens.html").write_text(html, encoding="utf-8")
        page.screenshot(path=str(seed_dir / "lens.png"), full_page=True)
        rows = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('a[href]')).map((a, index) => {
              const img = a.querySelector('img');
              return {
                rank: index + 1,
                href: a.href || '',
                sourceUrl: a.href || '',
                title: a.getAttribute('aria-label') || a.title || (img && img.alt) || a.innerText || '',
                thumbnailUrl: img ? (img.currentSrc || img.src || '') : '',
                src: img ? (img.currentSrc || img.src || '') : ''
              };
            })
            """
        )
        matches = extract_lens_matches_from_rows(rows, seed, lens_candidates)
        for match in matches:
            match["seedLensRunDir"] = relative_or_absolute(seed_dir)
        report.update({"status": "ok", "matchCount": len(matches), "finishedAt": now_iso(), "lensUrl": page.url})
        write_json(seed_dir / "all_visual_matches.json", matches)
        write_json(
            seed_dir / "lens_results_attr.json",
            {
                "status": "opened-results" if matches else "no-matches",
                "visualMatchesCandidateLimit": lens_candidates,
                "visualMatchesFound": len(matches),
                "visualMatches": matches,
                "seed": seed,
                "report": report,
            },
        )
        return matches, report
    except GoogleVerificationRequired:
        report.update({"status": "degraded", "error": verification_state.get("reason") or "google_verification_required", "finishedAt": now_iso()})
        if page is not None:
            save_page_debug_artifacts(page, seed_dir, "lens_failed")
        write_json(seed_dir / "lens_results_attr.json", {"visualMatches": [], "seed": seed, "report": report})
        write_json(seed_dir / "all_visual_matches.json", [])
        raise
    except Exception as exc:
        report.update({"status": "failed", "error": clean_text(exc, max_len=500), "finishedAt": now_iso()})
        if page is not None:
            save_page_debug_artifacts(page, seed_dir, "lens_failed")
        write_json(seed_dir / "lens_results_attr.json", {"visualMatches": [], "seed": seed, "report": report})
        write_json(seed_dir / "all_visual_matches.json", [])
        return [], report
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass


def aggregate_lens_matches(seed_matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for match in seed_matches:
        key = canonical_match_key(match.get("sourceUrl"))
        if not key:
            continue
        seed_ref = {
            "seedId": match.get("seedId"),
            "seedKeyword": match.get("seedKeyword"),
            "seedRank": match.get("seedRank"),
            "seedImagePath": match.get("seedImagePath") or match.get("seedLocalImagePath"),
            "seedSourceUrl": match.get("seedSourceUrl"),
            "lensRank": match.get("rank"),
        }
        if key not in by_key:
            by_key[key] = {**match, "seedRefs": [seed_ref]}
            continue
        existing = by_key[key]
        refs = existing.setdefault("seedRefs", [])
        refs.append(seed_ref)
    results = list(by_key.values())
    for index, match in enumerate(results, 1):
        match["aggregateRank"] = index
        match["rank"] = int(match.get("rank") or index)
    return results


def run_instagram_stage(
    lens_matches: list[dict[str, Any]],
    run_dir: Path,
    cookie_path: Path,
    min_likes: int,
    min_comments: int,
    engagement_top_n: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = {"visualMatches": lens_matches}
    candidates = ins_filter.extract_instagram_candidates(payload, max_candidates=max(1, len(lens_matches)))
    enriched, metadata_blocked = ins_filter.enrich_candidates(candidates, cookie_path)
    approved, filter_blocked, filter_stats = ins_filter.run_ins_filters(
        enriched,
        min_likes=max(0, min_likes),
        min_comments=max(0, min_comments),
        engagement_top_n=max(1, engagement_top_n),
    )
    blocked = [*metadata_blocked, *filter_blocked]
    paths = {
        "instagramCandidates": run_dir / "instagram_candidates.json",
        "instagramEnriched": run_dir / "instagram_enriched.json",
        "instagramBlocked": run_dir / "instagram_blocked.json",
        "instagramApproved": run_dir / "instagram_approved.json",
        "instagramApprovedMarkdown": run_dir / "instagram_approved.md",
        "instagramFilterReport": run_dir / "instagram_filter_report.json",
    }
    write_json(paths["instagramCandidates"], candidates)
    write_json(paths["instagramEnriched"], enriched)
    write_json(paths["instagramBlocked"], blocked)
    write_json(paths["instagramApproved"], approved)
    ins_filter.write_approved_markdown(paths["instagramApprovedMarkdown"], approved)
    report = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "workflow": "google_images_keyword_lens_instagram_filter",
        "writesFeishu": False,
        "pushesFeishu": False,
        "importsEagle": False,
        "lensMatchCount": len(lens_matches),
        "instagramCandidateCount": len(candidates),
        "enrichedCount": len(enriched),
        "blockedCount": len(blocked),
        "approvedCount": len(approved),
        "cookiePath": relative_or_absolute(cookie_path),
        "filterStats": filter_stats,
        "paths": {key: relative_or_absolute(path) for key, path in paths.items()},
    }
    write_json(paths["instagramFilterReport"], report)
    return approved, report


def write_final_markdown(path: Path, approved: list[dict[str, Any]]) -> None:
    lines = ["# Google Images Keyword Lens Final Approved", ""]
    if not approved:
        lines.append("No Instagram posts passed the current filters.")
    for index, item in enumerate(approved, 1):
        summary = ins_filter.summarize_item(item, index)
        manual = item.get("manualDiscovery") if isinstance(item.get("manualDiscovery"), dict) else {}
        lines.extend(
            [
                f"## {index}. {summary.get('url')}",
                f"- Author: {summary.get('author') or ''}",
                f"- Likes/comments: {summary.get('likes') or 0}/{summary.get('comments') or 0}",
                f"- Heat: {summary.get('heat') or 0}",
                f"- Primary product: {summary.get('primaryProduct') or ''}",
                f"- Seed keyword: {manual.get('seedKeyword') or ''}",
                f"- Seed rank: {manual.get('seedRank') or ''}",
                f"- Lens rank: {manual.get('lensRank') or ''}",
                f"- Caption: {summary.get('caption') or ''}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def load_keywords_from_args(args: argparse.Namespace) -> list[str]:
    raw: list[str] = []
    if args.keywords:
        raw.extend(re.split(r"[\n,]+", args.keywords))
    if args.keywords_file:
        path = absolute_path(args.keywords_file)
        text = path.read_text(encoding="utf-8-sig")
        try:
            payload = json.loads(text)
            if isinstance(payload, list):
                raw.extend(str(item.get("keyword") if isinstance(item, dict) else item) for item in payload)
            else:
                raw.extend(re.split(r"[\n,]+", text))
        except json.JSONDecodeError:
            raw.extend(re.split(r"[\n,]+", text))
    keywords: list[str] = []
    seen: set[str] = set()
    for value in raw:
        keyword = clean_text(value)
        key = keyword.lower()
        if not keyword or key in seen:
            continue
        seen.add(key)
        keywords.append(keyword)
        if len(keywords) >= max(1, args.max_keywords):
            break
    return keywords


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Keyword Google Images seeds -> Google Lens expansion -> local INS filters.")
    parser.add_argument("--keywords", default="", help="Comma or newline separated keywords.")
    parser.add_argument("--keywords-file", type=Path, default=None, help="Text or JSON keyword file.")
    parser.add_argument("--resume-run-dir", type=Path, default=None, help="Resume from an existing run directory that already has Google Images outputs.")
    parser.add_argument("--max-keywords", type=int, default=DEFAULT_MAX_KEYWORDS)
    parser.add_argument("--images-per-keyword", type=int, default=DEFAULT_IMAGES_PER_KEYWORD)
    parser.add_argument("--seeds-per-keyword", type=int, default=DEFAULT_SEEDS_PER_KEYWORD)
    parser.add_argument("--seed-review-pool-per-keyword", type=int, default=DEFAULT_IMAGES_PER_KEYWORD, help="How many downloaded Google Images candidates per keyword enter seed product/safety review; 0 means all.")
    parser.add_argument("--lens-candidates", type=int, default=DEFAULT_LENS_CANDIDATES)
    parser.add_argument("--visible-browser", action="store_true", help="Show Chrome so a human can resolve Google verification once.")
    parser.add_argument("--profile-dir", type=Path, default=PROFILE_DIR)
    parser.add_argument("--output-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--captcha-wait-seconds", type=int, default=DEFAULT_CAPTCHA_WAIT_SECONDS)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--cookie-file", type=Path, default=None)
    parser.add_argument("--min-likes", type=int, default=DEFAULT_MIN_LIKES)
    parser.add_argument("--min-comments", type=int, default=DEFAULT_MIN_COMMENTS)
    parser.add_argument("--engagement-top-n", type=int, default=DEFAULT_ENGAGEMENT_TOP_N)
    return parser.parse_args()


def launch_chrome_context(profile_dir: Path, visible_browser: bool, timeout_seconds: int) -> tuple[Any, Any]:
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=not visible_browser,
            viewport={"width": 1440, "height": 1200},
            accept_downloads=True,
            user_agent=USER_AGENT,
            timeout=max(10, timeout_seconds) * 1000,
        )
    except Exception:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=not visible_browser,
            viewport={"width": 1440, "height": 1200},
            accept_downloads=True,
            user_agent=USER_AGENT,
            timeout=max(10, timeout_seconds) * 1000,
        )
    return pw, context


def keywords_from_run_dir(run_dir: Path) -> list[str]:
    path = run_dir / "keywords.json"
    if not path.exists():
        return []
    payload = load_json(path)
    if not isinstance(payload, list):
        return []
    keywords: list[str] = []
    for item in payload:
        if isinstance(item, dict):
            keyword = clean_text(item.get("keyword") or item.get("term"))
        else:
            keyword = clean_text(item)
        if keyword:
            keywords.append(keyword)
    return keywords


def main() -> int:
    args = parse_args()
    resume_run_dir = absolute_path(args.resume_run_dir) if args.resume_run_dir else None
    if resume_run_dir:
        run_dir = resume_run_dir
        run_id = run_dir.name
        keywords = keywords_from_run_dir(run_dir)
    else:
        keywords = load_keywords_from_args(args)
        run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        output_root = absolute_path(args.output_root)
        run_dir = output_root / run_id
    if not keywords and not resume_run_dir:
        print("No keywords provided. Use --keywords or --keywords-file.", flush=True)
        return 2
    run_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = absolute_path(args.profile_dir)
    env = load_env()
    cookie_path = args.cookie_file or Path(os.environ.get("INS_MANUAL_ACCOUNT_COOKIES") or env.get("INS_MANUAL_ACCOUNT_COOKIES") or DEFAULT_ACCOUNT_COOKIE)
    cookie_path = absolute_path(cookie_path)

    existing_manifest = {}
    if resume_run_dir and (run_dir / "run_manifest.json").exists():
        loaded_manifest = load_json(run_dir / "run_manifest.json")
        existing_manifest = loaded_manifest if isinstance(loaded_manifest, dict) else {}
    manifest = {
        **existing_manifest,
        "schemaVersion": 1,
        "workflow": "google_images_keyword_lens_pipeline",
        "runId": run_id,
        "startedAt": existing_manifest.get("startedAt") or now_iso(),
        "runDir": relative_or_absolute(run_dir),
        "writesFeishu": False,
        "pushesFeishu": False,
        "importsEagle": False,
        "resumedAt": now_iso() if resume_run_dir else existing_manifest.get("resumedAt", ""),
        "parameters": {
            "maxKeywords": args.max_keywords,
            "imagesPerKeyword": args.images_per_keyword,
            "seedsPerKeyword": args.seeds_per_keyword,
            "seedReviewPoolPerKeyword": args.seed_review_pool_per_keyword,
            "lensCandidates": args.lens_candidates,
            "visibleBrowser": args.visible_browser,
            "captchaWaitSeconds": args.captcha_wait_seconds,
            "timeoutSeconds": args.timeout_seconds,
            "profileDir": relative_or_absolute(profile_dir),
            "cookiePath": relative_or_absolute(cookie_path),
            "resumeRunDir": relative_or_absolute(resume_run_dir) if resume_run_dir else "",
        },
    }
    write_json(run_dir / "run_manifest.json", manifest)
    if keywords:
        write_json(run_dir / "keywords.json", [{"rank": index, "keyword": keyword} for index, keyword in enumerate(keywords, 1)])

    stage_report: dict[str, Any] = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "degraded": False,
        "degradedReason": "",
        "keywordCount": len(keywords),
        "googleImagesRaw": 0,
        "googleImagesDownloaded": 0,
        "lensMatchCount": 0,
        "instagramApprovedCount": 0,
    }
    verification_state: dict[str, Any] = {"attempts": 0, "degraded": False}
    google_candidates: list[dict[str, Any]] = []
    downloaded_candidates: list[dict[str, Any]] = []
    google_fetch_report: list[dict[str, Any]] = []
    lens_reports: list[dict[str, Any]] = []
    all_seed_matches: list[dict[str, Any]] = []
    pw = None
    context = None

    try:
        if resume_run_dir:
            google_candidates = load_json(run_dir / "google_images_raw_candidates.json")
            downloaded_candidates = load_json(run_dir / "google_images_downloaded.json")
            report_path = run_dir / "google_images_fetch_report.json"
            google_fetch_report = load_json(report_path) if report_path.exists() else []
            print(f"Resuming from Google Images outputs: {run_dir}", flush=True)
        else:
            google_candidates = []
            downloaded_candidates = []
            google_fetch_report = []
        if not resume_run_dir:
            pw, context = launch_chrome_context(profile_dir, args.visible_browser, args.timeout_seconds)
            try:
                for keyword_rank, keyword in enumerate(keywords, 1):
                    try:
                        candidates, report = scrape_google_images_keyword(
                            context,
                            keyword,
                            keyword_rank,
                            run_dir,
                            max(1, args.images_per_keyword),
                            max(5, args.timeout_seconds),
                            verification_state,
                            max(10, args.captcha_wait_seconds),
                        )
                    except GoogleVerificationRequired as exc:
                        google_fetch_report.append(
                            {
                                "keyword": keyword,
                                "keywordRank": keyword_rank,
                                "status": "degraded",
                                "error": clean_text(exc, max_len=300),
                            }
                        )
                        stage_report["degraded"] = True
                        stage_report["degradedReason"] = verification_state.get("reason") or "google_verification_required"
                        break
                    google_fetch_report.append(report)
                    google_candidates.extend(candidates)
                    for candidate in candidates:
                        downloaded_candidates.append(
                            download_google_image_candidate(candidate, run_dir / "google_images_downloads", max(5, args.timeout_seconds))
                        )
                    write_json(run_dir / "google_images_raw_candidates.json", google_candidates)
                    write_json(run_dir / "google_images_downloaded.json", downloaded_candidates)
                    write_json(run_dir / "google_images_fetch_report.json", google_fetch_report)
            finally:
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        pass
                    context = None
                if pw is not None:
                    try:
                        pw.stop()
                    except Exception:
                        pass
                    pw = None

        write_json(run_dir / "google_images_raw_candidates.json", google_candidates)
        write_json(run_dir / "google_images_downloaded.json", downloaded_candidates)
        write_json(run_dir / "google_images_fetch_report.json", google_fetch_report)
        stage_report["googleImagesRaw"] = len(google_candidates)
        stage_report["googleImagesDownloaded"] = len([item for item in downloaded_candidates if item.get("downloadStatus") == "downloaded"])
        seed_approved: list[dict[str, Any]] = []
        seed_report: dict[str, Any] = {}
        cached_seed_approved = json_list(run_dir / "seed_visual_approved.json") if resume_run_dir and (run_dir / "seed_visual_approved.json").exists() else []
        cached_seed_ready = [item for item in cached_seed_approved if isinstance(item, dict) and seed_item_is_lens_ready(item)]
        if cached_seed_approved and len(cached_seed_ready) == len(cached_seed_approved):
            seed_approved = cached_seed_ready
            seed_report = {
                "reviewable": len(json_list(run_dir / "seed_review_candidates.json")),
                "reviewableTotal": len(
                    [
                        item
                        for item in downloaded_candidates
                        if isinstance(item, dict)
                        and is_lens_ready_candidate(item)
                    ]
                ),
                "seedInputBlocked": len(json_list(run_dir / "seed_input_blocked.json")),
                "reviewPoolPerKeyword": args.seed_review_pool_per_keyword,
                "productPassed": len(json_list(run_dir / "seed_product_passed.json")),
                "productBlocked": len(json_list(run_dir / "seed_product_blocked.json")),
                "safetyPassed": len(json_list(run_dir / "seed_safety_passed.json")),
                "safetyBlocked": len(json_list(run_dir / "seed_safety_blocked.json")),
                "visualApproved": len(seed_approved),
                "visualDeduped": len(json_list(run_dir / "seed_visual_deduped.json")),
                "resumedFromSeedReview": True,
            }
            print(f"Resuming from approved seed images: {len(seed_approved)}", flush=True)
        elif cached_seed_approved and not stage_report["degraded"]:
            print("Cached approved seed images are not Lens-ready; rerunning seed review from original-image candidates.", flush=True)
            seed_approved, seed_report = run_seed_reviews(
                downloaded_candidates,
                run_dir,
                max(1, args.seeds_per_keyword),
                max(0, args.seed_review_pool_per_keyword),
            )
            seed_report["reranSeedReviewReason"] = "cached_seed_not_lens_ready"
        elif not stage_report["degraded"]:
            seed_approved, seed_report = run_seed_reviews(
                downloaded_candidates,
                run_dir,
                max(1, args.seeds_per_keyword),
                max(0, args.seed_review_pool_per_keyword),
            )
        else:
            write_json(run_dir / "seed_product_passed.json", [])
            write_json(run_dir / "seed_product_blocked.json", [])
            write_json(run_dir / "seed_safety_passed.json", [])
            write_json(run_dir / "seed_safety_blocked.json", [])
            write_json(run_dir / "seed_visual_approved.json", [])
            write_json(run_dir / "seed_visual_deduped.json", [])
        stage_report.update(seed_report)

        if not stage_report["degraded"] and seed_approved:
            pw, context = launch_chrome_context(profile_dir / "lens_session", args.visible_browser, args.timeout_seconds)
            try:
                for seed in seed_approved:
                    try:
                        matches, lens_report = run_google_lens_for_seed(
                            context,
                            seed,
                            run_dir,
                            max(1, args.lens_candidates),
                            max(5, args.timeout_seconds),
                            verification_state,
                            max(10, args.captcha_wait_seconds),
                        )
                    except GoogleVerificationRequired as exc:
                        lens_reports.append(
                            {
                                "seedId": seed.get("seedId"),
                                "seedKeyword": seed.get("keyword") or seed.get("searchQuery"),
                                "status": "degraded",
                                "error": clean_text(exc, max_len=300),
                            }
                        )
                        stage_report["degraded"] = True
                        stage_report["degradedReason"] = verification_state.get("reason") or "google_verification_required"
                        break
                    lens_reports.append(lens_report)
                    all_seed_matches.extend(matches)
                    write_json(run_dir / "lens_seed_reports.json", lens_reports)
                    write_json(run_dir / "lens_matches_all.json", aggregate_lens_matches(all_seed_matches))
            finally:
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        pass
                    context = None
                if pw is not None:
                    try:
                        pw.stop()
                    except Exception:
                        pass
                    pw = None
        lens_matches = aggregate_lens_matches(all_seed_matches)
        write_json(run_dir / "lens_seed_reports.json", lens_reports)
        write_json(run_dir / "lens_matches_all.json", lens_matches)
        stage_report["lensSeedsRun"] = len([report for report in lens_reports if report.get("status") == "ok"])
        stage_report["lensMatchCount"] = len(lens_matches)

        approved: list[dict[str, Any]] = []
        instagram_report: dict[str, Any] = {}
        if lens_matches and not stage_report["degraded"]:
            approved, instagram_report = run_instagram_stage(
                lens_matches,
                run_dir,
                cookie_path,
                max(0, args.min_likes),
                max(0, args.min_comments),
                max(1, args.engagement_top_n),
            )
        else:
            write_json(run_dir / "instagram_candidates.json", [])
            write_json(run_dir / "instagram_enriched.json", [])
            write_json(run_dir / "instagram_blocked.json", [])
            write_json(run_dir / "instagram_approved.json", [])
            ins_filter.write_approved_markdown(run_dir / "instagram_approved.md", [])
            instagram_report = {
                "workflow": "google_images_keyword_lens_instagram_filter",
                "generatedAt": now_iso(),
                "lensMatchCount": len(lens_matches),
                "instagramCandidateCount": 0,
                "enrichedCount": 0,
                "blockedCount": 0,
                "approvedCount": 0,
                "skippedReason": stage_report.get("degradedReason") if stage_report["degraded"] else "no_lens_matches",
            }
            write_json(run_dir / "instagram_filter_report.json", instagram_report)

        write_json(run_dir / "final_approved.json", approved)
        write_final_markdown(run_dir / "final_approved.md", approved)
        stage_report["instagramApprovedCount"] = len(approved)
        stage_report["instagramFilterReport"] = instagram_report
        stage_report["generatedAt"] = now_iso()
        write_json(run_dir / "stage_report.json", stage_report)
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass
        manifest["finishedAt"] = now_iso()
        manifest["degraded"] = bool(stage_report.get("degraded"))
        manifest["degradedReason"] = stage_report.get("degradedReason", "")
        write_json(run_dir / "run_manifest.json", manifest)

    print(f"Run directory: {run_dir}", flush=True)
    print(f"Google Images candidates: {stage_report.get('googleImagesRaw', 0)}", flush=True)
    print(f"Lens matches: {stage_report.get('lensMatchCount', 0)}", flush=True)
    print(f"Final approved Instagram posts: {stage_report.get('instagramApprovedCount', 0)}", flush=True)
    if stage_report.get("degraded"):
        print(f"Degraded: {stage_report.get('degradedReason')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
