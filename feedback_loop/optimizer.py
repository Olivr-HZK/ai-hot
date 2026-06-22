from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
FEEDBACK_LOOP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "scripts"))
sys.path.insert(0, str(FEEDBACK_LOOP_DIR))

from env_utils import ROOT_ENV_FILE, env_bool, load_env
from feedback_field_utils import normalize_acceptance
from feedback_rules import RULES_FILE, deep_merge, load_feedback_rules, validate_feedback_rules
from feishu_feedback import collect_recent_feedback


BACKUP_DIR = BASE_DIR / "skill_runs" / "feedback" / "backups"
FEEDBACK_DIR = BASE_DIR / "skill_runs" / "feedback"
SCORING_ENV_KEYS = {
    "scoring": {
        "play_weight": "SCORING_PLAY_WEIGHT",
        "like_weight": "SCORING_LIKE_WEIGHT",
        "comment_weight": "SCORING_COMMENT_WEIGHT",
        "gravity": "SCORING_GRAVITY",
        "high_score_k": "SCORING_HIGH_SCORE_K",
    },
    "x_scoring": {
        "play_weight": "X_SCORING_PLAY_WEIGHT",
        "like_weight": "X_SCORING_LIKE_WEIGHT",
        "comment_weight": "X_SCORING_COMMENT_WEIGHT",
        "gravity": "X_SCORING_GRAVITY",
        "high_score_k": "X_SCORING_HIGH_SCORE_K",
    },
}
MATERIAL_ACCEPTANCE_SCORES = {"\u9ad8": 1.0, "\u4e2d": 0.5, "\u4f4e": -1.0, "\u5426\u51b3": -1.0}
TIKTOK_MAX_SEARCH_QUERIES = 10
TIKTOK_AI_SEARCH_COUNT = 5
TIKTOK_NON_AI_SEARCH_COUNT = 5
TIKTOK_AI_SEARCH_QUERIES = [
    "photo to video ai",
    "ai action figure",
    "ai emote face animation",
    "ai selfie video",
    "ai viral effect 3d figure",
    "ai avatar jigsaw",
    "ai clay avatar puzzle",
    "ai photo enhancer before after",
]
TIKTOK_NON_AI_SEARCH_QUERIES = [
    "photo transition template",
    "avatar puzzle challenge",
    "before after photo template",
    "sports highlight template",
    "movie poster transition",
]
TIKTOK_RESULTS_PER_KEYWORD = 35
TIKTOK_KEYWORD_ALLOCATION_TOTAL = TIKTOK_MAX_SEARCH_QUERIES * TIKTOK_RESULTS_PER_KEYWORD
TIKTOK_KEYWORD_ALLOCATION_MIN = 15
TIKTOK_KEYWORD_ALLOCATION_MAX = 50
TIKTOK_KEYWORD_TUNING_WINDOW_DAYS = 7
TIKTOK_KEYWORD_ROTATION_REPLACE_COUNT = 3
TIKTOK_AI_KEYWORD_CANDIDATES = [
    "photo to video ai",
    "ai action figure",
    "ai emote face animation",
    "ai selfie video",
    "ai viral effect 3d figure",
    "ai avatar jigsaw",
    "ai clay avatar puzzle",
    "ai photo enhancer before after",
    "ai portrait template",
    "ai photo trend",
    "ai image to video",
    "ai couple video",
    "ai family photo video",
    "ai old photo restoration",
    "ai avatar puzzle",
    "ai 3d figure",
    "ai collectible figure",
    "ai clay avatar",
    "ai face animation",
    "ai talking photo",
    "ai creator persona",
    "ai streamer transformation",
    "ai dress up template",
    "ai storybook portrait",
    "ai before after photo",
]
TIKTOK_NON_AI_KEYWORD_CANDIDATES = [
    "photo transition template",
    "avatar puzzle challenge",
    "portrait transition template",
    "before after photo template",
    "profile photo trend",
    "creator portrait template",
    "collectible figure trend",
    "photo slideshow template",
    "sports highlight template",
    "athlete celebration edit",
    "sports poster edit",
    "jersey portrait edit",
    "training transformation",
    "match entrance edit",
    "cinematic sports edit",
    "movie poster transition",
    "tv show poster edit",
    "character transformation edit",
    "cinematic trailer edit",
    "red carpet transition",
    "film look portrait",
    "character card edit",
]
TIKTOK_DISALLOWED_QUERY_TOKENS = [
    "gemini rain",
    "google gemini rain",
    "rain ai effect",
    "airain",
    "rainaieffect",
    "rainy embrace",
    "rain couple",
    "rain hug",
    "rain portrait",
    "\u96e8\u4e2d\u5199\u771f",
    "\u96e8\u4e2d\u62e5\u62b1",
    "ai anime",
    "\u0061\u0069\u52a8\u6f2b",
    "ai cat story",
    "ai cat video",
    "gen.pro",
    "ai robot",
    "\u4eba\u5de5\u667a\u80fd\u673a\u5668\u4eba",
]
X_MAX_SEARCH_QUERIES = 20
X_WORKFLOW_QUERY_COUNT = 6
X_AI_MATERIAL_QUERY_COUNT = 7
X_REAL_PHOTO_QUERY_COUNT = 7
X_WORKFLOW_SEARCH_QUERIES = [
    "ChatGPT Seedance iPhone vlog workflow",
    "GPT Images Seedance Suno couple video",
    "GPT Images Seedance prompt workflow",
    "photo to video storyboard prompt",
    "Kavi selfie to video prompt workflow",
    "AI Avatar Jigsaw prompt workflow",
]
X_AI_MATERIAL_SEARCH_QUERIES = [
    "AI photo enhancer before after",
    "AI old photo restoration prompt",
    "AI action figure video prompt",
    "AI selfie video prompt",
    "AI viral effect 3D figure",
    "AI avatar jigsaw puzzle",
    "AI clay avatar prompt",
]
X_REAL_PHOTO_SEARCH_QUERIES = [
    "real person portrait photography",
    "editorial portrait photography",
    "family memory portrait photography",
    "couple photo storyboard photography",
    "old photo restoration reference",
    "creative portrait photography",
    "cinematic portrait photography",
]
X_CORE_SEARCH_QUERIES = X_WORKFLOW_SEARCH_QUERIES
X_DEFAULT_MATERIAL_QUERIES = [*X_AI_MATERIAL_SEARCH_QUERIES, *X_REAL_PHOTO_SEARCH_QUERIES]
X_WORKFLOW_TOKENS = ["chatgpt", "gpt", "seedance", "suno", "workflow", "storyboard", "kavi", "avatar", "jigsaw"]
X_REAL_PHOTO_TOKENS = ["real person", "family", "couple", "old photo", "editorial", "cinematic", "creative", "portrait", "photography"]
X_DISALLOWED_QUERY_TOKENS = [
    "anime",
    "manga",
    "fanart",
    "celebrity",
    "paparazzi",
    "street style",
    "hardware",
    "crypto",
    "web3",
    "bikini",
    "swimsuit",
    "beach girl",
    "sensual",
    "100k",
    "subscribe",
    "subscriber",
    "follower milestone",
]
X_ALLOWED_QUERY_TOKENS = [
    "ai",
    "prompt",
    "workflow",
    "seedance",
    "gpt",
    "kavi",
    "avatar",
    "jigsaw",
    "facebook instant game",
    "photo",
    "portrait",
    "video",
    "storyboard",
    "vlog",
    "cinematic",
    "fashion",
    "editorial",
    "creative",
    "holiday",
    "real person",
]


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def feedback_score(row: dict[str, Any]) -> float:
    values = row.get("material_acceptance_values")
    if not isinstance(values, list) or not values:
        values = [row.get("material_acceptance", "")]
    scores = [MATERIAL_ACCEPTANCE_SCORES[value] for value in (normalize_acceptance(item) for item in values) if value]
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def feedback_window(today: date, days: int) -> tuple[date, date]:
    start = today - timedelta(days=days)
    end = today - timedelta(days=1)
    return start, end


def format_feedback_markdown(rows: list[dict[str, Any]], today: date, days: int) -> str:
    start, end = feedback_window(today, days)
    lines = [
        f"# Social media hotspot feedback: last {days} days\n\n",
        f"- Window: {start.isoformat()} - {end.isoformat()}\n",
        f"- Records: {len(rows)}\n\n",
        "Acceptance values: veto=\u5426\u51b3, high=\u9ad8, medium=\u4e2d, low=\u4f4e. "
        "The single Feishu rating field \u91c7\u7eb3\u610f\u613f maps 1 star to veto, 2 stars to medium, and 3 stars to high.\n\n",
    ]
    for index, row in enumerate(rows, 1):
        push_date = row.get("push_date")
        date_text = push_date.isoformat() if isinstance(push_date, date) else ""
        lines.extend(
            [
                f"## {index}. {row.get('intro') or '(no intro)'}\n",
                f"- Push date: {date_text}\n",
                f"- Platform: {row.get('platform') or ''}\n",
                f"- URL: {row.get('url') or ''}\n",
                f"- Plays/Likes/Comments: {row.get('plays') or 0}/{row.get('likes') or 0}/{row.get('comments') or 0}\n",
                f"- Publish days: {row.get('publish_days') or ''}\n",
                f"- Heat value: {row.get('heat') or ''}\n",
                f"- Material acceptance: {row.get('material_acceptance') or 'not provided'}\n",
                f"- Reason: {row.get('material_reason') or 'not provided'}\n\n",
            ]
        )
    return "".join(lines) if rows else "".join(lines) + "No usable feedback rows.\n"


SENSITIVE_FEEDBACK_PATTERNS = [
    (r"(?i)\bnsfw\b|\bsoft[- ]?porn\b|\bonlyfans\b|\bnude\b|\blingerie\b|\bbikini\b|\bswimsuit\b|\bcleavage\b|\bsexy\b|\bseductive\b", "[adult_or_edge_bait]"),
    (r"(?i)\bwar\b|\belection\b|\bpolitics\b|\bpolitical\b|\bregulator\b", "[sensitive_public_topic]"),
    (r"(?i)\bcrypto\b|\bweb3\b|\btoken\b|\bcoin\b", "[crypto_or_web3]"),
    (r"(?i)\bcelebrity\b|\bpaparazzi\b|\bstreet style\b", "[celebrity_dependent]"),
    (r"\u64e6\u8fb9|\u8272\u60c5|\u6210\u4eba|\u88f8|\u6cf3\u88c5|\u6bd4\u57fa\u5c3c|\u6027\u611f", "[adult_or_edge_bait]"),
    (r"\u653f\u6cbb|\u9009\u4e3e|\u6218\u4e89|\u793e\u4f1a\u8fd0\u52a8", "[sensitive_public_topic]"),
]


def safe_feedback_text(value: Any, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    for pattern, replacement in SENSITIVE_FEEDBACK_PATTERNS:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"https?://\S+", "[url]", text)
    return text[:limit].strip()


def feedback_url_domain(value: Any) -> str:
    match = re.search(r"https?://([^/\s]+)", str(value or ""))
    return match.group(1).lower() if match else ""


def feedback_row_tags(row: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    values = row.get("material_acceptance_values")
    if not isinstance(values, list) or not values:
        values = [row.get("material_acceptance", "")]
    for value in values:
        normalized = normalize_acceptance(value)
        if normalized:
            tags.append(f"material:{normalized}")
    text = " ".join(str(row.get(key, "")) for key in ["intro", "material_reason"] if row.get(key))
    tags.extend(material_keywords(text)[:6])
    return list(dict.fromkeys(tags))[:10]


def format_sanitized_feedback_markdown(rows: list[dict[str, Any]], today: date, days: int, *, compact: bool = False) -> str:
    start, end = feedback_window(today, days)
    lines = [
        f"# Sanitized social media hotspot feedback: last {days} days\n\n",
        f"- Window: {start.isoformat()} - {end.isoformat()}\n",
        f"- Records: {len(rows)}\n",
        "- Raw user text has been redacted into safe labels where needed. Rating 1 star equals veto, 2 stars medium, 3 stars high.\n\n",
    ]
    if not rows:
        return "".join(lines) + "No usable feedback rows.\n"
    for index, row in enumerate(rows, 1):
        push_date = row.get("push_date")
        date_text = push_date.isoformat() if isinstance(push_date, date) else ""
        tags = ", ".join(feedback_row_tags(row)) or "none"
        lines.extend(
            [
                f"## {index}. feedback item\n",
                f"- Push date: {date_text}\n",
                f"- Platform: {row.get('platform') or ''}\n",
                f"- URL domain: {feedback_url_domain(row.get('url')) or 'unknown'}\n",
                f"- Plays/Likes/Comments: {row.get('plays') or 0}/{row.get('likes') or 0}/{row.get('comments') or 0}\n",
                f"- Heat value: {row.get('heat') or ''}\n",
                f"- Material acceptance: {row.get('material_acceptance') or 'not provided'}\n",
                f"- Tags: {tags}\n",
            ]
        )
        if not compact:
            lines.extend(
                [
                    f"- Sanitized intro: {safe_feedback_text(row.get('intro')) or 'not provided'}\n",
                    f"- Sanitized reason: {safe_feedback_text(row.get('material_reason')) or 'not provided'}\n",
                ]
            )
        lines.append("\n")
    return "".join(lines)


def strip_json_fence(content: str) -> str:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def response_content(response: Any) -> str:
    try:
        return response.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
        return ""


def call_ai_optimizer(current_rules: dict[str, Any], rows: list[dict[str, Any]], today: date, days: int) -> dict[str, Any]:
    env = load_env()
    api_key = os.environ.get("OPENAI_API_KEY") or env.get("OPENAI_API_KEY")
    base_url = None
    model = os.environ.get("OPENAI_FEEDBACK_MODEL") or env.get("OPENAI_FEEDBACK_MODEL") or "gpt-5.4"
    provider = "openai"
    if not api_key:
        api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY")
        model = os.environ.get("OPENROUTER_MODEL") or env.get("OPENROUTER_MODEL") or model
        base_url = "https://openrouter.ai/api/v1"
        provider = "openrouter"
    if not api_key:
        raise RuntimeError("No OPENAI_API_KEY or OPENROUTER_API_KEY configured for AI feedback optimization")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package is required for AI feedback optimization") from exc
    prompt = format_sanitized_feedback_markdown(rows, today=today, days=days, compact=False)
    retry_prompt = format_sanitized_feedback_markdown(rows, today=today, days=days, compact=True)
    system_prompt = (
        "You are the rule optimizer for a multi-platform social-media hotspot pipeline. Return JSON only. "
        "The feedback input has been sanitized. Use the structured ratings, tags, platform, and safe summaries; never request raw sensitive text. "
        "For feedback weighting, use the single material rating: 1 star/veto='\u5426\u51b3' score -1, 2 stars/medium='\u4e2d' score 0.5, 3 stars/high='\u9ad8' score +1. "
        "You may update scrape.search_queries for TikTok, scrape.max_search_queries, x_scrape.search_queries for X, x_scrape.max_search_queries, "
        "x_team_demand workflow/photo/reject keywords, quality_thresholds, "
        "filters, audience_targeting, product_targeting, analysis_prompt, learning_summary, scoring.active_parameters for TikTok, and "
        "x_scoring.active_parameters for X. Formula parameters are play_weight, like_weight, comment_weight, "
        "gravity, and high_score_k; keep them inside each scoring section's bounds. "
        "For TikTok, keep max_search_queries exactly 10 with exactly 5 AI-related queries and 5 non-AI material/template queries. "
        "TikTok keyword_allocations are post-processed by the deterministic Stage0 allocator: keep each allocation 15-50 and total 350 if you touch them. "
        "Only choose weekly replacement keywords from scrape.keyword_candidates.ai/non_ai; do not invent candidate-pool entries unless they fit Evoke/Toki/Kavi/Avatar reusable material. Non-AI TikTok candidates may include product templates, sports real-person/effect material, and popular movie/TV real-person/effect material, but must not be generic celebrity gossip, leaks, pure IP copies, edge-bait, or plain entertainment. "
        "If feedback changes add more than 10 TikTok queries, delete the most recently poor-performing matching query types first, especially repeated rain-couple/rain-portrait, AI cat/story, AI anime, AI robot, Gen.pro/script-to-video, and fake-AI CapCut beat-edit directions. "
        "For X, keep max_search_queries exactly 20 and keep the search query mix at 6 product-manual workflow/prompt/storyboard queries, "
        "7 other queries that start with 'AI ', and 7 non-AI real-person or photo-reference material queries. Preserve the six workflow queries "
        "ChatGPT Seedance iPhone vlog workflow, GPT Images Seedance Suno couple video, GPT Images Seedance prompt workflow, "
        "photo to video storyboard prompt, Kavi selfie to video prompt workflow, and AI Avatar Jigsaw prompt workflow. "
        "Only add X queries about Evoke/Toki/Kavi/Avatar, AI workflow, prompts, photo-to-video, avatar puzzle, or reusable real-person visual material; "
        "put celebrity, anime, traditional photography business, creator milestone/subscriber celebration posts, bikini/swimsuit beach-girl bait, hardware, crypto/Web3, and generic entertainment negatives into x_team_demand.reject_keywords instead of X search queries. "
        "Treat cinematic superhero/power-fantasy prompt posts as UA watch/medium and product low unless they show reusable product value."
    )
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)

    def request_rules(feedback_prompt: str, mode: str) -> dict[str, Any]:
        user_prompt = (
            f"Today: {today.isoformat()}\n"
            f"Input mode: {mode}\n\n"
            f"Current rules:\n{json.dumps(current_rules, ensure_ascii=False, indent=2)}\n\n"
            f"Feedback:\n{feedback_prompt}"
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(strip_json_fence(response_content(response)))

    try:
        proposed = request_rules(prompt, "sanitized")
    except Exception as first_exc:
        print(f"[WARN] AI optimization sanitized prompt failed; retrying with compact safe summary: {first_exc}")
        proposed = request_rules(retry_prompt, "compact_safe_summary")
    rules = deep_merge(current_rules, proposed)
    rules["source"] = f"feishu_feedback_ai_{provider}"
    normalize_tiktok_search_queries(rules, [row for row in rows if row_platform(row) == "tiktok"])
    normalize_x_search_queries(rules)
    validate_feedback_rules(rules)
    return rules


def extract_topic(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    for sep in ["+", ":", "|", ","]:
        if sep in cleaned:
            parts = [part.strip() for part in cleaned.split(sep) if part.strip()]
            if parts:
                cleaned = max(parts, key=len)
                break
    return cleaned[:24].strip()


def material_keywords(text: str) -> list[str]:
    haystack = re.sub(r"\s+", " ", str(text or "").strip().lower())
    patterns = [
        (["gemini", "rain"], "gemini rain duplicate template"),
        (["rain", "ai", "effect"], "rain ai effect duplicate template"),
        (["airain"], "rain ai effect duplicate template"),
        (["rainaieffect"], "rain ai effect duplicate template"),
        (["rainy", "embrace"], "rainy embrace duplicate template"),
        (["retro", "poster"], "retro poster"),
        (["movie", "poster"], "movie poster"),
        (["street", "poster"], "street poster"),
        (["rain", "couple"], "rain couple"),
        (["couple", "embrace"], "couple embrace"),
        (["photo", "video"], "photo to video"),
        (["static", "motion"], "static to motion"),
        (["selfie", "prompt"], "selfie prompt"),
        (["prompt", "portrait"], "portrait prompt"),
        (["character", "generator"], "character generator"),
        (["outfit"], "outfit transformation"),
        (["makeup"], "makeup transformation"),
        (["hairstyle"], "hairstyle transformation"),
        (["baseball"], "baseball trend"),
        (["dance"], "dance template"),
        (["sticker"], "sticker template"),
        (["mini", "doll"], "mini doll"),
        (["rain", "hug"], "rain hug"),
        (["rain", "couple"], "rain couple"),
        (["gen.pro"], "gen.pro script video"),
        (["script", "video"], "script to video"),
        (["ai", "cat"], "ai cat video"),
        (["ai", "anime"], "ai anime"),
        (["ai", "robot"], "ai robot"),
        (["100k", "club"], "subscriber milestone"),
        (["subscribe", "button"], "subscriber milestone"),
        (["bikini"], "bikini visual bait"),
        (["swimsuit"], "swimsuit visual bait"),
        (["beach", "girl"], "beach girl visual bait"),
        (["superhero"], "cinematic superhero prompt"),
        (["great power"], "cinematic superhero prompt"),
        (["\u590d\u53e4", "\u6d77\u62a5"], "\u590d\u53e4\u6d77\u62a5"),
        (["\u60c5\u4fa3", "\u96e8"], "\u96e8\u591c\u60c5\u4fa3"),
        (["\u81ea\u62cd", "\u63d0\u793a\u8bcd"], "\u81ea\u62cd\u63d0\u793a\u8bcd"),
        (["\u5199\u771f"], "\u5199\u771f"),
        (["\u7a7f\u642d"], "\u7a7f\u642d"),
    ]
    results: list[str] = []
    for required, label in patterns:
        if all(token in haystack for token in required):
            results = unique_append(results, label, limit=12)
    topic = extract_topic(text)
    if topic:
        results = unique_append(results, topic, limit=12)
    return results


def unique_append(values: list[str], item: str, limit: int = 80) -> list[str]:
    item = item.strip()
    if not item or item in values:
        return values
    return (values + [item])[-limit:]


def remove_items(values: list[str], items: list[str]) -> list[str]:
    targets = {item.strip().lower() for item in items if item.strip()}
    return [value for value in values if value.strip().lower() not in targets]


def is_tiktok_ai_query(query: str) -> bool:
    haystack = query.strip().lower()
    return bool(re.search(r"(^|[^a-z0-9])ai([^a-z0-9]|$)", haystack))


def tiktok_query_allowed(query: str) -> bool:
    haystack = query.strip().lower()
    if not haystack:
        return False
    return not any(token in haystack for token in TIKTOK_DISALLOWED_QUERY_TOKENS)


def tiktok_query_feedback_score(query: str, rows: list[dict[str, Any]]) -> float:
    haystack = query.strip().lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", haystack) if len(token) >= 4 and token not in {"video", "photo", "template"}]
    score = 0.0
    for row in rows:
        text = " ".join(str(row.get(key, "")) for key in ["intro", "material_reason"] if row.get(key)).lower()
        if not text:
            continue
        if haystack in text or any(token in text for token in tokens):
            score += feedback_score(row)
    return score


def rank_tiktok_queries(queries: list[str], rows: list[dict[str, Any]], defaults: list[str], limit: int, blocked: set[str] | None = None) -> list[str]:
    candidates: list[tuple[str, int]] = []
    seen: set[str] = set()
    blocked = blocked or set()
    for value in [*queries, *defaults]:
        query = re.sub(r"\s+", " ", str(value or "")).strip()
        key = query.lower()
        if not query or key in seen or key in blocked or not tiktok_query_allowed(query):
            continue
        seen.add(key)
        candidates.append((query, len(candidates)))
    default_set = {query.lower() for query in defaults}
    ranked = sorted(
        candidates,
        key=lambda item: (
            tiktok_query_feedback_score(item[0], rows) + (0.25 if item[0].lower() in default_set else 0.0),
            -item[1],
        ),
        reverse=True,
    )
    return [query for query, _index in ranked[:limit]]


def tiktok_keyword_defaults() -> dict[str, Any]:
    return {
        "keyword_tuning_window_days": TIKTOK_KEYWORD_TUNING_WINDOW_DAYS,
        "keyword_allocation_min": TIKTOK_KEYWORD_ALLOCATION_MIN,
        "keyword_allocation_max": TIKTOK_KEYWORD_ALLOCATION_MAX,
        "keyword_allocation_total": TIKTOK_KEYWORD_ALLOCATION_TOTAL,
        "hot_feed": {
            "enabled": True,
            "max_items": 100,
            "max_pages": 1,
            "path": "",
            "method": "GET",
        },
        "keyword_candidates": {
            "ai": TIKTOK_AI_KEYWORD_CANDIDATES,
            "non_ai": TIKTOK_NON_AI_KEYWORD_CANDIDATES,
        },
    }


def ensure_tiktok_scrape_defaults(scrape: dict[str, Any]) -> None:
    defaults = tiktok_keyword_defaults()
    for key in ["keyword_tuning_window_days", "keyword_allocation_min", "keyword_allocation_max", "keyword_allocation_total"]:
        scrape.setdefault(key, defaults[key])
    hot_feed = scrape.setdefault("hot_feed", {})
    if not isinstance(hot_feed, dict):
        hot_feed = {}
        scrape["hot_feed"] = hot_feed
    for key, value in defaults["hot_feed"].items():
        hot_feed.setdefault(key, value)
    candidates = scrape.setdefault("keyword_candidates", {})
    if not isinstance(candidates, dict):
        candidates = {}
        scrape["keyword_candidates"] = candidates
    for kind in ["ai", "non_ai"]:
        values = candidates.get(kind, [])
        if not isinstance(values, list):
            values = []
        merged: list[str] = []
        seen: set[str] = set()
        for value in [*values, *defaults["keyword_candidates"][kind]]:
            query = re.sub(r"\s+", " ", str(value or "")).strip()
            key = query.lower()
            if not query or key in seen or not tiktok_query_allowed(query):
                continue
            if kind == "ai" and not is_tiktok_ai_query(query):
                continue
            if kind == "non_ai" and is_tiktok_ai_query(query):
                continue
            seen.add(key)
            merged.append(query)
        candidates[kind] = merged
    rotation = scrape.setdefault("keyword_rotation", {})
    if not isinstance(rotation, dict):
        rotation = {}
        scrape["keyword_rotation"] = rotation
    rotation.setdefault("last_rotation_week", "")
    rotation.setdefault("replaced_keywords", [])
    rotation.setdefault("added_keywords", [])
    rotation.setdefault("reason", "")


def tiktok_query_key(query: Any) -> str:
    return re.sub(r"\s+", " ", str(query or "").strip().lower())


def even_tiktok_allocations(queries: list[str]) -> dict[str, int]:
    if not queries:
        return {}
    base = TIKTOK_KEYWORD_ALLOCATION_TOTAL // len(queries)
    allocations = {query: base for query in queries}
    remainder = TIKTOK_KEYWORD_ALLOCATION_TOTAL - sum(allocations.values())
    for query in queries[:remainder]:
        allocations[query] += 1
    return allocations


def normalize_tiktok_search_queries(rules: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> None:
    rows = rows or []
    scrape = rules.setdefault("scrape", {})
    ensure_tiktok_scrape_defaults(scrape)
    raw_queries = scrape.get("search_queries", [])
    if not isinstance(raw_queries, list):
        raw_queries = []
    cleaned = [re.sub(r"\s+", " ", str(query or "")).strip() for query in raw_queries]
    rotation = scrape.get("keyword_rotation", {})
    blocked = set()
    if isinstance(rotation, dict):
        blocked = {tiktok_query_key(query) for query in rotation.get("replaced_keywords", []) if str(query).strip()}
    cleaned = [query for query in cleaned if tiktok_query_key(query) not in blocked]
    ai_queries = [query for query in cleaned if is_tiktok_ai_query(query)]
    non_ai_queries = [query for query in cleaned if query and not is_tiktok_ai_query(query)]
    candidate_cfg = scrape.get("keyword_candidates", {})
    ai_defaults = candidate_cfg.get("ai", TIKTOK_AI_KEYWORD_CANDIDATES) if isinstance(candidate_cfg, dict) else TIKTOK_AI_KEYWORD_CANDIDATES
    non_ai_defaults = candidate_cfg.get("non_ai", TIKTOK_NON_AI_KEYWORD_CANDIDATES) if isinstance(candidate_cfg, dict) else TIKTOK_NON_AI_KEYWORD_CANDIDATES
    selected_ai = rank_tiktok_queries(ai_queries, rows, ai_defaults, TIKTOK_AI_SEARCH_COUNT, blocked)
    selected_non_ai = rank_tiktok_queries(non_ai_queries, rows, non_ai_defaults, TIKTOK_NON_AI_SEARCH_COUNT, blocked)
    scrape["search_queries"] = selected_ai + selected_non_ai
    scrape["max_search_queries"] = TIKTOK_MAX_SEARCH_QUERIES
    scrape["ai_search_count"] = TIKTOK_AI_SEARCH_COUNT
    scrape["non_ai_search_count"] = TIKTOK_NON_AI_SEARCH_COUNT
    scrape["results_per_keyword"] = int(scrape.get("results_per_keyword") or TIKTOK_RESULTS_PER_KEYWORD)
    existing_allocations = scrape.get("keyword_allocations", {})
    if not isinstance(existing_allocations, dict):
        existing_allocations = {}
    defaults = even_tiktok_allocations(scrape["search_queries"])
    allocations: dict[str, int] = {}
    for query in scrape["search_queries"]:
        raw_value = existing_allocations.get(query, existing_allocations.get(tiktok_query_key(query), defaults[query]))
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = defaults[query]
        allocations[query] = int(clamp(value, TIKTOK_KEYWORD_ALLOCATION_MIN, TIKTOK_KEYWORD_ALLOCATION_MAX))
    if sum(allocations.values()) != TIKTOK_KEYWORD_ALLOCATION_TOTAL:
        allocations = defaults
    scrape["keyword_allocations"] = allocations


def tiktok_url_keys(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    normalized = text.split("?")[0].rstrip("/").lower()
    keys = [normalized]
    match = re.search(r"/video/(\d+)", normalized) or re.search(r"\b(\d{12,})\b", normalized)
    if match:
        keys.append(f"video:{match.group(1)}")
    return list(dict.fromkeys(keys))


def iter_tiktok_raw_archives(today: date, days: int) -> list[Path]:
    cutoff = datetime.combine(today - timedelta(days=days + 1), datetime.min.time()).timestamp()
    candidates: list[Path] = []
    for pattern in [
        BASE_DIR / "skill_runs" / "scrape_checkpoints" / "tiktok" / "runs" / "*.json",
        BASE_DIR / "skill_runs" / "scrape_checkpoints" / "tiktok" / "latest_raw.json",
        BASE_DIR / "trend-scrap" / "tiktok-scraper" / "data" / "raw" / "*.json",
    ]:
        if "*" in str(pattern):
            candidates.extend(Path(pattern.parent).glob(pattern.name))
        elif pattern.exists():
            candidates.append(pattern)
    fresh: list[Path] = []
    for path in candidates:
        try:
            if path.stat().st_mtime >= cutoff:
                fresh.append(path)
        except OSError:
            continue
    return fresh


def load_json_items(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ["items", "rawData", "data", "results"]:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def build_tiktok_keyword_index(today: date, days: int) -> dict[str, str]:
    index: dict[str, str] = {}
    for path in iter_tiktok_raw_archives(today, days):
        for item in load_json_items(path):
            query = re.sub(r"\s+", " ", str(item.get("sourceQuery") or item.get("searchQuery") or "").strip())
            if not query:
                continue
            keys: list[str] = []
            for field in ["webVideoUrl", "url", "shareUrl", "id"]:
                keys.extend(tiktok_url_keys(item.get(field)))
            video_meta = item.get("videoMeta")
            if isinstance(video_meta, dict):
                keys.extend(tiktok_url_keys(video_meta.get("webVideoUrl")))
            for key in keys:
                index.setdefault(key, query)
    return index


def tiktok_keyword_for_feedback_row(row: dict[str, Any], index: dict[str, str]) -> str:
    for key in tiktok_url_keys(row.get("url")):
        if key in index:
            return index[key]
    return ""


def row_has_ua_value(row: dict[str, Any], target: str) -> bool:
    values = row.get("material_acceptance_values")
    if not isinstance(values, list) or not values:
        values = [row.get("material_acceptance", "")]
    return any(normalize_acceptance(value) == target for value in values)


def row_has_ua_negative(row: dict[str, Any]) -> bool:
    values = row.get("material_acceptance_values")
    if not isinstance(values, list) or not values:
        values = [row.get("material_acceptance", "")]
    return any(normalize_acceptance(value) in {"\u4f4e", "\u5426\u51b3"} for value in values)


def tiktok_keyword_performance(rules: dict[str, Any], rows: list[dict[str, Any]], today: date, days: int) -> dict[str, Any]:
    queries = rules.get("scrape", {}).get("search_queries", [])
    query_by_key = {tiktok_query_key(query): query for query in queries if str(query).strip()}
    stats: dict[str, dict[str, Any]] = {
        query: {
            "keyword": query,
            "feedbackCount": 0,
            "highQualityCount": 0,
            "usableCount": 0,
            "uselessCount": 0,
            "score": 0.0,
        }
        for query in query_by_key.values()
    }
    index = build_tiktok_keyword_index(today, days)
    unmatched = 0
    for row in rows:
        if row_platform(row) != "tiktok":
            continue
        keyword = tiktok_keyword_for_feedback_row(row, index)
        canonical = query_by_key.get(tiktok_query_key(keyword))
        if not canonical:
            unmatched += 1
            continue
        item = stats[canonical]
        high = row_has_ua_value(row, "\u9ad8")
        usable = row_has_ua_value(row, "\u4e2d")
        useless = row_has_ua_negative(row)
        item["feedbackCount"] += 1
        if high:
            item["highQualityCount"] += 1
        if usable:
            item["usableCount"] += 1
        if useless:
            item["uselessCount"] += 1
        item["score"] = round(item["highQualityCount"] * 2.0 + item["usableCount"] * 0.5 - item["uselessCount"] * 1.5, 4)
    return {
        "windowDays": days,
        "sourceIndexSize": len(index),
        "unmatchedFeedbackCount": unmatched,
        "keywords": stats,
    }


def allocate_tiktok_keywords(queries: list[str], performance: dict[str, Any]) -> dict[str, int]:
    if not queries:
        return {}
    allocations = {query: TIKTOK_KEYWORD_ALLOCATION_MIN for query in queries}
    remaining = TIKTOK_KEYWORD_ALLOCATION_TOTAL - sum(allocations.values())
    stats = performance.get("keywords", {}) if isinstance(performance, dict) else {}
    weights: dict[str, float] = {}
    for query in queries:
        item = stats.get(query, {})
        score = float(item.get("score", 0.0) or 0.0)
        feedback_count = int(item.get("feedbackCount", 0) or 0)
        weights[query] = max(0.15, 1.0 + score) if feedback_count else 1.0
    weight_sum = sum(weights.values()) or 1.0
    fractional: list[tuple[float, float, str]] = []
    for query in queries:
        raw_add = remaining * weights[query] / weight_sum
        add = min(TIKTOK_KEYWORD_ALLOCATION_MAX - TIKTOK_KEYWORD_ALLOCATION_MIN, int(raw_add))
        allocations[query] += add
        fractional.append((raw_add - add, float(stats.get(query, {}).get("score", 0.0) or 0.0), query))
    leftover = TIKTOK_KEYWORD_ALLOCATION_TOTAL - sum(allocations.values())
    for _fraction, _score, query in sorted(fractional, reverse=True):
        if leftover <= 0:
            break
        if allocations[query] < TIKTOK_KEYWORD_ALLOCATION_MAX:
            allocations[query] += 1
            leftover -= 1
    while leftover > 0:
        progressed = False
        ordered = sorted(
            queries,
            key=lambda value: (float(stats.get(value, {}).get("score", 0.0) or 0.0), -allocations[value]),
            reverse=True,
        )
        for query in ordered:
            if allocations[query] >= TIKTOK_KEYWORD_ALLOCATION_MAX:
                continue
            allocations[query] += 1
            leftover -= 1
            progressed = True
            if leftover <= 0:
                break
        if not progressed:
            break
    return allocations


def tiktok_iso_week(today: date) -> str:
    year, week, _weekday = today.isocalendar()
    return f"{year}-W{week:02d}"


def select_tiktok_replacements_deterministic(scrape: dict[str, Any], current: list[str], rows: list[dict[str, Any]], kind: str, count: int) -> list[str]:
    candidates = scrape.get("keyword_candidates", {}).get(kind, [])
    defaults = TIKTOK_AI_KEYWORD_CANDIDATES if kind == "ai" else TIKTOK_NON_AI_KEYWORD_CANDIDATES
    current_keys = {tiktok_query_key(query) for query in current}
    ranked: list[tuple[float, int, str]] = []
    seen: set[str] = set()
    for index, value in enumerate([*candidates, *defaults]):
        query = re.sub(r"\s+", " ", str(value or "").strip())
        key = tiktok_query_key(query)
        if not query or key in current_keys or key in seen or not tiktok_query_allowed(query):
            continue
        if kind == "ai" and not is_tiktok_ai_query(query):
            continue
        if kind == "non_ai" and is_tiktok_ai_query(query):
            continue
        seen.add(key)
        ranked.append((tiktok_query_feedback_score(query, rows), -index, query))
    return [query for _score, _index, query in sorted(ranked, reverse=True)[:count]]


def select_tiktok_replacements_with_ai(scrape: dict[str, Any], current: list[str], rows: list[dict[str, Any]], replace_counts: dict[str, int]) -> dict[str, list[str]]:
    if not any(replace_counts.values()):
        return {"ai": [], "non_ai": []}
    env = load_env()
    openai_key = os.environ.get("OPENAI_API_KEY") or env.get("OPENAI_API_KEY")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY")
    api_key = openai_key or openrouter_key
    if not api_key:
        return {"ai": [], "non_ai": []}
    try:
        from openai import OpenAI
    except ImportError:
        return {"ai": [], "non_ai": []}
    base_url = None
    model = os.environ.get("OPENAI_FEEDBACK_MODEL") or env.get("OPENAI_FEEDBACK_MODEL") or "gpt-5.4"
    if not openai_key:
        base_url = "https://openrouter.ai/api/v1"
        model = os.environ.get("OPENROUTER_MODEL") or env.get("OPENROUTER_MODEL") or model
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    try:
        client = OpenAI(**kwargs)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return JSON only. Choose TikTok replacement search keywords only from the provided candidate pools. "
                        "Do not invent keywords. Preserve the requested ai/non_ai counts. Favor Evoke/Toki/Kavi/Avatar material, "
                        "single-photo upload, photo-to-video, avatar puzzle, before-after, and reusable template signals."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "current": current,
                            "replace_counts": replace_counts,
                            "candidates": scrape.get("keyword_candidates", {}),
                            "feedback": format_sanitized_feedback_markdown(rows[:40], today=date.today(), days=TIKTOK_KEYWORD_TUNING_WINDOW_DAYS, compact=True),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        payload = json.loads(strip_json_fence(response_content(response)))
    except Exception as exc:
        print(f"[WARN] TikTok keyword rotation AI selection failed; using fallback: {exc}")
        return {"ai": [], "non_ai": []}
    selected: dict[str, list[str]] = {"ai": [], "non_ai": []}
    current_keys = {tiktok_query_key(query) for query in current}
    for kind in ["ai", "non_ai"]:
        pool = {tiktok_query_key(value): str(value).strip() for value in scrape.get("keyword_candidates", {}).get(kind, [])}
        values = payload.get(kind, [])
        if not isinstance(values, list):
            values = []
        for value in values:
            key = tiktok_query_key(value)
            query = pool.get(key)
            if not query or key in current_keys or key in {tiktok_query_key(item) for item in selected[kind]}:
                continue
            if kind == "ai" and not is_tiktok_ai_query(query):
                continue
            if kind == "non_ai" and is_tiktok_ai_query(query):
                continue
            selected[kind].append(query)
            if len(selected[kind]) >= replace_counts.get(kind, 0):
                break
    return selected


def rotate_tiktok_keywords_if_needed(rules: dict[str, Any], rows: list[dict[str, Any]], today: date, performance: dict[str, Any]) -> list[dict[str, str]]:
    scrape = rules.setdefault("scrape", {})
    ensure_tiktok_scrape_defaults(scrape)
    week = tiktok_iso_week(today)
    rotation = scrape.setdefault("keyword_rotation", {})
    if rotation.get("last_rotation_week") == week:
        return []
    queries = list(scrape.get("search_queries", []))
    stats = performance.get("keywords", {}) if isinstance(performance, dict) else {}
    if sum(int(item.get("feedbackCount", 0) or 0) for item in stats.values()) <= 0:
        rotation["reason"] = "Weekly TikTok keyword rotation skipped because no 7-day feedback could be mapped to current keywords."
        return []
    indexed = []
    for index, query in enumerate(queries):
        item = stats.get(query, {})
        indexed.append(
            (
                float(item.get("score", 0.0) or 0.0),
                0 if int(item.get("feedbackCount", 0) or 0) else 1,
                -int(item.get("uselessCount", 0) or 0),
                index,
                query,
            )
        )
    worst = [query for *_rest, query in sorted(indexed)[:TIKTOK_KEYWORD_ROTATION_REPLACE_COUNT]]
    replace_counts = {
        "ai": len([query for query in worst if is_tiktok_ai_query(query)]),
        "non_ai": len([query for query in worst if not is_tiktok_ai_query(query)]),
    }
    selected = select_tiktok_replacements_with_ai(scrape, queries, rows, replace_counts)
    for kind, count in replace_counts.items():
        if len(selected[kind]) < count:
            fallback = select_tiktok_replacements_deterministic(scrape, queries + selected["ai"] + selected["non_ai"], rows, kind, count - len(selected[kind]))
            selected[kind].extend(fallback)
    selected_by_kind = {"ai": list(selected["ai"]), "non_ai": list(selected["non_ai"])}
    replacements: list[dict[str, str]] = []
    new_queries: list[str] = []
    for query in queries:
        if query not in worst:
            new_queries.append(query)
            continue
        kind = "ai" if is_tiktok_ai_query(query) else "non_ai"
        added = selected_by_kind[kind].pop(0) if selected_by_kind[kind] else query
        new_queries.append(added)
        if added != query:
            replacements.append({"removed": query, "added": added, "type": kind})
    scrape["search_queries"] = new_queries
    rotation["last_rotation_week"] = week
    rotation["replaced_keywords"] = [item["removed"] for item in replacements]
    rotation["added_keywords"] = [item["added"] for item in replacements]
    rotation["reason"] = "Weekly TikTok keyword rotation based on 7-day feedback performance."
    return replacements


def apply_tiktok_keyword_tuning(rules: dict[str, Any], rows: list[dict[str, Any]], today: date) -> dict[str, Any]:
    scrape = rules.setdefault("scrape", {})
    ensure_tiktok_scrape_defaults(scrape)
    normalize_tiktok_search_queries(rules, rows)
    window_days = int(scrape.get("keyword_tuning_window_days") or TIKTOK_KEYWORD_TUNING_WINDOW_DAYS)
    performance = tiktok_keyword_performance(rules, rows, today, window_days)
    replacements = rotate_tiktok_keywords_if_needed(rules, rows, today, performance)
    if replacements:
        replace_map = {item["removed"]: item["added"] for item in replacements}
        rules["scrape"]["search_queries"] = [replace_map.get(query, query) for query in rules["scrape"]["search_queries"]]
        scrape["max_search_queries"] = TIKTOK_MAX_SEARCH_QUERIES
        scrape["ai_search_count"] = TIKTOK_AI_SEARCH_COUNT
        scrape["non_ai_search_count"] = TIKTOK_NON_AI_SEARCH_COUNT
        performance = tiktok_keyword_performance(rules, rows, today, window_days)
    queries = rules["scrape"]["search_queries"]
    allocations = allocate_tiktok_keywords(queries, performance)
    rules["scrape"]["keyword_allocations"] = allocations
    return {
        "generatedAt": datetime.now().isoformat(),
        "windowDays": window_days,
        "allocations": allocations,
        "replacements": replacements,
        "performance": performance,
    }


def x_query_allowed(query: str) -> bool:
    haystack = query.strip().lower()
    if not haystack:
        return False
    if any(token in haystack for token in X_DISALLOWED_QUERY_TOKENS):
        return False
    return any(token in haystack for token in X_ALLOWED_QUERY_TOKENS)


def clean_x_query(query: Any) -> str:
    return re.sub(r"\s+", " ", str(query or "")).strip()


def append_x_query(bucket: list[str], query: Any, seen: set[str], limit: int) -> None:
    value = clean_x_query(query)
    key = value.lower()
    if not value or key in seen or len(bucket) >= limit:
        return
    bucket.append(value)
    seen.add(key)


def classify_x_query(query: str) -> str:
    haystack = query.strip().lower()
    if not x_query_allowed(query):
        return ""
    if haystack.startswith("ai "):
        return "ai_material"
    if query in X_WORKFLOW_SEARCH_QUERIES or any(token in haystack for token in X_WORKFLOW_TOKENS):
        return "workflow"
    if any(token in haystack for token in X_REAL_PHOTO_TOKENS):
        return "real_photo"
    return ""


def normalize_x_search_queries(rules: dict[str, Any]) -> None:
    x_scrape = rules.setdefault("x_scrape", {})
    x_scrape["max_search_queries"] = X_MAX_SEARCH_QUERIES

    raw_queries = x_scrape.get("search_queries", [])
    if not isinstance(raw_queries, list):
        raw_queries = []

    workflow: list[str] = []
    ai_material: list[str] = []
    real_photo: list[str] = []
    seen: set[str] = set()

    for query in X_WORKFLOW_SEARCH_QUERIES:
        append_x_query(workflow, query, seen, X_WORKFLOW_QUERY_COUNT)

    for query in raw_queries:
        value = clean_x_query(query)
        bucket = classify_x_query(value)
        if bucket == "workflow":
            append_x_query(workflow, value, seen, X_WORKFLOW_QUERY_COUNT)
        elif bucket == "ai_material":
            append_x_query(ai_material, value, seen, X_AI_MATERIAL_QUERY_COUNT)
        elif bucket == "real_photo":
            append_x_query(real_photo, value, seen, X_REAL_PHOTO_QUERY_COUNT)

    for query in X_AI_MATERIAL_SEARCH_QUERIES:
        append_x_query(ai_material, query, seen, X_AI_MATERIAL_QUERY_COUNT)
    for query in X_REAL_PHOTO_SEARCH_QUERIES:
        append_x_query(real_photo, query, seen, X_REAL_PHOTO_QUERY_COUNT)

    x_scrape["search_queries"] = workflow + ai_material + real_photo


def update_x_team_demand_from_feedback(rules: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    x_team = rules.setdefault("x_team_demand", {})
    x_team.setdefault("photo_product_keywords", [])
    x_team.setdefault("reject_keywords", [])
    for row in rows:
        score = feedback_score(row)
        text = " ".join(str(row.get(key, "")) for key in ["intro", "material_reason"] if row.get(key))
        keywords = [keyword for keyword in material_keywords(text) if 2 <= len(keyword) <= 40]
        if not keywords:
            continue
        if score >= 0.5:
            for keyword in keywords:
                x_team["photo_product_keywords"] = unique_append(x_team["photo_product_keywords"], keyword, limit=120)
            x_team["reject_keywords"] = remove_items(x_team["reject_keywords"], keywords)
        elif score <= -0.75:
            for keyword in keywords:
                x_team["reject_keywords"] = unique_append(x_team["reject_keywords"], keyword, limit=160)


def split_feedback_target(row: dict[str, Any]) -> str:
    return ""


def update_audience_targeting_from_split_feedback(rules: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    audience = rules.setdefault("audience_targeting", {})
    audience.setdefault("enabled", True)
    audience.setdefault("ua_keywords", [])
    audience.setdefault("product_keywords", [])
    audience.setdefault("min_keyword_hits", 1)
    return rules


def row_platform(row: dict[str, Any]) -> str:
    platform = str(row.get("platform") or "").strip().lower()
    if platform in {"x", "twitter"}:
        return "x"
    return "tiktok"


def tune_scoring_parameters(rules: dict[str, Any], rows: list[dict[str, Any]], section: str = "scoring") -> None:
    scoring = rules.setdefault(section, {})
    params = scoring.setdefault("active_parameters", {})
    bounds = scoring.setdefault("bounds", {})
    defaults = {"play_weight": 0.01, "like_weight": 1.0, "comment_weight": 5.0, "gravity": 1.8, "high_score_k": 500.0}
    for key, default in defaults.items():
        params[key] = float(params.get(key, default))
    if not rows:
        return
    scored = [feedback_score(row) for row in rows]
    reject_rate = len([score for score in scored if score <= -0.75]) / len(scored)
    high_rate = len([score for score in scored if score >= 0.75]) / len(scored)
    low_rate = len([score for score in scored if 0 < score < 0.75]) / len(scored)
    if reject_rate >= 0.4:
        params["play_weight"] *= 0.95
        params["like_weight"] *= 1.05
        params["comment_weight"] *= 1.08
        params["gravity"] += 0.05
        params["high_score_k"] *= 1.08
    elif high_rate >= 0.4:
        params["play_weight"] *= 1.02
        params["gravity"] -= 0.03
        params["high_score_k"] *= 0.96
    if low_rate >= 0.35:
        params["comment_weight"] *= 1.04
        params["gravity"] += 0.02
        params["high_score_k"] *= 1.03
    for key, default_bounds in {
        "play_weight": [0.001, 0.05],
        "like_weight": [0.2, 5.0],
        "comment_weight": [1.0, 20.0],
        "gravity": [0.8, 3.0],
        "high_score_k": [100.0, 10000.0],
    }.items():
        lower, upper = bounds.get(key, default_bounds)
        params[key] = round(clamp(float(params[key]), float(lower), float(upper)), 4)


def optimize_rules_from_feedback(current_rules: dict[str, Any], rows: list[dict[str, Any]], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    rules = copy.deepcopy(current_rules)
    filters = rules.setdefault("filters", {})
    audience = rules.setdefault("audience_targeting", {})
    filters.setdefault("preferred_keywords", [])
    filters.setdefault("deprioritized_keywords", [])
    audience.setdefault("enabled", True)
    audience.setdefault("ua_keywords", [])
    audience.setdefault("product_keywords", [])
    audience.setdefault("min_keyword_hits", 1)
    learning = rules.setdefault("learning_summary", [])
    positive_topics: list[str] = []
    negative_topics: list[str] = []
    for row in rows:
        score = feedback_score(row)
        text = " ".join(str(row.get(key, "")) for key in ["intro", "material_reason"] if row.get(key))
        topic = extract_topic(text)
        if not topic:
            continue
        if score >= 0.5:
            filters["preferred_keywords"] = unique_append(filters["preferred_keywords"], topic)
            positive_topics.append(topic)
        elif score <= -0.75:
            filters["deprioritized_keywords"] = unique_append(filters["deprioritized_keywords"], topic)
            negative_topics.append(topic)
    tiktok_rows = [row for row in rows if row_platform(row) == "tiktok"]
    x_rows = [row for row in rows if row_platform(row) == "x"]
    update_audience_targeting_from_split_feedback(rules, rows)
    update_x_team_demand_from_feedback(rules, x_rows)
    tune_scoring_parameters(rules, tiktok_rows, section="scoring")
    tune_scoring_parameters(rules, x_rows, section="x_scoring")
    normalize_tiktok_search_queries(rules, tiktok_rows)
    normalize_x_search_queries(rules)
    rules["version"] = int(rules.get("version", 1)) + 1
    rules["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rules["source"] = "feishu_feedback_deterministic"
    start, end = feedback_window(today, 1)
    rules["last_feedback_window"] = {"start_date": start.isoformat(), "end_date": end.isoformat(), "feedback_count": len(rows)}
    if positive_topics or negative_topics:
        learning.append(f"{today.isoformat()} feedback tuned scoring and topics.")
        rules["learning_summary"] = learning[-80:]
    validate_feedback_rules(rules)
    return rules


def env_number(value: Any) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.8f}".rstrip("0").rstrip(".")


def json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def sync_scoring_parameters_to_env(rules: dict[str, Any], env_file: Path = ROOT_ENV_FILE) -> None:
    updates: dict[str, str] = {}
    for section, env_keys in SCORING_ENV_KEYS.items():
        active = ((rules or {}).get(section) or {}).get("active_parameters") or {}
        updates.update({env_key: env_number(active[param_key]) for param_key, env_key in env_keys.items() if param_key in active})
    if not updates:
        return
    existing_lines = env_file.read_text(encoding="utf-8-sig").splitlines() if env_file.exists() else []
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)
    missing = [key for key in updates if key not in seen]
    if missing:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("# Synced scoring parameters from feedback rules")
        for key in missing:
            new_lines.append(f"{key}={updates[key]}")
    env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    for key, value in updates.items():
        os.environ[key] = value


def write_rules(new_rules: dict[str, Any], dry_run: bool = False) -> None:
    validate_feedback_rules(new_rules)
    if dry_run:
        print(json.dumps(new_rules, ensure_ascii=False, indent=2))
        return
    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if RULES_FILE.exists():
        backup = BACKUP_DIR / f"{RULES_FILE.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        shutil.copy2(RULES_FILE, backup)
    tmp = RULES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new_rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(RULES_FILE)
    sync_scoring_parameters_to_env(new_rules)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize TikTok rules from Feishu feedback")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-fetch", action="store_true", help="Use no live feedback; validates existing rules")
    parser.add_argument("--skip-ai", action="store_true", help="Use deterministic feedback optimization only")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env()
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    try:
        rows = [] if args.skip_fetch else collect_recent_feedback(days=args.days)
        (FEEDBACK_DIR / f"{date.today().strftime('%Y%m%d')}_recent_feedback.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
        (FEEDBACK_DIR / f"{date.today().strftime('%Y%m%d')}_recent_feedback.md").write_text(format_feedback_markdown(rows, today=date.today(), days=args.days), encoding="utf-8")
        current = load_feedback_rules()
        keyword_window_days = int(current.get("scrape", {}).get("keyword_tuning_window_days", TIKTOK_KEYWORD_TUNING_WINDOW_DAYS) or TIKTOK_KEYWORD_TUNING_WINDOW_DAYS)
        keyword_rows = rows
        if not args.skip_fetch and keyword_window_days != args.days:
            try:
                keyword_rows = collect_recent_feedback(days=keyword_window_days)
            except Exception as keyword_exc:
                print(f"[WARN] TikTok keyword tuning feedback fetch failed; using current rows only: {keyword_exc}")
                keyword_rows = rows
        if not rows and not keyword_rows:
            validate_feedback_rules(current)
            print("[INFO] No feedback rows found; existing rules kept.")
            return 0
        use_ai = bool(rows) and not args.skip_ai and not env_bool("FEEDBACK_DISABLE_AI", False)
        if use_ai:
            try:
                print(f"[INFO] Optimizing feedback rules with AI from {len(rows)} rows.")
                new_rules = call_ai_optimizer(current, rows, today=date.today(), days=args.days)
                new_rules["version"] = int(current.get("version", 1)) + 1
                new_rules["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                start, end = feedback_window(date.today(), args.days)
                new_rules["last_feedback_window"] = {"start_date": start.isoformat(), "end_date": end.isoformat(), "feedback_count": len(rows)}
            except Exception as ai_exc:
                print(f"[WARN] AI optimization failed; falling back to deterministic rules: {ai_exc}")
                new_rules = optimize_rules_from_feedback(current, rows)
        elif rows:
            new_rules = optimize_rules_from_feedback(current, rows)
        else:
            new_rules = copy.deepcopy(current)
            normalize_tiktok_search_queries(new_rules, keyword_rows)
            normalize_x_search_queries(new_rules)
            new_rules["version"] = int(current.get("version", 1)) + 1
            new_rules["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_rules["source"] = "feishu_feedback_keyword_tuning"
        if rows:
            new_rules = update_audience_targeting_from_split_feedback(new_rules, rows)
        keyword_report = apply_tiktok_keyword_tuning(new_rules, keyword_rows, date.today())
        (FEEDBACK_DIR / f"{date.today().strftime('%Y%m%d')}_tiktok_keyword_performance.json").write_text(
            json.dumps(keyword_report, ensure_ascii=False, indent=2, default=json_default),
            encoding="utf-8",
        )
        validate_feedback_rules(new_rules)
        write_rules(new_rules, dry_run=args.dry_run)
        print(f"[INFO] Optimized rules with {len(rows)} feedback rows; TikTok keyword tuning used {len(keyword_rows)} rows.")
        return 0
    except Exception as exc:
        print(f"[WARN] Feedback optimization failed: {exc}")
        validate_feedback_rules(load_feedback_rules())
        print("[WARN] Existing valid rules kept.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
