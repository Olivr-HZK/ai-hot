from __future__ import annotations

import json
import os
from typing import Any

import requests

from env_utils import load_env
from ins_scoring import clean_text, media_urls


BLOCKED_CATEGORIES = {"nsfw", "soft_porn", "edge_bait", "ai_girl_bait", "anime_soft_porn"}


def text_blob(item: dict[str, Any]) -> str:
    parts = [
        item.get("title"),
        item.get("text"),
        item.get("desc"),
        item.get("summary"),
        " ".join(str(tag) for tag in item.get("hashtags") or []),
    ]
    return clean_text(" ".join(str(part or "") for part in parts if part)).lower()


def high_risk_keyword(item: dict[str, Any], rules: dict[str, Any]) -> str:
    text = text_blob(item)
    for keyword in rules.get("safety", {}).get("high_risk_keywords", []):
        if str(keyword).lower() in text:
            return str(keyword)
    return ""


def normalize_review(raw: dict[str, Any], model: str, fallback: bool = False) -> dict[str, Any]:
    category = clean_text(raw.get("riskCategory") or raw.get("risk_category") or raw.get("category") or "safe").lower()
    category = {
        "safe": "safe",
        "allowed": "safe",
        "sexual": "soft_porn",
        "suggestive": "edge_bait",
        "sexually_suggestive": "edge_bait",
        "ai_girl": "ai_girl_bait",
    }.get(category, category)
    allowed = raw.get("isAllowed", raw.get("allowed", True))
    if isinstance(allowed, str):
        allowed = allowed.strip().lower() in {"true", "1", "yes", "safe", "allowed", "pass"}
    if category in BLOCKED_CATEGORIES:
        allowed = False
    try:
        confidence = float(raw.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "isAllowed": bool(allowed),
        "riskCategory": category or "unknown",
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": clean_text(raw.get("reason") or raw.get("rationale"), max_len=220),
        "model": model,
        "fallback": fallback,
    }


def fallback_review(item: dict[str, Any], rules: dict[str, Any], model: str, warning: str = "") -> dict[str, Any]:
    hit = high_risk_keyword(item, rules)
    if hit:
        return {
            "isAllowed": False,
            "riskCategory": "keyword_high_risk",
            "confidence": 1.0,
            "reason": f"high-risk keyword matched: {hit}",
            "model": model,
            "fallback": True,
            "warning": clean_text(warning, max_len=180),
        }
    return {
        "isAllowed": True,
        "riskCategory": "unreviewed",
        "confidence": 0.0,
        "reason": "model unavailable or failed; no high-risk keyword matched",
        "model": model,
        "fallback": True,
        "warning": clean_text(warning, max_len=180),
    }


def build_prompt(item: dict[str, Any]) -> list[dict[str, Any]]:
    text = (
        "You are a strict Instagram visual safety reviewer for AI product and UA material selection. "
        "Review the post text and attached media URLs. Block NSFW, soft-porn, edge-bait, AI-girl bait, "
        "anime soft-porn, lingerie/swimsuit sexualized display, and sexually suggestive poses. "
        "Allow normal portraits, family/couple photos, fashion/editorial photography, makeup, hairstyle, "
        "creative photos, and non-sexual anime or art style. Return strict JSON with keys: "
        "isAllowed, riskCategory, confidence, reason. riskCategory must be one of safe, nsfw, "
        "soft_porn, edge_bait, ai_girl_bait, anime_soft_porn, other.\n"
        f"Post text: {clean_text(text_blob(item), max_len=1200)}"
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for url in media_urls(item, limit=3):
        if not url.lower().split("?", 1)[0].endswith((".mp4", ".mov", ".webm", ".m3u8")):
            content.append({"type": "image_url", "image_url": {"url": url}})
    return content


def review_with_model(item: dict[str, Any], rules: dict[str, Any], model: str) -> dict[str, Any] | None:
    env = load_env()
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return None
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": build_prompt(item)}],
            "response_format": {"type": "json_object"},
            "max_tokens": 500,
        },
        timeout=45,
    )
    response.raise_for_status()
    text = response.json()["choices"][0]["message"].get("content") or "{}"
    parsed = json.loads(text)
    return normalize_review(parsed, model) if isinstance(parsed, dict) else None


def apply_ins_safety_review(items: list[dict[str, Any]], rules: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    safety = rules.get("safety", {})
    if not safety.get("enabled", True):
        return items, []
    model = str(safety.get("model") or "qwen/qwen3.7-max")
    kept: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in items:
        updated = dict(item)
        try:
            review = review_with_model(updated, rules, model) or fallback_review(updated, rules, model, "model unavailable")
        except Exception as exc:
            review = fallback_review(updated, rules, model, str(exc))
        updated["safetyReview"] = review
        if not review.get("isAllowed", True):
            blocked.append(updated)
        else:
            kept.append(updated)
    print(f"  - INS safety review kept {len(kept)}/{len(items)} items; blocked {len(blocked)}", flush=True)
    return kept, blocked


