from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
BASE_DIR = SCRIPTS_DIR.parent
INSTAGRAM_DIR = SCRIPTS_DIR / "instagram"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(INSTAGRAM_DIR))

from env_utils import env_bool, env_float, env_int, load_env, resolve_bitable_config
from feedback_field_utils import (
    field_text,
    field_url,
    material_feedback,
    normalize_acceptance,
)
from feedback_hard_filter import apply_feedback_hard_filter
from feishu_push import WRITE_FIELD_NAMES, get_tenant_access_token
from instagram.ins_product_fit import apply_product_fit
from instagram.ins_product_review import apply_product_v2_review
from instagram.ins_rules import load_ins_rules
from instagram.ins_safety_review import apply_ins_safety_review
from instagram.ins_scoring import normalize_ins_post
from pipeline_variant import mark_pipeline_variant, resolve_pipeline_variant
from scrape_checkpoint import atomic_write_json
from ua_material_review import (
    apply_ua_material_review,
    force_ua_material_push_object,
    mark_ua_material_candidates,
    merge_unique_preserving_ua_material,
)
from visual_dedupe import apply_visual_dedupe


RUN_ROOT = BASE_DIR / "skill_runs" / "instagram_keyword_discovery"
DEFAULT_MODEL = "qwen/qwen3.7-max"
DEFAULT_ACCOUNT_COOKIE = "www.instagram.com_cookies.txt"
DEFAULT_MAX_LINKS_PER_QUERY = 40
DEFAULT_MAX_SCROLLS = 12
DEFAULT_DELAY_SECONDS = 1.0
DEFAULT_MAX_POOL_TERMS = 0
INS_COMMENT_WEIGHT = 8
INS_BASELINE_MIN_CREATOR_POSTS = 3
NEGATIVE_QUERY_TERMS = [
    "celebrity",
    "paparazzi",
    "leak",
    "spoiler",
    "gossip",
    "onlyfans",
    "nsfw",
    "nude",
    "lingerie",
    "bikini",
    "crypto",
    "web3",
    "politics",
    "election",
    "hardware",
    "meme",
    "logic",
    "legacy",
    "product_v2",
    "product v2",
    "cta",
    "prompt",
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean_text(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", field_text(value)).strip()
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


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


def normalize_platform(value: Any) -> str:
    text = clean_text(value).lower()
    if text in {"ins", "instagram"}:
        return "instagram"
    return text


def is_high_quality_ins_record(fields: dict[str, Any]) -> tuple[bool, str]:
    feedback = material_feedback(fields)
    if normalize_acceptance(feedback.get("material_acceptance")) == "\u9ad8":
        return True, "material=high"
    return False, ""


def fetch_all_bitable_records(limit: int = 2000) -> list[dict[str, Any]]:
    cfg = resolve_bitable_config()
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret or not cfg["app_token"] or not cfg["table_id"]:
        raise RuntimeError("Missing Feishu bitable credentials")
    token = get_tenant_access_token(app_id, app_secret)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{cfg['app_token']}/tables/{cfg['table_id']}/records/search"
    records: list[dict[str, Any]] = []
    page_token = ""
    while len(records) < limit:
        body: dict[str, Any] = {"automatic_fields": True}
        params: dict[str, Any] = {"page_size": min(500, max(1, limit - len(records)))}
        if page_token:
            params["page_token"] = page_token
        response = requests.post(url, headers=headers, params=params, json=body, timeout=30)
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to fetch Feishu records: {data}")
        payload = data.get("data") or {}
        items = payload.get("items") or []
        records.extend(item for item in items if isinstance(item, dict))
        if not payload.get("has_more"):
            break
        page_token = clean_text(payload.get("page_token"))
        if not page_token:
            break
    return records


def record_to_seed(record: dict[str, Any]) -> dict[str, Any] | None:
    fields = record.get("fields") or {}
    if normalize_platform(fields.get(WRITE_FIELD_NAMES["platform"])) != "instagram":
        return None
    is_high_quality, quality_reason = is_high_quality_ins_record(fields)
    if not is_high_quality:
        return None
    url = field_url(fields.get(WRITE_FIELD_NAMES["url"]))
    if not url:
        return None
    feedback = material_feedback(fields)
    return {
        "recordId": record.get("record_id", ""),
        "pushDate": str(parse_feishu_date(fields.get(WRITE_FIELD_NAMES["push_date"])) or ""),
        "platform": "Instagram",
        "url": url,
        "intro": clean_text(fields.get(WRITE_FIELD_NAMES["intro"]), max_len=1200),
        "likes": clean_text(fields.get(WRITE_FIELD_NAMES["likes"])),
        "comments": clean_text(fields.get(WRITE_FIELD_NAMES["comments"])),
        "heat": clean_text(fields.get(WRITE_FIELD_NAMES["heat"])),
        "autoPrompt": clean_text(fields.get(WRITE_FIELD_NAMES.get("auto_prompt", "")), max_len=1200),
        "materialAcceptance": feedback.get("material_acceptance", ""),
        "materialReason": clean_text(feedback.get("material_reason"), max_len=600),
        "materialFeedbackSources": feedback.get("material_feedback_sources", []),
        "qualityReason": quality_reason,
    }


def collect_high_quality_seeds(lookback_days: int, max_seeds: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    today = date.today()
    cutoff = today - timedelta(days=max(1, lookback_days))
    records = fetch_all_bitable_records()
    seeds: list[dict[str, Any]] = []
    stats = {"recordsFetched": len(records), "instagramHighQuality": 0, "outsideLookback": 0}
    for record in records:
        seed = record_to_seed(record)
        if not seed:
            continue
        stats["instagramHighQuality"] += 1
        push_date = parse_feishu_date((record.get("fields") or {}).get(WRITE_FIELD_NAMES["push_date"]))
        if isinstance(push_date, date) and push_date < cutoff:
            stats["outsideLookback"] += 1
            continue
        seeds.append(seed)
    seeds.sort(key=lambda item: item.get("pushDate") or "", reverse=True)
    return seeds[: max(1, max_seeds)], stats


def load_product_manual() -> str:
    path = BASE_DIR / "references" / "product_material_requirements.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")[:10000]


def strip_json_fence(content: str) -> str:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def normalize_keyword(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[@#]+", " ", text)
    text = text.replace("-", " ").replace("_", " ")
    text = re.sub(r"[^a-z0-9 +]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_+")
    words = [word for word in text.split() if word not in {"the", "and", "for", "with", "from", "instagram", "viral", "trending"}]
    return " ".join(words[:6]).strip()


def keyword_allowed(value: str) -> bool:
    text = normalize_keyword(value)
    if not text or not re.search(r"[a-z]", text):
        return False
    if len(text.split()) < 2:
        return False
    if any(term in text for term in NEGATIVE_QUERY_TERMS):
        return False
    return True


def unique_keywords(values: list[Any], limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        keyword = normalize_keyword(value)
        if keyword and keyword_allowed(keyword) and keyword not in result:
            result.append(keyword)
        if len(result) >= limit:
            break
    return result


def keyword_pool_path(output_root: Path, env: dict[str, str]) -> Path:
    raw = os.environ.get("INS_MANUAL_KEYWORD_POOL_PATH") or env.get("INS_MANUAL_KEYWORD_POOL_PATH", "")
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else BASE_DIR / path
    return output_root / "keyword_pool.json"


def load_keyword_pool(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schemaVersion": 1, "createdAt": now_iso(), "updatedAt": "", "terms": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {"schemaVersion": 1, "createdAt": now_iso(), "updatedAt": "", "terms": [], "loadError": "invalid_json"}
    if not isinstance(data, dict):
        return {"schemaVersion": 1, "createdAt": now_iso(), "updatedAt": "", "terms": [], "loadError": "not_object"}
    terms = data.get("terms")
    if not isinstance(terms, list):
        data["terms"] = []
    else:
        cleaned_terms: list[dict[str, Any]] = []
        for entry in terms:
            if not isinstance(entry, dict):
                continue
            term = normalize_keyword(entry.get("term"))
            if not keyword_allowed(term):
                continue
            updated = dict(entry)
            updated["term"] = term
            cleaned_terms.append(updated)
        data["terms"] = cleaned_terms
    data.setdefault("schemaVersion", 1)
    data.setdefault("createdAt", now_iso())
    data.setdefault("updatedAt", "")
    return data


def pool_term_index(pool: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in pool.get("terms") or []:
        if not isinstance(entry, dict):
            continue
        term = normalize_keyword(entry.get("term"))
        if term:
            result[term] = entry
    return result


def update_keyword_pool_with_learned_terms(
    pool: dict[str, Any],
    terms: list[str],
    *,
    run_id: str,
    seeds: list[dict[str, Any]],
    source: str,
) -> dict[str, Any]:
    indexed = pool_term_index(pool)
    seed_urls = [str(seed.get("url") or "") for seed in seeds if seed.get("url")]
    for term in unique_keywords(terms, len(terms)):
        if term in indexed:
            entry = indexed[term]
            entry["updatedAt"] = now_iso()
            entry["learnedCount"] = int(entry.get("learnedCount") or 0) + 1
            entry["lastLearnedRunId"] = run_id
            sources = list(entry.get("sources") or [])
            if source not in sources:
                sources.append(source)
            entry["sources"] = sources
            continue
        entry = {
            "term": term,
            "status": "active",
            "createdAt": now_iso(),
            "updatedAt": now_iso(),
            "sources": [source],
            "learnedCount": 1,
            "lastLearnedRunId": run_id,
            "seedUrls": seed_urls[:10],
            "timesSearched": 0,
            "lastSearchedAt": "",
            "lastCandidateCount": 0,
            "lastApprovedCount": 0,
        }
        pool.setdefault("terms", []).append(entry)
        indexed[term] = entry
    pool["updatedAt"] = now_iso()
    return pool


def active_pool_terms(pool: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for entry in pool.get("terms") or []:
        if not isinstance(entry, dict):
            continue
        if clean_text(entry.get("status") or "active").lower() not in {"active", ""}:
            continue
        term = normalize_keyword(entry.get("term"))
        if term and keyword_allowed(term) and term not in terms:
            terms.append(term)
    return terms


def select_search_terms_from_pool(
    generated_terms: list[str],
    pool: dict[str, Any],
    *,
    use_pool: bool,
    pool_only: bool,
    max_pool_terms: int,
    shuffle_pool: bool,
) -> tuple[list[str], dict[str, Any]]:
    pool_terms = active_pool_terms(pool) if use_pool or pool_only else []
    if shuffle_pool:
        random.shuffle(pool_terms)
    if max_pool_terms > 0:
        pool_terms = pool_terms[:max_pool_terms]
    terms = pool_terms if pool_only else unique_keywords([*pool_terms, *generated_terms], len(pool_terms) + len(generated_terms))
    return terms, {
        "useKeywordPool": use_pool,
        "poolOnly": pool_only,
        "poolActiveCount": len(active_pool_terms(pool)),
        "selectedPoolCount": len(pool_terms),
        "generatedCount": len(generated_terms),
        "selectedCount": len(terms),
        "maxPoolTerms": max_pool_terms,
        "shufflePool": shuffle_pool,
    }


def update_keyword_pool_search_stats(
    pool: dict[str, Any],
    search_reports: list[dict[str, Any]],
    approved: list[dict[str, Any]],
) -> dict[str, Any]:
    indexed = pool_term_index(pool)
    approved_by_query: dict[str, int] = {}
    for item in approved:
        query = normalize_keyword((item.get("manualDiscovery") or {}).get("sourceQuery"))
        if query:
            approved_by_query[query] = approved_by_query.get(query, 0) + 1
    for report in search_reports:
        query = normalize_keyword(report.get("query"))
        if not query or query not in indexed:
            continue
        entry = indexed[query]
        candidate_count = int(report.get("candidateCount") or 0)
        approved_count = approved_by_query.get(query, 0)
        entry["timesSearched"] = int(entry.get("timesSearched") or 0) + 1
        entry["lastSearchedAt"] = now_iso()
        entry["lastCandidateCount"] = candidate_count
        entry["lastApprovedCount"] = approved_count
        entry["totalCandidateCount"] = int(entry.get("totalCandidateCount") or 0) + candidate_count
        entry["totalApprovedCount"] = int(entry.get("totalApprovedCount") or 0) + approved_count
        entry["updatedAt"] = now_iso()
    pool["updatedAt"] = now_iso()
    return pool


def fallback_keywords(seeds: list[dict[str, Any]], limit: int) -> list[str]:
    base = [
        "single photo upload",
        "portrait transformation",
        "photo to video template",
        "before after portrait",
        "ai portrait prompt",
        "dream portrait template",
        "storybook portrait",
        "creator persona",
        "avatar puzzle challenge",
        "cinematic portrait edit",
    ]
    extracted: list[str] = []
    for seed in seeds:
        text = " ".join(
            [
                seed.get("intro", ""),
                seed.get("autoPrompt", ""),
                seed.get("materialReason", ""),
            ]
        )
        for match in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,24}(?:\s+[A-Za-z][A-Za-z0-9_-]{2,24}){0,3}", text):
            extracted.append(match)
    return unique_keywords([*base, *extracted], limit)


def generate_search_terms(seeds: list[dict[str, Any]], max_terms: int, model: str) -> tuple[list[str], dict[str, Any]]:
    env = load_env()
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    if not seeds:
        return [], {"mode": "empty_seeds", "reason": "no high-quality Instagram seeds found"}
    seed_payload = [
        {
            "url": seed.get("url"),
            "intro": seed.get("intro"),
            "autoPrompt": seed.get("autoPrompt"),
            "materialAcceptance": seed.get("materialAcceptance"),
            "materialReason": seed.get("materialReason"),
        }
        for seed in seeds
    ]
    if not api_key:
        keywords = fallback_keywords(seeds, max_terms)
        return keywords, {"mode": "fallback", "reason": "OPENROUTER_API_KEY missing", "searchTerms": keywords}
    prompt = (
        "You are extracting Instagram search keywords from historically high-quality Instagram materials. "
        "Use the local product manual, and generate English Instagram search terms that can find similar public posts/reels for Evoke, Toki, Kavi, and Avatar. "
        "Return JSON only: {\"searchTerms\": [string], \"termReasons\": [{\"term\": string, \"reason\": string}], \"rejectedDirections\": [string]}. "
        f"Generate at most {max_terms} unique English search terms. Each term must be short, 2-6 words, product-aligned, and suitable for Instagram search/tag pages. "
        "Prefer single-photo upload, before/after, portrait transformation, photo-to-video, creator persona, dream/storybook portrait, avatar puzzle, and reusable ad/template material. "
        "Do not include celebrity gossip, paparazzi, leaks, spoilers, pure IP copies, edge-bait, politics, crypto, hardware, pure memes, or broad entertainment terms.\n\n"
        f"Local product manual:\n{load_product_manual()}\n\n"
        f"High-quality Instagram seed materials:\n{json.dumps(seed_payload, ensure_ascii=False)}"
    )
    compact_seed_payload = [
        {
            "url": seed.get("url"),
            "intro": clean_text(seed.get("intro"), max_len=260),
            "materialReason": clean_text(seed.get("materialReason"), max_len=180),
        }
        for seed in seeds
    ]
    retry_prompt = (
        "The previous keyword extraction response failed JSON parsing. "
        "Return only valid compact JSON with exactly this shape: "
        "{\"searchTerms\":[\"short english term\"],\"termReasons\":[],\"rejectedDirections\":[]}. "
        f"Generate at most {max_terms} Instagram search terms. Each term must be 2-6 English words and product-aligned for Evoke, Toki, Kavi, or Avatar. "
        "Do not output metadata words such as prompt, cta, legacy, logic, product_v2, or broad unsafe/celebrity/IP terms. "
        "Useful directions: single-photo upload, before/after, portrait transformation, photo-to-video, creator persona, dream/storybook portrait, avatar puzzle, reusable ad template.\n"
        f"Compact seed materials:\n{json.dumps(compact_seed_payload, ensure_ascii=False)}"
    )
    last_error = ""
    for attempt, (attempt_prompt, max_tokens) in enumerate([(prompt, 2000), (retry_prompt, 1200)], 1):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": attempt_prompt}],
                    "response_format": {"type": "json_object"},
                    "max_tokens": max_tokens,
                },
                timeout=75,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"].get("content") or "{}"
            parsed = json.loads(strip_json_fence(content))
            raw_terms = parsed.get("searchTerms", []) if isinstance(parsed, dict) else []
            keywords = unique_keywords(raw_terms, max_terms)
            if not keywords:
                raise ValueError("model returned no valid keywords")
            return keywords, {"mode": "model", "model": model, "attempt": attempt, "raw": parsed, "searchTerms": keywords}
        except Exception as exc:
            last_error = str(exc)
            continue
    try:
        raise ValueError(last_error)
    except Exception as exc:
        keywords = fallback_keywords(seeds, max_terms)
        return keywords, {"mode": "fallback", "reason": str(exc), "model": model, "searchTerms": keywords}


def cookie_header_to_playwright_cookies(header: str, domain: str) -> list[dict[str, Any]]:
    parsed = SimpleCookie()
    parsed.load(header or "")
    cookies: list[dict[str, Any]] = []
    for name, morsel in parsed.items():
        value = morsel.value
        if not name or value is None:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": morsel["path"] or "/",
                "secure": True,
                "httpOnly": False,
            }
        )
    return cookies


def read_json_cookies_for_playwright(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    cookies: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for domain in ["instagram.com", "www.instagram.com", ".instagram.com"]:
            raw = payload.get(domain)
            if isinstance(raw, str) and raw.strip():
                cookies.extend(cookie_header_to_playwright_cookies(raw, domain.lstrip(".")))
        return cookies
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            value = str(item.get("value") or "")
            domain = str(item.get("domain") or "").strip()
            if not name or not domain or "instagram.com" not in domain:
                continue
            cookie = {
                "name": name,
                "value": value,
                "domain": domain,
                "path": str(item.get("path") or "/"),
                "secure": bool(item.get("secure", True)),
                "httpOnly": bool(item.get("httpOnly", item.get("http_only", False))),
            }
            expires = item.get("expires") or item.get("expirationDate")
            try:
                expires_int = int(float(expires))
            except (TypeError, ValueError):
                expires_int = 0
            if expires_int > 0:
                cookie["expires"] = expires_int
            cookies.append(cookie)
    return cookies


def read_netscape_cookies_for_playwright(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        return read_json_cookies_for_playwright(path)
    cookies: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line[len("#HttpOnly_") :]
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _include_subdomains, cookie_path, secure, expires, name, value = parts
        if not domain or not name:
            continue
        cookie: dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": cookie_path or "/",
            "httpOnly": http_only,
            "secure": secure.upper() == "TRUE",
        }
        try:
            expiry = int(float(expires))
        except (TypeError, ValueError):
            expiry = 0
        if expiry > 0:
            cookie["expires"] = expiry
        cookies.append(cookie)
    return cookies


def instagram_search_urls(query: str) -> list[str]:
    text = normalize_keyword(query)
    if not text:
        return []
    urls = [f"https://www.instagram.com/explore/search/keyword/?q={quote(text)}"]
    tag = re.sub(r"[^a-zA-Z0-9_]+", "", text.replace(" ", ""))
    if len(tag) >= 2:
        urls.append(f"https://www.instagram.com/explore/tags/{tag}/")
    return urls


def canonical_instagram_url(url: str) -> str:
    text = str(url or "").strip()
    if text.startswith("/"):
        text = f"https://www.instagram.com{text}"
    match = re.search(r"instagram\.com/(p|reel|tv)/([^/?#]+)", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return f"https://www.instagram.com/{match.group(1).lower()}/{match.group(2)}/"


def extract_instagram_links_from_html(html: str, limit: int = 100) -> list[str]:
    links: list[str] = []
    for match in re.finditer(r"""href=["']([^"']+)["']""", html or "", flags=re.IGNORECASE):
        href = unquote(match.group(1))
        clean = canonical_instagram_url(href)
        if clean and clean not in links:
            links.append(clean)
        if len(links) >= limit:
            break
    return links


def parse_timestamp(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        timestamp = int(value)
        if timestamp > 100000000000:
            timestamp = int(timestamp / 1000)
        return timestamp
    text = str(value or "").strip()
    if text.isdigit():
        timestamp = int(text)
        if timestamp > 100000000000:
            timestamp = int(timestamp / 1000)
        return timestamp
    return None


class InstagramAccountSearchClient:
    def __init__(self, cookie_path: Path, *, headless: bool, max_scrolls: int, delay_seconds: float) -> None:
        self.cookie_path = cookie_path
        self.headless = headless
        self.max_scrolls = max_scrolls
        self.delay_seconds = delay_seconds

    def available(self) -> bool:
        return self.cookie_path.exists()

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        links = self.collect_links(query, limit)
        candidates: list[dict[str, Any]] = []
        errors: list[str] = []
        for link in links[:limit]:
            try:
                candidate = self.candidate_from_ytdlp(link)
                candidate["manualDiscovery"] = {"sourceQuery": query, "source": "instagram_account_cookie"}
                candidates.append(candidate)
            except Exception as exc:
                errors.append(f"{link}: {clean_text(exc, max_len=180)}")
        return candidates, {"query": query, "linkCount": len(links), "candidateCount": len(candidates), "errors": errors[:10]}

    def collect_links(self, query: str, limit: int) -> list[str]:
        if not self.cookie_path.exists():
            raise RuntimeError(f"Instagram account cookies file not found: {self.cookie_path}")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("playwright is not installed. Run: python -m pip install playwright && python -m playwright install chromium") from exc
        cookies = read_netscape_cookies_for_playwright(self.cookie_path)
        if not cookies:
            raise RuntimeError(f"Instagram cookies file is empty or invalid: {self.cookie_path}")
        links: list[str] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.headless)
            context = browser.new_context()
            context.add_cookies(cookies)
            page = context.new_page()
            try:
                for url in instagram_search_urls(query):
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    self.assert_logged_in(page)
                    self.collect_page_links(page, links, limit)
                    for _index in range(max(0, self.max_scrolls)):
                        if len(links) >= limit:
                            break
                        page.evaluate("window.scrollBy(0, Math.max(document.body.scrollHeight, 1200))")
                        page.wait_for_timeout(int(max(0.0, self.delay_seconds + random.uniform(0, 0.6)) * 1000))
                        self.assert_logged_in(page)
                        self.collect_page_links(page, links, limit)
                    if len(links) >= limit:
                        break
            finally:
                context.close()
                browser.close()
        return links[:limit]

    def collect_page_links(self, page: Any, links: list[str], limit: int) -> None:
        for link in extract_instagram_links_from_html(page.content(), limit * 3):
            if link not in links:
                links.append(link)
            if len(links) >= limit:
                break

    def assert_logged_in(self, page: Any) -> None:
        current_url = str(getattr(page, "url", "") or "").lower()
        body = page.content().lower()[:2400]
        if any(marker in current_url for marker in ["/accounts/login", "checkpoint", "challenge"]):
            raise RuntimeError("Instagram cookies appear expired or account checkpoint/login is required.")
        if any(marker in body for marker in ["log in to instagram", "verify your account", "suspicious login", "enter your security code"]):
            raise RuntimeError("Instagram cookies appear expired or account checkpoint/login is required.")

    def candidate_from_ytdlp(self, url: str) -> dict[str, Any]:
        try:
            import yt_dlp  # type: ignore
        except ImportError as exc:
            raise RuntimeError("yt-dlp is not installed. Install project requirements first.") from exc
        cookiefile_copy = ""
        if self.cookie_path.exists() and self.cookie_path.suffix.lower() != ".json":
            fd, cookiefile_copy = tempfile.mkstemp(
                prefix="ins_ytdlp_cookies_",
                suffix=self.cookie_path.suffix or ".txt",
            )
            os.close(fd)
            shutil.copyfile(self.cookie_path, cookiefile_copy)
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "extract_flat": False,
            "ignore_no_formats_error": True,
        }
        if cookiefile_copy:
            options["cookiefile"] = cookiefile_copy
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
        finally:
            if cookiefile_copy:
                try:
                    Path(cookiefile_copy).unlink(missing_ok=True)
                except Exception:
                    pass
        info = info if isinstance(info, dict) else {}
        timestamp = parse_timestamp(info.get("timestamp") or info.get("release_timestamp"))
        parsed = urlparse(url)
        path = parsed.path.lower()
        media_type = "reel" if "/reel/" in path else "image"
        username = clean_text(info.get("uploader_id") or info.get("uploader") or info.get("channel"))
        caption = clean_text(info.get("description") or info.get("title"), max_len=2200)
        thumbnail = clean_text(info.get("thumbnail"))
        return {
            "url": clean_text(info.get("webpage_url") or url),
            "permalink": clean_text(info.get("webpage_url") or url),
            "caption": caption,
            "title": caption,
            "description": caption,
            "ownerUsername": username,
            "username": username,
            "timestamp": timestamp,
            "taken_at": timestamp,
            "likesCount": info.get("like_count") or 0,
            "commentsCount": info.get("comment_count") or 0,
            "media_type": media_type,
            "type": media_type,
            "thumbnail": thumbnail,
            "displayUrl": thumbnail,
            "raw_source": {"yt_dlp": info},
        }


def rapidapi_key_chain(env: dict[str, str]) -> list[str]:
    keys: list[str] = []
    for name in ["INS_RAPIDAPI_KEY", "RAPIDAPI_KEY_2", "RAPIDAPI_KEY"]:
        value = os.environ.get(name) or env.get(name, "")
        if value and value not in keys:
            keys.append(value)
    return keys


def find_list_by_keys(value: Any, keys: list[str]) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    for key in keys:
        child = value.get(key)
        if isinstance(child, list):
            return child
        if isinstance(child, dict):
            nested = find_list_by_keys(child, keys)
            if nested:
                return nested
    for child in value.values():
        nested = find_list_by_keys(child, keys)
        if nested:
            return nested
    return []


def flatten_instagram_posts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [post for item in value for post in flatten_instagram_posts(item)]
    if not isinstance(value, dict):
        return []
    if isinstance(value.get("node"), dict):
        return flatten_instagram_posts(value["node"])
    markers = {
        "caption",
        "shortcode",
        "shortCode",
        "code",
        "taken_at",
        "timestamp",
        "like_count",
        "likesCount",
        "commentsCount",
        "displayUrl",
        "display_url",
        "url",
        "permalink",
        "postUrl",
    }
    if any(key in value for key in markers):
        return [value]
    posts = find_list_by_keys(
        value,
        [
            "items",
            "posts",
            "data",
            "results",
            "edges",
            "media",
            "medias",
            "user_posts",
            "timeline_media",
        ],
    )
    return [post for post in flatten_instagram_posts(posts) if post]


class InstagramRapidApiSearchClient:
    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self.search_host = os.environ.get("INS_RAPIDAPI_SEARCH_HOST") or env.get("INS_RAPIDAPI_SEARCH_HOST", "")
        self.search_path = os.environ.get("INS_RAPIDAPI_SEARCH_PATH") or env.get("INS_RAPIDAPI_SEARCH_PATH", "/search")
        self.search_method = (os.environ.get("INS_RAPIDAPI_SEARCH_METHOD") or env.get("INS_RAPIDAPI_SEARCH_METHOD", "GET")).upper()
        self.query_param = os.environ.get("INS_RAPIDAPI_SEARCH_QUERY_PARAM") or env.get("INS_RAPIDAPI_SEARCH_QUERY_PARAM", "") or "q"
        self.keys = rapidapi_key_chain(env)

    def available(self) -> bool:
        return bool(self.search_host and self.keys)

    def headers(self, host: str, key: str) -> dict[str, str]:
        return {"X-RapidAPI-Key": key, "X-RapidAPI-Host": host, "Content-Type": "application/json"}

    def search(self, query: str, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not self.available():
            raise RuntimeError("Instagram RapidAPI search is not configured")
        params = {
            "page": 1,
            "perPage": min(max(1, limit), 30),
            "sort": "-score",
            "socialTypes": "INST",
            "trackTotal": "true",
            self.query_param: query,
        }
        url = f"https://{self.search_host}{self.search_path}"
        last_response: requests.Response | None = None
        for index, key in enumerate(self.keys):
            response = (
                requests.post(url, headers=self.headers(self.search_host, key), json=params, timeout=45)
                if self.search_method == "POST"
                else requests.get(url, headers=self.headers(self.search_host, key), params=params, timeout=45)
            )
            last_response = response
            if response.status_code in {401, 403, 429} and index < len(self.keys) - 1:
                continue
            response.raise_for_status()
            payload = response.json()
            posts = flatten_instagram_posts(payload)
            candidates: list[dict[str, Any]] = []
            for post in posts[:limit]:
                updated = dict(post)
                updated["manualDiscovery"] = {"sourceQuery": query, "source": "instagram_rapidapi_search"}
                candidates.append(updated)
            return candidates, {
                "query": query,
                "provider": "rapidapi",
                "host": self.search_host,
                "path": self.search_path,
                "candidateCount": len(candidates),
            }
        if last_response is not None:
            last_response.raise_for_status()
        raise RuntimeError("Instagram RapidAPI search failed")


def load_cached_raw_candidates() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    latest_path = RUN_ROOT / "latest.json"
    if not latest_path.exists():
        raise FileNotFoundError(f"Manual INS discovery cache not found: {latest_path}")
    latest = json.loads(latest_path.read_text(encoding="utf-8-sig"))
    raw_path = Path(((latest.get("paths") or {}).get("rawCandidates") or ""))
    if raw_path and not raw_path.is_absolute():
        raw_path = BASE_DIR / raw_path
    if not raw_path.exists():
        raw = latest.get("rawCandidates") or []
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)], {"cache": str(latest_path)}
        raise FileNotFoundError(f"Cached raw candidates not found: {raw_path}")
    data = json.loads(raw_path.read_text(encoding="utf-8-sig"))
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else [], {"cache": str(raw_path)}


def engagement_score(item: dict[str, Any]) -> int:
    score = item.get("heatValue")
    try:
        if score not in (None, ""):
            return int(float(score))
    except (TypeError, ValueError):
        pass
    return raw_ins_heat(item)


def raw_ins_heat(item: dict[str, Any]) -> int:
    return int(item.get("diggCount") or item.get("likeCount") or 0) + INS_COMMENT_WEIGHT * int(item.get("commentCount") or 0)


def compressed_ins_heat_score(raw_score: float, high_score_k: float) -> float:
    if raw_score <= 100:
        return raw_score
    over_score = raw_score - 100
    return 100 + 50 * over_score / (over_score + max(1.0, high_score_k))


def _db_path_from_rules(rules: dict[str, Any]) -> Path:
    raw = str((rules.get("database") or {}).get("path") or "skill_runs/instagram/instagram_hotspots.sqlite")
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


def _sqlite_recent_baselines(rules: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], float, int]:
    cfg = rules.get("hot_post", {}) if isinstance(rules.get("hot_post"), dict) else {}
    baseline_days = int(cfg.get("baseline_days", 7) or 7)
    db_path = _db_path_from_rules(rules)
    if not db_path.exists():
        return {}, 0.0, 0
    cutoff_ts = int((datetime.now() - timedelta(days=baseline_days)).timestamp())
    by_creator: dict[str, list[int]] = {}
    all_heats: list[int] = []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            for row in conn.execute(
                "select username, like_count, comment_count from posts where publish_ts >= ?",
                (cutoff_ts,),
            ):
                heat = int(row["like_count"] or 0) + INS_COMMENT_WEIGHT * int(row["comment_count"] or 0)
                username = clean_text(row["username"]).lower()
                if username:
                    by_creator.setdefault(username, []).append(heat)
                all_heats.append(heat)
    except sqlite3.Error:
        return {}, 0.0, 0
    baselines = {
        username: {"count": len(values), "avgHeat": sum(values) / len(values)}
        for username, values in by_creator.items()
        if values
    }
    global_median = float(statistics.median(all_heats)) if all_heats else 0.0
    return baselines, global_median, len(all_heats)


def apply_manual_ins_heat_scores(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    if not items:
        return []
    cfg = rules.get("hot_post", {}) if isinstance(rules.get("hot_post"), dict) else {}
    baseline_days = int(cfg.get("baseline_days", 7) or 7)
    high_score_k = max(1.0, float(cfg.get("high_score_k", 600.0) or 600.0))
    sqlite_baselines, global_median, global_count = _sqlite_recent_baselines(rules)
    if global_median <= 0:
        run_heats = [raw_ins_heat(item) for item in items if raw_ins_heat(item) > 0]
        global_median = float(statistics.median(run_heats)) if run_heats else 1.0
        global_count = len(run_heats)

    updated_items: list[dict[str, Any]] = []
    for item in items:
        updated = dict(item)
        author = updated.get("authorMeta") if isinstance(updated.get("authorMeta"), dict) else {}
        username = clean_text(
            author.get("uniqueId")
            or author.get("nickName")
            or updated.get("ownerUsername")
            or updated.get("username")
        ).lower()
        creator = sqlite_baselines.get(username) or {}
        creator_count = int(creator.get("count") or 0)
        if creator_count >= INS_BASELINE_MIN_CREATOR_POSTS and float(creator.get("avgHeat") or 0) > 0:
            baseline = float(creator["avgHeat"])
            baseline_type = "creator_7d_average"
        else:
            baseline = max(1.0, global_median)
            baseline_type = "global_7d_median"
        raw_heat = raw_ins_heat(updated)
        heat_ratio = raw_heat / baseline if baseline > 0 else 0.0
        raw_score = heat_ratio * 100
        heat_score = compressed_ins_heat_score(raw_score, high_score_k)
        updated["heatValue"] = round(heat_score, 4)
        updated["insManualHeat"] = {
            "rawHeat": raw_heat,
            "commentWeight": INS_COMMENT_WEIGHT,
            "baselineHeat": baseline,
            "baselineType": baseline_type,
            "baselineDays": baseline_days,
            "creatorHistoryCount": creator_count,
            "globalBaselinePostCount": global_count,
            "heatRatio": heat_ratio,
            "rawInsHeatScore": raw_score,
            "insHeatScore": heat_score,
            "highScoreK": high_score_k,
            "compression": "tik_x_style_over_100",
        }
        updated_items.append(updated)
    return updated_items


def item_key(item: dict[str, Any]) -> str:
    return clean_text(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url") or item.get("permalink") or item.get("upsertKey"))


def dedupe_raw_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = clean_text(item.get("url") or item.get("permalink") or item.get("shortcode") or item.get("id"))
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        result.append(item)
    return result


def normalize_candidates(raw_candidates: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in raw_candidates:
        item = normalize_ins_post(raw, rules)
        manual = dict(raw.get("manualDiscovery") or {})
        item["manualDiscovery"] = {
            **manual,
            "workflow": "ins_keyword_discovery",
            "source": manual.get("source") or "instagram_account_cookie",
        }
        normalized.append(item)
    return apply_manual_ins_heat_scores(normalized, rules)


def apply_engagement_gate(
    items: list[dict[str, Any]],
    min_likes: int,
    min_comments: int,
    top_n: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    passed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in items:
        likes = int(item.get("diggCount") or item.get("likeCount") or 0)
        comments = int(item.get("commentCount") or 0)
        updated = dict(item)
        updated["manualDiscovery"] = {
            **dict(updated.get("manualDiscovery") or {}),
            "engagementScore": raw_ins_heat(updated),
            "insHeatScore": updated.get("heatValue"),
            "insHeatDetails": updated.get("insManualHeat") or {},
            "engagementGate": {"minLikes": min_likes, "minComments": min_comments},
        }
        if likes >= min_likes and comments >= min_comments:
            passed.append(updated)
        else:
            updated["manualDiscovery"]["rejectReason"] = "engagement_gate_failed"
            blocked.append(updated)
    passed.sort(key=lambda item: float(item.get("heatValue") or engagement_score(item)), reverse=True)
    return passed[: max(1, top_n)], blocked


def audit_candidates(items: list[dict[str, Any]], rules: dict[str, Any], variant: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stats: dict[str, Any] = {"input": len(items)}
    if not items:
        return [], stats
    safe_items, blocked_safety = apply_ins_safety_review(items, rules)
    stats["blockedSafety"] = len(blocked_safety)
    stats["afterSafety"] = len(safe_items)
    fitted = apply_product_fit(safe_items, rules)
    relevant = [item for item in fitted if (item.get("insProductFit") or {}).get("isRelevant")]
    stats["afterKeywordProductFit"] = len(relevant)
    reviewed_product, blocked_product = apply_product_v2_review(relevant, rules)
    stats["blockedProductManual"] = len(blocked_product)
    stats["afterProductManual"] = len(reviewed_product)
    ua_rules = dict(rules)
    ua_cfg = dict(ua_rules.get("ua_material_review") or {})
    ua_cfg["review_pool_size"] = max(1, len(safe_items))
    ua_cfg["daily_max"] = max(1, len(safe_items))
    ua_cfg["daily_min"] = 0
    ua_rules["ua_material_review"] = ua_cfg
    ua_candidates = mark_ua_material_candidates(
        sorted(safe_items, key=engagement_score, reverse=True),
        ua_rules,
        platform="ins",
        reason="manual Instagram keyword discovery candidate",
    )
    reviewed_ua, blocked_ua = apply_ua_material_review(ua_candidates, rules, platform="ins")
    stats["blockedUaMaterial"] = len(blocked_ua)
    stats["afterUaMaterial"] = len(reviewed_ua)
    combined = merge_unique_preserving_ua_material(reviewed_product, reviewed_ua)
    if combined:
        combined = apply_visual_dedupe(combined, platform="ins", top_n=len(combined))[0]
    stats["afterVisualDedupe"] = len(combined)
    combined = mark_pipeline_variant(combined, variant)
    combined = force_ua_material_push_object(combined)
    combined = apply_feedback_hard_filter(combined, variant=variant, label="manual_ins_keyword_discovery")
    approved = list(combined)
    approved.sort(key=engagement_score, reverse=True)
    stats["approved"] = len(approved)
    return approved, stats


def summarize_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    product_fit = item.get("insProductFit") if isinstance(item.get("insProductFit"), dict) else {}
    product_review = item.get("productManualReview") if isinstance(item.get("productManualReview"), dict) else {}
    ua_review = item.get("uaMaterialReview") if isinstance(item.get("uaMaterialReview"), dict) else {}
    return {
        "rank": index,
        "url": item.get("hotspotUrl") or item.get("webVideoUrl") or "",
        "author": author.get("nickName") or author.get("uniqueId") or "",
        "caption": clean_text(item.get("text") or item.get("title") or item.get("desc"), max_len=400),
        "likes": item.get("diggCount") or item.get("likeCount") or 0,
        "comments": item.get("commentCount") or 0,
        "heat": item.get("heatValue") or engagement_score(item),
        "mediaType": item.get("mediaType"),
        "pushObject": "ALL",
        "primaryProduct": product_review.get("primaryProduct") or ua_review.get("recommendedProduct") or product_fit.get("primaryProduct") or "",
        "sourceQuery": (item.get("manualDiscovery") or {}).get("sourceQuery", ""),
        "productReviewReason": product_review.get("reason", ""),
        "uaReviewReason": ua_review.get("reason", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual Instagram keyword discovery from high-quality Feishu feedback seeds.")
    parser.add_argument("--lookback-days", type=int, default=60)
    parser.add_argument("--max-seeds", type=int, default=20)
    parser.add_argument("--max-search-terms", type=int, default=30)
    parser.add_argument("--max-links-per-query", type=int, default=None)
    parser.add_argument("--max-scrolls", type=int, default=None)
    parser.add_argument("--min-likes", type=int, default=500)
    parser.add_argument("--min-comments", type=int, default=10)
    parser.add_argument("--engagement-top-n", type=int, default=60)
    parser.add_argument("--from-cache", action="store_true")
    parser.add_argument("--allow-rapidapi", action="store_true", help="Allow configured Instagram RapidAPI search only if cookie search has no output.")
    parser.add_argument("--pool-only", action="store_true", help="Search only the existing persistent keyword pool; skip Feishu seed learning.")
    parser.add_argument("--disable-keyword-pool", action="store_true", help="Do not read or update the persistent keyword pool for this run.")
    parser.add_argument("--max-pool-terms", type=int, default=None, help="Limit active pool terms searched in this run; 0 means all active terms.")
    parser.add_argument("--shuffle-pool", action="store_true", help="Shuffle pool terms before applying --max-pool-terms.")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--output-dir", type=Path, default=RUN_ROOT)
    return parser.parse_args()


def main() -> int:
    env = load_env()
    args = parse_args()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = args.output_dir if args.output_dir.is_absolute() else BASE_DIR / args.output_dir
    run_dir = output_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    model = os.environ.get("INS_MANUAL_REVIEW_MODEL") or env.get("INS_MANUAL_REVIEW_MODEL") or os.environ.get("OPENROUTER_MODEL") or env.get("OPENROUTER_MODEL") or DEFAULT_MODEL
    use_keyword_pool = not bool(args.disable_keyword_pool)
    max_pool_terms = args.max_pool_terms if args.max_pool_terms is not None else env_int("INS_MANUAL_MAX_POOL_TERMS", DEFAULT_MAX_POOL_TERMS, env)
    shuffle_pool = bool(args.shuffle_pool or env_bool("INS_MANUAL_SHUFFLE_POOL", False, env))
    pool_path = keyword_pool_path(output_root, env)
    keyword_pool = load_keyword_pool(pool_path) if use_keyword_pool or args.pool_only else {"schemaVersion": 1, "terms": []}
    cookie_raw = os.environ.get("INS_MANUAL_ACCOUNT_COOKIES") or env.get("INS_MANUAL_ACCOUNT_COOKIES") or DEFAULT_ACCOUNT_COOKIE
    cookie_path = Path(cookie_raw)
    if not cookie_path.is_absolute():
        cookie_path = BASE_DIR / cookie_path
    max_links_per_query = args.max_links_per_query or env_int("INS_MANUAL_MAX_LINKS_PER_QUERY", DEFAULT_MAX_LINKS_PER_QUERY, env)
    max_scrolls = args.max_scrolls if args.max_scrolls is not None else env_int("INS_MANUAL_MAX_SCROLLS", DEFAULT_MAX_SCROLLS, env)
    delay_seconds = env_float("INS_MANUAL_SEARCH_DELAY_SECONDS", DEFAULT_DELAY_SECONDS, env)
    headless = env_bool("INS_MANUAL_SEARCH_HEADLESS", True, env)
    allow_rapidapi = bool(args.allow_rapidapi or env_bool("INS_MANUAL_ALLOW_RAPIDAPI", False, env))
    rules = load_ins_rules()
    variant = resolve_pipeline_variant()
    errors: list[str] = []

    seeds: list[dict[str, Any]] = []
    seed_stats: dict[str, Any] = {}
    keyword_meta: dict[str, Any] = {}
    search_terms: list[str] = []
    search_reports: list[dict[str, Any]] = []
    if args.from_cache:
        raw_candidates, cache_meta = load_cached_raw_candidates()
        keyword_meta = {"mode": "from_cache", **cache_meta}
    else:
        learned_terms: list[str] = []
        if args.pool_only:
            seed_stats = {"skipped": "pool_only"}
            keyword_meta = {"mode": "pool_only"}
        else:
            try:
                seeds, seed_stats = collect_high_quality_seeds(args.lookback_days, args.max_seeds)
            except Exception as exc:
                errors.append(f"seed_fetch_failed: {exc}")
                seeds = []
                seed_stats = {"error": str(exc)}
            learned_terms, keyword_meta = generate_search_terms(seeds, args.max_search_terms, model)
            if use_keyword_pool:
                keyword_pool = update_keyword_pool_with_learned_terms(
                    keyword_pool,
                    learned_terms,
                    run_id=run_id,
                    seeds=seeds,
                    source="feishu_high_quality_seed_learning",
                )
        search_terms, pool_selection = select_search_terms_from_pool(
            learned_terms,
            keyword_pool,
            use_pool=use_keyword_pool,
            pool_only=bool(args.pool_only),
            max_pool_terms=max(0, int(max_pool_terms or 0)),
            shuffle_pool=shuffle_pool,
        )
        keyword_meta = {
            **keyword_meta,
            "learnedTerms": learned_terms,
            "keywordPool": {
                **pool_selection,
                "path": pool_path.relative_to(BASE_DIR).as_posix() if pool_path.is_relative_to(BASE_DIR) else str(pool_path),
            },
        }
        raw_candidates: list[dict[str, Any]] = []
        if not cookie_path.exists():
            errors.append(f"instagram_cookie_missing: {cookie_path}")
        elif not search_terms:
            errors.append("no_search_terms")
        else:
            client = InstagramAccountSearchClient(cookie_path, headless=headless, max_scrolls=max_scrolls, delay_seconds=delay_seconds)
            for index, query in enumerate(search_terms, 1):
                print(f"  - INS manual cookie search {index}/{len(search_terms)}: {query}", flush=True)
                try:
                    candidates, report = client.search(query, max_links_per_query)
                    raw_candidates.extend(candidates)
                    search_reports.append(report)
                except Exception as exc:
                    error = f"{query}: {exc}"
                    errors.append(error)
                    search_reports.append({"query": query, "provider": "cookie", "error": str(exc)})
        if allow_rapidapi and search_terms and not raw_candidates:
            rapidapi_client = InstagramRapidApiSearchClient(env)
            if not rapidapi_client.available():
                errors.append("RapidAPI fallback requested but INS_RAPIDAPI_SEARCH_HOST or keys are missing.")
            else:
                for index, query in enumerate(search_terms, 1):
                    print(f"  - INS manual RapidAPI fallback {index}/{len(search_terms)}: {query}", flush=True)
                    try:
                        candidates, report = rapidapi_client.search(query, max_links_per_query)
                        raw_candidates.extend(candidates)
                        search_reports.append(report)
                    except Exception as exc:
                        errors.append(f"rapidapi {query}: {exc}")
                        search_reports.append({"query": query, "provider": "rapidapi", "error": str(exc)})
    raw_candidates = dedupe_raw_candidates(raw_candidates)
    normalized = normalize_candidates(raw_candidates, rules)
    engagement_passed, engagement_blocked = apply_engagement_gate(
        normalized,
        min_likes=args.min_likes,
        min_comments=args.min_comments,
        top_n=args.engagement_top_n,
    )
    approved, audit_stats = audit_candidates(engagement_passed, rules, variant)
    approved = [{**item, "pushObject": "ALL"} for item in approved]
    if (use_keyword_pool or args.pool_only) and not args.from_cache:
        keyword_pool = update_keyword_pool_search_stats(keyword_pool, search_reports, approved)
        atomic_write_json(pool_path, keyword_pool)
    rejected_summary = [
        summarize_item(item, index)
        for index, item in enumerate(sorted(engagement_blocked, key=engagement_score, reverse=True), 1)
    ]
    approved_summary = [summarize_item(item, index) for index, item in enumerate(approved, 1)]

    paths = {
        "seeds": (run_dir / "seeds.json").relative_to(BASE_DIR).as_posix(),
        "keywords": (run_dir / "keywords.json").relative_to(BASE_DIR).as_posix(),
        "rawCandidates": (run_dir / "raw_candidates.json").relative_to(BASE_DIR).as_posix(),
        "engagementPassed": (run_dir / "engagement_passed.json").relative_to(BASE_DIR).as_posix(),
        "approved": (run_dir / "approved.json").relative_to(BASE_DIR).as_posix(),
        "rejected": (run_dir / "rejected.json").relative_to(BASE_DIR).as_posix(),
        "keywordPool": pool_path.relative_to(BASE_DIR).as_posix() if pool_path.is_relative_to(BASE_DIR) else str(pool_path),
    }
    atomic_write_json(BASE_DIR / paths["seeds"], seeds)
    atomic_write_json(BASE_DIR / paths["keywords"], {"searchTerms": search_terms, "keywordMeta": keyword_meta})
    atomic_write_json(BASE_DIR / paths["rawCandidates"], raw_candidates)
    atomic_write_json(BASE_DIR / paths["engagementPassed"], engagement_passed)
    atomic_write_json(BASE_DIR / paths["approved"], approved)
    atomic_write_json(BASE_DIR / paths["rejected"], rejected_summary)
    report = {
        "schemaVersion": 1,
        "runId": run_id,
        "generatedAt": now_iso(),
        "workflow": "manual_instagram_keyword_discovery",
        "dryRun": True,
        "writesFeishu": False,
        "pushesFeishu": False,
        "variant": variant,
        "source": "cache" if args.from_cache else "feishu_high_quality_seeds",
        "seedStats": seed_stats,
        "seedCount": len(seeds),
        "searchTerms": search_terms,
        "searchTermCount": len(search_terms),
        "keywordPool": {
            "enabled": bool(use_keyword_pool or args.pool_only),
            "poolOnly": bool(args.pool_only),
            "path": paths["keywordPool"],
            "activeCount": len(active_pool_terms(keyword_pool)),
            "maxPoolTerms": max_pool_terms,
            "shufflePool": shuffle_pool,
        },
        "searchReports": search_reports,
        "rawCandidateCount": len(raw_candidates),
        "normalizedCandidateCount": len(normalized),
        "engagementGate": {
            "minLikes": args.min_likes,
            "minComments": args.min_comments,
            "topN": args.engagement_top_n,
            "passed": len(engagement_passed),
            "blocked": len(engagement_blocked),
        },
        "auditStats": audit_stats,
        "approvedCount": len(approved),
        "approved": approved_summary,
        "rejectedEngagementSample": rejected_summary[:30],
        "paths": paths,
        "errors": errors,
    }
    atomic_write_json(run_dir / "report.json", report)
    atomic_write_json(output_root / "latest.json", report)
    print(json.dumps({"runId": run_id, "approvedCount": len(approved), "latest": str(output_root / "latest.json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
