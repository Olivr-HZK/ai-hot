from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from comment_enrichment import existing_comments
from env_utils import BASE_DIR, env_bool, env_int, load_env


SPACE_RE = re.compile(r"\s+")
TCO_RE = re.compile(r"https?://t\.co/[A-Za-z0-9_%-]+")
UNUSABLE_HTML_RE = re.compile(
    r"(something went wrong|this page is not available|log in to continue|"
    r"sign up for|browser is no longer supported|enable javascript|"
    r"tiktok - make your day)",
    re.IGNORECASE,
)


class TextAndMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_ignored = False
        self.ignored_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.meta: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self.in_ignored = True
            self.ignored_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            attrs_dict = {key.lower(): value or "" for key, value in attrs}
            name = (attrs_dict.get("name") or attrs_dict.get("property") or "").lower()
            content = clean_text(attrs_dict.get("content"))
            if content and name in {"description", "og:description", "twitter:description"}:
                self.meta.append(content)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self.ignored_depth > 0:
            self.ignored_depth -= 1
            self.in_ignored = self.ignored_depth > 0
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_ignored:
            return
        text = clean_text(data)
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        elif len(text) >= 20:
            self.text_parts.append(text)

    def blocks(self, source_prefix: str) -> list[dict[str, str]]:
        blocks: list[dict[str, str]] = []
        for index, text in enumerate(self.meta[:6]):
            blocks.append({"source": f"{source_prefix}.meta[{index}]", "text": text})
        title = clean_text(" ".join(self.title_parts))
        if title:
            blocks.append({"source": f"{source_prefix}.title", "text": title})
        body = clean_text(" ".join(self.text_parts), max_len=6000)
        if body:
            blocks.append({"source": f"{source_prefix}.body", "text": body})
        return blocks


def clean_text(value: Any, *, max_len: int | None = None) -> str:
    text = SPACE_RE.sub(" ", str(value or "")).strip()
    if max_len is not None and len(text) > max_len:
        return text[:max_len].rstrip()
    return text


def project_path(path: Path) -> Path:
    return path if path.is_absolute() else BASE_DIR / path


def platform_of(item: dict[str, Any]) -> str:
    raw = clean_text(item.get("hotspotPlatform") or item.get("sourcePlatform") or item.get("platform")).lower()
    if raw in {"x", "twitter"}:
        return "x"
    if raw in {"tiktok", "tik tok", "tt"}:
        return "tiktok"
    if raw in {"instagram", "ins"}:
        return "ins"
    url = item_url(item).lower()
    if "x.com/" in url or "twitter.com/" in url:
        return "x"
    if "tiktok.com/" in url:
        return "tiktok"
    if "instagram.com/" in url:
        return "ins"
    return raw or "unknown"


def item_url(item: dict[str, Any]) -> str:
    video_meta = item.get("videoMeta") if isinstance(item.get("videoMeta"), dict) else {}
    raw_source = item.get("raw_source") if isinstance(item.get("raw_source"), dict) else {}
    for value in [
        item.get("hotspotUrl"),
        item.get("webVideoUrl"),
        item.get("url"),
        item.get("shareUrl"),
        item.get("canonicalUrl"),
        video_meta.get("webVideoUrl"),
        raw_source.get("hotspotUrl"),
        raw_source.get("webVideoUrl"),
        raw_source.get("url"),
        raw_source.get("shareUrl"),
    ]:
        text = clean_text(value)
        if text.startswith("http"):
            return text
    return ""


def item_id(item: dict[str, Any], platform: str) -> str:
    for key in ["id", "tweetId", "tweet_id", "videoId", "aweme_id", "shortcode", "code", "pk"]:
        value = clean_text(item.get(key))
        if value:
            return value
    url = item_url(item)
    if platform == "x":
        match = re.search(r"/status/(\d+)", url)
        if match:
            return match.group(1)
    if platform == "tiktok":
        match = re.search(r"/video/(\d+)", url)
        if match:
            return match.group(1)
    if platform == "ins":
        match = re.search(r"instagram\.com/(?:p|reel)/([^/?#]+)", url)
        if match:
            return match.group(1)
    return ""


def config(env: dict[str, str]) -> dict[str, Any]:
    timeout = env_int("AUTO_PROMPT_SOURCE_REHYDRATE_TIMEOUT_SECONDS", 30, env)
    cookie_domains = [
        clean_text(value).lower().lstrip(".")
        for value in re.split(r"[,;]+", env.get("AUTO_PROMPT_COOKIE_DOMAINS", "x.com,tiktok.com,instagram.com"))
        if clean_text(value)
    ]
    browser_platforms = {
        clean_text(value).lower()
        for value in re.split(r"[,;]+", env.get("AUTO_PROMPT_BROWSER_REHYDRATE_PLATFORMS", "x"))
        if clean_text(value)
    }
    return {
        "enabled": env_bool("AUTO_PROMPT_SOURCE_REHYDRATE_ENABLED", True, env),
        "mode": clean_text(env.get("AUTO_PROMPT_SOURCE_REHYDRATE_MODE") or "no_api").lower(),
        "cache_dir": Path(env.get("AUTO_PROMPT_SOURCE_REHYDRATE_CACHE_DIR") or "skill_runs/source_rehydrate"),
        "timeout": timeout,
        "max_comments": env_int("AUTO_PROMPT_SOURCE_REHYDRATE_MAX_COMMENTS", 20, env),
        "x_enabled": env_bool("AUTO_PROMPT_X_DETAIL_ENABLED", True, env),
        "tiktok_enabled": env_bool("AUTO_PROMPT_TIKTOK_DETAIL_ENABLED", True, env),
        "ins_enabled": env_bool("AUTO_PROMPT_INS_DETAIL_ENABLED", True, env),
        "use_local_cookies": env_bool("AUTO_PROMPT_USE_LOCAL_COOKIES", True, env),
        "cookie_file": Path(env.get("AUTO_PROMPT_COOKIE_FILE") or "skill_runs/cookies/source_rehydrate_cookies.json"),
        "cookie_domains": cookie_domains,
        "cookie_timeout": env_int("AUTO_PROMPT_COOKIE_TIMEOUT_SECONDS", timeout, env),
        "local_cache_max_file_bytes": env_int("AUTO_PROMPT_LOCAL_CACHE_MAX_FILE_MB", 80, env) * 1024 * 1024,
        "browser_enabled": env_bool("AUTO_PROMPT_BROWSER_REHYDRATE_ENABLED", True, env),
        "browser_platforms": browser_platforms,
        "browser_headless": env_bool("AUTO_PROMPT_BROWSER_HEADLESS", True, env),
        "browser_timeout": env_int("AUTO_PROMPT_BROWSER_TIMEOUT_SECONDS", 45, env),
        "browser_wait_after_load_ms": env_int("AUTO_PROMPT_BROWSER_WAIT_AFTER_LOAD_MS", 1500, env),
        "browser_cache_version": clean_text(env.get("AUTO_PROMPT_BROWSER_CACHE_VERSION") or "browser_v1"),
    }


def cache_path(cache_dir: Path, url: str, mode: str) -> Path:
    digest = hashlib.sha256(f"{mode}:{url}".encode("utf-8")).hexdigest()[:24]
    return BASE_DIR / cache_dir / f"{digest}.json"


def cache_identity(cfg: dict[str, Any], platform: str) -> str:
    mode = clean_text(cfg.get("mode") or "no_api").lower()
    if browser_render_enabled(platform, cfg):
        return f"{mode}:{cfg.get('browser_cache_version') or 'browser_v1'}"
    return mode


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def extract_url_texts(value: Any) -> list[str]:
    texts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            texts.append(node)
        elif isinstance(node, dict):
            for key in ["text", "title", "desc", "description", "caption", "hotspotIntro", "summary"]:
                if key in node:
                    walk(node.get(key))
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return texts


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def normalize_cookie_domain(domain: str) -> str:
    return clean_text(domain).lower().lstrip(".")


def domain_matches(host: str, domain: str) -> bool:
    host = host.lower().lstrip(".")
    domain = normalize_cookie_domain(domain)
    return bool(host and domain and (host == domain or host.endswith("." + domain)))


def cookie_domain_allowed(domain: str, allowed_domains: list[str]) -> bool:
    if not allowed_domains:
        return True
    normalized = normalize_cookie_domain(domain)
    return any(domain_matches(normalized, allowed) or domain_matches(allowed, normalized) for allowed in allowed_domains)


def load_cookie_headers(cfg: dict[str, Any]) -> tuple[dict[str, str], dict[str, Any]]:
    if not cfg.get("use_local_cookies"):
        return {}, {"status": "skipped", "reason": "local cookies disabled"}
    path = project_path(Path(cfg["cookie_file"]))
    if not path.exists():
        return {}, {"status": "failed", "reason": "cookie_file_missing", "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {}, {"status": "failed", "reason": "cookie_file_invalid_json", "error": clean_text(exc, max_len=300), "path": str(path)}

    allowed_domains = list(cfg.get("cookie_domains") or [])
    headers: dict[str, str] = {}
    if isinstance(data, dict) and all(isinstance(value, str) for value in data.values()):
        for raw_domain, header in data.items():
            domain = normalize_cookie_domain(raw_domain)
            if domain and header and cookie_domain_allowed(domain, allowed_domains):
                headers[domain] = clean_text(header)
    else:
        cookies = data.get("cookies") if isinstance(data, dict) else data
        if isinstance(cookies, list):
            grouped: dict[str, list[str]] = {}
            for cookie in cookies:
                if not isinstance(cookie, dict):
                    continue
                name = clean_text(cookie.get("name"))
                value = clean_text(cookie.get("value"))
                domain = normalize_cookie_domain(cookie.get("domain") or "")
                if not name or not value or not domain or not cookie_domain_allowed(domain, allowed_domains):
                    continue
                grouped.setdefault(domain, []).append(f"{name}={value}")
            headers = {domain: "; ".join(values) for domain, values in grouped.items() if values}

    return headers, {
        "status": "success" if headers else "failed",
        "reason": "" if headers else "no_cookie_for_allowed_domains",
        "path": str(path),
        "domains": sorted(headers.keys()),
    }


def cookie_for_url(url: str, cookie_headers: dict[str, str]) -> tuple[str, str]:
    host = host_of(url)
    matches = [(domain, header) for domain, header in cookie_headers.items() if domain_matches(host, domain)]
    if not matches:
        return "", ""
    domain, header = sorted(matches, key=lambda pair: len(pair[0]), reverse=True)[0]
    return header, domain


def browser_render_enabled(platform: str, cfg: dict[str, Any]) -> bool:
    if cfg.get("mode") != "no_api" or not cfg.get("browser_enabled"):
        return False
    return clean_text(platform).lower() in set(cfg.get("browser_platforms") or set())


def playwright_cookies_for_url(url: str, cookie_headers: dict[str, str]) -> tuple[list[dict[str, Any]], str]:
    cookie_header, cookie_domain = cookie_for_url(url, cookie_headers)
    if not cookie_header:
        return [], ""
    cookies: list[dict[str, Any]] = []
    domain = "." + cookie_domain.lstrip(".")
    for raw_part in cookie_header.split(";"):
        if "=" not in raw_part:
            continue
        name, value = raw_part.split("=", 1)
        name = clean_text(name)
        value = value.strip()
        if not name or not value:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "secure": True,
                "sameSite": "Lax",
            }
        )
    return cookies, cookie_domain


def click_x_show_more(page: Any) -> int:
    clicked = 0
    patterns = [
        r"show more",
        r"显示更多",
        r"查看更多",
        r"更多",
    ]
    for pattern in patterns:
        try:
            locators = page.get_by_text(re.compile(pattern, re.IGNORECASE))
            count = min(locators.count(), 6)
            for index in range(count):
                try:
                    locators.nth(index).click(timeout=1200)
                    clicked += 1
                except Exception:
                    continue
        except Exception:
            continue
    return clicked


def extract_x_tweet_texts(page: Any, target_id: str = "") -> list[str]:
    script = """
    (targetId) => {
      const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
      const articles = Array.from(document.querySelectorAll('article[data-testid="tweet"]'));
      const results = [];
      for (const article of articles) {
        const links = Array.from(article.querySelectorAll('a[href*="/status/"]')).map((a) => a.getAttribute('href') || '');
        const idHit = !targetId || links.some((href) => href.includes('/status/' + targetId));
        const texts = Array.from(article.querySelectorAll('div[data-testid="tweetText"]')).map((node) => clean(node.innerText)).filter(Boolean);
        if (idHit && texts.length) {
          results.push(...texts);
        }
      }
      if (!results.length) {
        const fallback = Array.from(document.querySelectorAll('div[data-testid="tweetText"]')).map((node) => clean(node.innerText)).filter(Boolean);
        results.push(...fallback);
      }
      return Array.from(new Set(results));
    }
    """
    try:
        values = page.evaluate(script, target_id)
    except Exception:
        values = []
    if not isinstance(values, list):
        return []
    return [clean_text(value, max_len=6000) for value in values if clean_text(value)]


def fetch_browser_render_blocks(
    item: dict[str, Any],
    platform: str,
    url: str,
    cfg: dict[str, Any],
    cookie_headers: dict[str, str],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not browser_render_enabled(platform, cfg):
        return [], {"status": "skipped", "reason": "browser_render_disabled"}
    if platform != "x":
        return [], {"status": "skipped", "reason": f"unsupported_browser_platform:{platform}"}
    cookies, cookie_domain = playwright_cookies_for_url(url, cookie_headers)
    if not cookies:
        return [], {"status": "skipped", "reason": "missing_browser_cookie", "browserCookieUsed": False, "browserCookieDomain": ""}
    timeout_ms = max(1000, int(cfg["browser_timeout"]) * 1000)
    target_id = item_id(item, platform)
    browser = None
    context = None
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return [], {"status": "skipped", "reason": "browser_unavailable", "error": clean_text(exc, max_len=300)}

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=bool(cfg["browser_headless"]))
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                ),
                locale="en-US",
            )
            context.add_cookies(cookies)
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_selector('article[data-testid="tweet"], div[data-testid="tweetText"]', timeout=timeout_ms)
            except PlaywrightTimeoutError:
                return [], {
                    "status": "failed",
                    "reason": "browser_timeout",
                    "browserCookieUsed": True,
                    "browserCookieDomain": cookie_domain,
                    "finalUrl": page.url,
                }
            wait_ms = max(0, int(cfg["browser_wait_after_load_ms"]))
            if wait_ms:
                page.wait_for_timeout(wait_ms)
            clicked = click_x_show_more(page)
            if clicked:
                page.wait_for_timeout(500)
            texts = extract_x_tweet_texts(page, target_id=target_id)
            blocks = [
                {"source": f"sourceRehydrate.browserRender.xTweetText[{index}]", "text": text}
                for index, text in enumerate(texts[:10])
            ]
            status = "success" if blocks else "failed"
            reason = "" if blocks else "browser_login_or_shell"
            return blocks, {
                "status": status,
                "reason": reason,
                "browserCookieUsed": True,
                "browserCookieDomain": cookie_domain,
                "finalUrl": page.url,
                "browserTextBlockCount": len(blocks),
                "showMoreClicked": clicked,
            }
    except Exception as exc:
        return [], {
            "status": "failed",
            "reason": "browser_error",
            "browserCookieUsed": True,
            "browserCookieDomain": cookie_domain,
            "error": clean_text(exc, max_len=500),
        }
    finally:
        try:
            if context is not None:
                context.close()
        except Exception:
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass


def html_usability(blocks: list[dict[str, str]], url: str) -> tuple[bool, str]:
    joined = clean_text(" ".join(str(block.get("text") or "") for block in blocks), max_len=2000)
    meaningful = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", joined)
    if not blocks or len(meaningful) < 24:
        return False, "empty_or_too_short"
    if "prompt" in joined.lower() or "\u63d0\u793a\u8bcd" in joined:
        return True, "usable"
    if UNUSABLE_HTML_RE.search(joined) and len(meaningful) < 220:
        return False, f"generic_shell:{host_of(url) or 'unknown_host'}"
    return True, "usable"


def fetch_html_blocks(
    url: str,
    timeout: int,
    *,
    cookie_header: str = "",
    cookie_domain: str = "",
    source_prefix: str = "sourceRehydrate.publicHtml",
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not url:
        return [], {"status": "skipped", "reason": "missing_url"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    }
    if cookie_header:
        headers["Cookie"] = cookie_header
    response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "<html" not in response.text[:500].lower():
        return [], {
            "status": "skipped",
            "reason": f"non_html_content:{content_type}",
            "finalUrl": response.url,
            "cookieUsed": bool(cookie_header),
            "cookieDomain": cookie_domain,
        }
    parser = TextAndMetaParser()
    parser.feed(response.text[:500_000])
    blocks = parser.blocks(source_prefix)
    usable, html_status = html_usability(blocks, response.url)
    return (blocks if usable else []), {
        "status": "success" if usable else "failed",
        "htmlStatus": html_status,
        "finalUrl": response.url,
        "contentType": content_type,
        "blockCount": len(blocks if usable else []),
        "cookieUsed": bool(cookie_header),
        "cookieDomain": cookie_domain,
    }


def collect_json_text_blocks(payload: Any, prefix: str, limit: int = 20) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    keys = {
        "text",
        "full_text",
        "desc",
        "description",
        "caption",
        "title",
        "content",
        "body",
        "richtext",
        "note",
    }

    def walk(node: Any, path: str) -> None:
        if len(blocks) >= limit:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                next_path = f"{path}.{key}" if path else key
                if key in keys:
                    text = clean_text(value, max_len=4000)
                    if text:
                        blocks.append({"source": f"{prefix}.{next_path}", "text": text})
                        if len(blocks) >= limit:
                            return
                walk(value, next_path)
        elif isinstance(node, list):
            for index, item in enumerate(node[:50]):
                walk(item, f"{path}[{index}]")
                if len(blocks) >= limit:
                    return

    walk(payload, "")
    return blocks


def normalized_urls(url: str) -> set[str]:
    text = clean_text(url).rstrip("/")
    if not text:
        return set()
    urls = {text, text.replace("twitter.com/", "x.com/"), text.replace("x.com/", "twitter.com/")}
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        without_query = parsed._replace(query="", fragment="").geturl().rstrip("/")
        urls.update(
            {
                without_query,
                without_query.replace("twitter.com/", "x.com/"),
                without_query.replace("x.com/", "twitter.com/"),
            }
        )
    return {item for item in urls if item}


def candidate_url_values(node: dict[str, Any]) -> list[str]:
    values: list[str] = []
    video_meta = node.get("videoMeta") if isinstance(node.get("videoMeta"), dict) else {}
    raw_source = node.get("raw_source") if isinstance(node.get("raw_source"), dict) else {}
    for value in [
        node.get("hotspotUrl"),
        node.get("webVideoUrl"),
        node.get("url"),
        node.get("shareUrl"),
        node.get("canonicalUrl"),
        video_meta.get("webVideoUrl"),
        raw_source.get("hotspotUrl"),
        raw_source.get("webVideoUrl"),
        raw_source.get("url"),
        raw_source.get("shareUrl"),
    ]:
        text = clean_text(value)
        if text.startswith("http"):
            values.append(text)
    return values


def candidate_id_values(node: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ["id", "tweetId", "tweet_id", "videoId", "aweme_id", "shortcode", "code", "pk"]:
        value = clean_text(node.get(key))
        if value:
            values.append(value)
    for url in candidate_url_values(node):
        for pattern in [r"/status/(\d+)", r"/video/(\d+)", r"instagram\.com/(?:p|reel)/([^/?#]+)"]:
            match = re.search(pattern, url)
            if match:
                values.append(match.group(1))
    return values


def iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def local_cache_files() -> list[Path]:
    roots = [
        BASE_DIR / "skill_runs" / "hotspots.json",
        BASE_DIR / "skill_runs" / "hotspots_tiktok.json",
        BASE_DIR / "skill_runs" / "hotspots_x.json",
        BASE_DIR / "skill_runs" / "hotspots_ins.json",
        BASE_DIR / "skill_runs" / "manual_audits",
        BASE_DIR / "skill_runs" / "scrape_checkpoints",
        BASE_DIR / "skill_runs" / "tiktok_hot_feed",
        BASE_DIR / "skill_runs" / "instagram",
        BASE_DIR / "trend-scrap" / "x-scraper" / "data",
        BASE_DIR / "trend-scrap" / "tiktok-scraper" / "data",
    ]
    files: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix.lower() == ".json":
            files.append(root)
        elif root.exists():
            files.extend(path for path in root.rglob("*.json") if path.is_file())
    return files


def node_matches_target(node: dict[str, Any], target_urls: set[str], target_id: str) -> bool:
    for url in candidate_url_values(node):
        if normalized_urls(url) & target_urls:
            return True
    if target_id:
        return target_id in set(candidate_id_values(node))
    return False


def fetch_local_cache_blocks(item: dict[str, Any], platform: str, cfg: dict[str, Any]) -> tuple[list[dict[str, str]], list[str], dict[str, Any]]:
    url = item_url(item)
    target_urls = normalized_urls(url)
    target_id = item_id(item, platform)
    if not target_urls and not target_id:
        return [], [], {"status": "skipped", "reason": "missing_url_or_id"}
    needles = set(target_urls)
    if target_id:
        needles.add(target_id)
    blocks: list[dict[str, str]] = []
    comments: list[str] = []
    matched_files: list[str] = []
    skipped_large = 0
    max_bytes = int(cfg.get("local_cache_max_file_bytes") or 80 * 1024 * 1024)
    for path in local_cache_files():
        try:
            if path.stat().st_size > max_bytes:
                skipped_large += 1
                continue
            raw_text = path.read_text(encoding="utf-8-sig", errors="ignore")
        except Exception:
            continue
        if not any(needle and needle in raw_text for needle in needles):
            continue
        try:
            data = json.loads(raw_text)
        except Exception:
            continue
        file_matched = False
        for node in iter_dicts(data):
            if not node_matches_target(node, target_urls, target_id):
                continue
            file_matched = True
            blocks.extend(collect_json_text_blocks(node, f"sourceRehydrate.localCache.{path.name}", limit=10))
            remaining = max(0, int(cfg["max_comments"]) - len(comments))
            for comment in existing_comments(node, remaining):
                if comment not in comments:
                    comments.append(comment)
            if len(blocks) >= 30 and len(comments) >= int(cfg["max_comments"]):
                break
        if file_matched:
            matched_files.append(str(path))
        if len(blocks) >= 30 and len(comments) >= int(cfg["max_comments"]):
            break
    return blocks[:30], comments[: int(cfg["max_comments"])], {
        "status": "success" if blocks or comments else "skipped",
        "reason": "" if blocks or comments else "no_local_cache_match",
        "matchedFiles": matched_files[:10],
        "matchCount": len(matched_files),
        "skippedLargeFiles": skipped_large,
    }


def fetch_existing_comments(item: dict[str, Any], cfg: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    limit = max(0, int(cfg["max_comments"]))
    if limit <= 0:
        return [], {"status": "skipped", "reason": "max_comments_zero"}
    comments = existing_comments(item, limit)
    if comments:
        return comments, {"status": "success", "source": "existing", "count": len(comments)}
    return [], {"status": "skipped", "reason": "no_existing_comments"}


def build_rehydrate_payload(item: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    cfg = config(env)
    url = item_url(item)
    platform = platform_of(item)
    payload: dict[str, Any] = {
        "status": "skipped",
        "mode": cfg["mode"],
        "platform": platform,
        "url": url,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "textBlocks": [],
        "comments": [],
        "attempts": [],
        "cookieUsed": False,
        "cookieDomain": "",
        "htmlStatus": "",
        "localCacheHit": False,
        "browserUsed": False,
        "browserStatus": "skipped",
        "browserTextBlockCount": 0,
        "browserError": "",
        "browserCacheVersion": cfg.get("browser_cache_version", ""),
        "browserCookieUsed": False,
        "browserCookieDomain": "",
    }
    if not cfg["enabled"]:
        payload["reason"] = "source rehydrate disabled"
        return payload
    if not url:
        payload["reason"] = "missing source url"
        return payload
    platform_enabled = {
        "x": cfg["x_enabled"],
        "tiktok": cfg["tiktok_enabled"],
        "ins": cfg["ins_enabled"],
    }.get(platform, False)
    if not platform_enabled:
        payload["reason"] = f"{platform} source rehydrate disabled"
        return payload

    text_blocks: list[dict[str, str]] = []
    comments: list[str] = []

    blocks, local_comments, local_meta = fetch_local_cache_blocks(item, platform, cfg)
    text_blocks.extend(blocks)
    comments.extend(local_comments)
    payload["localCacheHit"] = bool(blocks or local_comments)
    payload["attempts"].append({"type": "local_cache", **local_meta})

    cookie_headers: dict[str, str] = {}
    cookie_meta: dict[str, Any] = {"status": "skipped", "reason": "not_loaded"}
    if cfg["mode"] == "no_api" and cfg.get("use_local_cookies"):
        cookie_headers, cookie_meta = load_cookie_headers(cfg)
        payload["attempts"].append({"type": "cookie_file", **cookie_meta})

    if cfg["mode"] == "no_api" and browser_render_enabled(platform, cfg):
        blocks, browser_meta = fetch_browser_render_blocks(item, platform, url, cfg, cookie_headers)
        text_blocks.extend(blocks)
        payload["browserUsed"] = browser_meta.get("status") != "skipped"
        payload["browserStatus"] = str(browser_meta.get("status") or "skipped")
        payload["browserTextBlockCount"] = int(browser_meta.get("browserTextBlockCount") or len(blocks))
        payload["browserError"] = clean_text(browser_meta.get("error"), max_len=500)
        payload["browserCookieUsed"] = bool(browser_meta.get("browserCookieUsed"))
        payload["browserCookieDomain"] = clean_text(browser_meta.get("browserCookieDomain"))
        payload["attempts"].append({"type": "browser_render", **browser_meta})

    urls_to_visit = [url]
    for source_text in extract_url_texts(item):
        urls_to_visit.extend(TCO_RE.findall(source_text))
    urls_to_visit = list(dict.fromkeys(urls_to_visit))

    for index, visit_url in enumerate(urls_to_visit):
        cookie_header, cookie_domain = cookie_for_url(visit_url, cookie_headers)
        if not cookie_header:
            payload["attempts"].append(
                {
                    "type": "cookie_html",
                    "url": visit_url,
                    "index": index,
                    "status": "skipped",
                    "reason": cookie_meta.get("reason") or "no_cookie_for_domain",
                    "cookieUsed": False,
                    "cookieDomain": "",
                }
            )
            continue
        try:
            blocks, meta = fetch_html_blocks(
                visit_url,
                int(cfg["cookie_timeout"]),
                cookie_header=cookie_header,
                cookie_domain=cookie_domain,
                source_prefix="sourceRehydrate.cookieHtml",
            )
            text_blocks.extend(blocks)
            if blocks and not payload["cookieUsed"]:
                payload["cookieUsed"] = True
                payload["cookieDomain"] = cookie_domain
            if meta.get("htmlStatus") and not payload["htmlStatus"]:
                payload["htmlStatus"] = str(meta.get("htmlStatus"))
            payload["attempts"].append({"type": "cookie_html", "url": visit_url, "index": index, **meta})
        except Exception as exc:
            payload["attempts"].append(
                {
                    "type": "cookie_html",
                    "url": visit_url,
                    "index": index,
                    "status": "failed",
                    "cookieUsed": bool(cookie_header),
                    "cookieDomain": cookie_domain,
                    "error": clean_text(exc, max_len=500),
                }
            )

    for index, visit_url in enumerate(urls_to_visit):
        try:
            blocks, meta = fetch_html_blocks(visit_url, int(cfg["timeout"]), source_prefix="sourceRehydrate.publicHtml")
            text_blocks.extend(blocks)
            if meta.get("htmlStatus") and not payload["htmlStatus"]:
                payload["htmlStatus"] = str(meta.get("htmlStatus"))
            payload["attempts"].append({"type": "public_html", "url": visit_url, "index": index, **meta})
        except Exception as exc:
            payload["attempts"].append(
                {"type": "public_html", "url": visit_url, "index": index, "status": "failed", "error": clean_text(exc, max_len=500)}
            )

    existing, comment_meta = fetch_existing_comments(item, cfg)
    for comment in existing:
        if comment not in comments:
            comments.append(comment)
    payload["comments"] = comments[: int(cfg["max_comments"])]
    payload["attempts"].append({"type": "comments", **comment_meta, "externalApiUsed": False})
    payload["attempts"].append({"type": "platform_detail", "status": "skipped", "reason": "no_api_mode", "externalApiUsed": False})

    seen: set[str] = set()
    deduped_blocks: list[dict[str, str]] = []
    for block in text_blocks:
        text = clean_text(block.get("text"), max_len=6000)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        deduped_blocks.append({"source": block.get("source", "sourceRehydrate"), "text": text})
    payload["textBlocks"] = deduped_blocks[:20]
    payload["status"] = "success" if payload["textBlocks"] or payload["comments"] else "failed"
    if payload["status"] == "failed":
        payload["reason"] = "no source text or comments collected"
    return payload


def rehydrate_item(item: dict[str, Any], env: dict[str, str] | None = None) -> dict[str, Any]:
    env = env or load_env()
    cfg = config(env)
    updated = dict(item)
    url = item_url(updated)
    if not cfg["enabled"] or not url:
        payload = build_rehydrate_payload(updated, env)
        updated["sourceRehydrate"] = payload
        updated["sourceRehydrateTextBlocks"] = []
        updated["sourceRehydrateComments"] = []
        return updated
    platform = platform_of(updated)
    cache_key = cache_identity(cfg, platform)
    path = cache_path(Path(cfg["cache_dir"]), url, cache_key)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            if clean_text(payload.get("mode") or "no_api").lower() != clean_text(cfg.get("mode") or "no_api").lower():
                raise ValueError("cached source rehydrate mode mismatch")
            if browser_render_enabled(platform, cfg) and clean_text(payload.get("browserCacheVersion")) != clean_text(cfg.get("browser_cache_version")):
                raise ValueError("cached source rehydrate browser cache version mismatch")
            payload["cacheHit"] = True
        except Exception:
            payload = build_rehydrate_payload(updated, env)
            try:
                atomic_write_json(path, payload)
            except Exception as exc:
                payload["cacheWriteError"] = clean_text(exc, max_len=300)
    else:
        payload = build_rehydrate_payload(updated, env)
        try:
            atomic_write_json(path, payload)
        except Exception as exc:
            payload["cacheWriteError"] = clean_text(exc, max_len=300)
    updated["sourceRehydrate"] = {
        key: value
        for key, value in payload.items()
        if key not in {"textBlocks", "comments"}
    }
    updated["sourceRehydrate"]["cachePath"] = str(path)
    updated["sourceRehydrateTextBlocks"] = payload.get("textBlocks") or []
    updated["sourceRehydrateComments"] = payload.get("comments") or []
    return updated
