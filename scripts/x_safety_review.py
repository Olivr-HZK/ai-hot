from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from env_utils import load_env
from feedback_rules import detect_media_type
from visual_dedupe import allowed_model, clean_text, image_input_urls, item_text, openrouter_models


BASE_DIR = Path(__file__).resolve().parents[1]
DEBUG_DIR = BASE_DIR / "skill_runs" / "safety_review"

DEFAULT_MODEL = "qwen/qwen3.6-flash"
MODEL_FALLBACKS = ["qwen/qwen3.6-plus", "z-ai/glm-5v-turbo", "bytedance-seed/seed-2.0-lite"]

BLOCKED_RISK_CATEGORIES = {"nsfw", "soft_porn", "edge_bait", "ai_girl_bait", "anime_soft_porn"}
HIGH_RISK_KEYWORDS = [
    "nsfw",
    "soft porn",
    "onlyfans",
    "lingerie",
    "bikini",
    "cleavage",
    "nude",
    "porn",
    "sexy anime",
    "anime girl",
    "ai girl",
    "ai girlfriend",
    "sexy girl",
    "\u64e6\u8fb9",
    "\u8f6f\u8272\u60c5",
    "\u8272\u60c5",
    "\u5185\u8863",
    "\u6cf3\u88c5",
    "\u4e8c\u6b21\u5143\u7f8e\u5973",
]


def env_truthy(name: str, env: dict[str, str]) -> bool:
    return str(os.environ.get(name) or env.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_safety_model() -> str:
    env = load_env()
    configured = os.environ.get("X_SAFETY_REVIEW_MODEL") or env.get("X_SAFETY_REVIEW_MODEL")
    configured = configured or os.environ.get("VISUAL_DEDUPE_MODEL") or env.get("VISUAL_DEDUPE_MODEL") or DEFAULT_MODEL
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return configured if allowed_model(configured) else DEFAULT_MODEL
    candidates = [configured, *MODEL_FALLBACKS]
    available = set(openrouter_models())
    for model in candidates:
        if allowed_model(model) and (not available or model in available):
            return model
    return DEFAULT_MODEL


def high_risk_keyword_hit(item: dict[str, Any]) -> str:
    text = item_text(item).lower()
    for keyword in HIGH_RISK_KEYWORDS:
        if keyword.lower() in text:
            return keyword
    return ""


def normalize_risk_category(value: Any) -> str:
    category = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    aliases = {
        "safe": "safe",
        "allowed": "safe",
        "sexual": "soft_porn",
        "sexually_suggestive": "edge_bait",
        "suggestive": "edge_bait",
        "anime_suggestive": "anime_soft_porn",
        "ai_girl": "ai_girl_bait",
    }
    return aliases.get(category, category or "unknown")


def bool_value(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "allowed", "pass"}:
        return True
    if text in {"false", "0", "no", "blocked", "fail"}:
        return False
    return default


def normalize_review(raw: dict[str, Any], model: str, media_type: str, fallback: bool = False) -> dict[str, Any]:
    category = normalize_risk_category(raw.get("riskCategory") or raw.get("risk_category") or raw.get("category"))
    allowed = bool_value(raw.get("isAllowed", raw.get("is_allowed", raw.get("allowed"))), default=True)
    if category in BLOCKED_RISK_CATEGORIES:
        allowed = False
    try:
        confidence = float(raw.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "isAllowed": allowed,
        "riskCategory": category,
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": clean_text(raw.get("reason") or raw.get("rationale") or "", max_len=220),
        "mediaType": media_type,
        "model": model,
        "fallback": fallback,
    }


def build_review_prompt(item: dict[str, Any], media_type: str) -> list[dict[str, Any]]:
    prompt = (
        "You are a strict safety reviewer for X image materials used by an AI creative product and UA team. "
        "Review both the attached image URLs and the post text. Block adult, NSFW, soft-porn, edge-bait, "
        "AI-girl bait, anime soft-porn, lingerie/swimsuit sexualized display, and sexually suggestive poses. "
        "Allow normal portraits, couple/family photos, fashion, makeup, hairstyle, art photography, and non-sexual anime style. "
        "Return strict JSON with keys: isAllowed, riskCategory, confidence, reason. "
        "riskCategory must be one of safe, nsfw, soft_porn, edge_bait, ai_girl_bait, anime_soft_porn, other."
    )
    author_meta = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"{prompt}\n"
                f"Media type: {media_type}\n"
                f"Post text: {clean_text(item_text(item), max_len=1200)}\n"
                f"Author: {clean_text(author_meta.get('nickName') or author.get('username'), max_len=120)}"
            ),
        }
    ]
    for url in image_input_urls(item, limit=3):
        content.append({"type": "image_url", "image_url": {"url": url}})
    return content


def review_with_model(item: dict[str, Any], model: str, media_type: str) -> dict[str, Any] | None:
    env = load_env()
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    if not api_key or not allowed_model(model):
        return None
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": build_review_prompt(item, media_type)}],
            "response_format": {"type": "json_object"},
            "max_tokens": 500,
        },
        timeout=45,
    )
    response.raise_for_status()
    text = response.json()["choices"][0]["message"].get("content") or "{}"
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        return None
    return normalize_review(parsed, model, media_type)


def fallback_review(item: dict[str, Any], media_type: str, model: str, error: str = "") -> dict[str, Any]:
    hit = high_risk_keyword_hit(item)
    if hit:
        return {
            "isAllowed": False,
            "riskCategory": "keyword_high_risk",
            "confidence": 1.0,
            "reason": f"high-risk keyword matched: {hit}",
            "mediaType": media_type,
            "model": model,
            "fallback": True,
            "warning": clean_text(error, max_len=180),
        }
    return {
        "isAllowed": True,
        "riskCategory": "unreviewed",
        "confidence": 0.0,
        "reason": "model unavailable or failed; no high-risk keyword matched",
        "mediaType": media_type,
        "model": model,
        "fallback": True,
        "warning": clean_text(error, max_len=180),
    }


def apply_x_image_safety_review(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    env = load_env()
    if env_truthy("X_SAFETY_REVIEW_DISABLE", env):
        return items, []
    model = resolve_safety_model()
    kept: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in items:
        updated = dict(item)
        media_type = detect_media_type(updated)
        if media_type not in {"image", "mixed"}:
            updated["safetyReview"] = {
                "isAllowed": True,
                "riskCategory": "not_reviewed",
                "confidence": 1.0,
                "reason": "not an X image or mixed-media candidate",
                "mediaType": media_type,
                "model": "",
                "fallback": False,
            }
            kept.append(updated)
            continue
        try:
            review = review_with_model(updated, model, media_type) or fallback_review(updated, media_type, model, "model unavailable")
        except Exception as exc:
            review = fallback_review(updated, media_type, model, str(exc))
        updated["safetyReview"] = review
        if not review.get("isAllowed", True):
            blocked.append(updated)
            continue
        kept.append(updated)
    if blocked:
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            (DEBUG_DIR / f"x_{timestamp}_blocked.json").write_text(json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"  - X safety review debug write skipped: {exc}", flush=True)
    print(f"  - X image safety review kept {len(kept)}/{len(items)} items; blocked {len(blocked)}", flush=True)
    return kept, blocked
