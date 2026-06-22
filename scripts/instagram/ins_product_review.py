from __future__ import annotations

import json
import os
from typing import Any

import requests

from env_utils import load_env
from ins_scoring import clean_text, media_urls


PRODUCT_REVIEW_MANUAL = """
Project products:
Primary focus products: Evoke, Toki, Kavi, Avatar. Most Instagram materials should serve these four products.
1. Evoke: UA and product. For Instagram, accept high-quality image/carousel materials with reusable photo value even when they are not direct feature demos: real-person portraits, artistic portraits, editorial/fashion photos, creative photos, AI photography prompts, photo style transfer, family/couple/pet photos, old photo restoration, blur removal, scratch/wrinkle repair, black-and-white colorization, portrait generation, family memory photos, and old-photo-to-video.
2. Toki: UA and product, product-side priority above 70%. For Instagram, accept image materials that can become photo-to-video ideas: dynamic human poses, emotional scenes, couple/pet/family scenes, cinematic portraits, action-figure/figurine/toyification, Labubu-like toyification, AI emote, face animation, AI transform, AI magic, AI hug/couple/pet animation, AI dance, and short social video templates.
3. Kavi: UA and product. Accept selfie/photo-to-video, viral AI effects, stylized animation, custom 3D figure, lifelike motion, and trending short-video style references.
4. Avatar: UA and product. Accept avatar generation, clay avatar, profile photo filters, jigsaw puzzle mechanics, Facebook Instant Game sharing loops, friend challenge, and invite/share materials.
Proven launched-ad patterns to prioritize: single real-person photo upload, strong input/result or before/after transformation, portrait-to-live-scene, streamer/creator persona, family-safe dream/princess/fairy/storybook dress-up, vertical mobile ad UI, upload button, result carousel, CTA/end-card, App Store/Google Play badge, template-library or daily viral-trend selling point.
Reject: AI/model/company news, funding, hardware, crypto/Web3, politics or social-political campaign materials, adult/suggestive visuals, weakly reusable celebrity/IP leaks, and materials with no clear photo, video, UA, product feature, or reusable visual template value.
Also reject pure beautiful fantasy/anime/princess/fairy images without upload/template/product/ad-structure evidence, IP-dependent princess/Disney-like concepts, and any child material that is adultized or suggestive.
Important: Instagram is primarily an image-material source. High-quality safe images can be accepted for Evoke/Toki/Kavi/Avatar if the visual style, composition, prompt, effect, or game loop can be reused by these products, even if the caption does not explicitly mention the product feature.
"""

POLITICAL_REJECT_KEYWORDS = [
    "politics",
    "political",
    "election",
    "government",
    "president",
    "minister",
    "parliament",
    "new india",
    "youth leadership",
    "stronger future",
]


def review_enabled(rules: dict[str, Any]) -> bool:
    cfg = rules.get("product_v2_review", {}) if isinstance(rules.get("product_v2_review"), dict) else {}
    return bool(cfg.get("enabled", True))


def review_model(rules: dict[str, Any]) -> str:
    cfg = rules.get("product_v2_review", {}) if isinstance(rules.get("product_v2_review"), dict) else {}
    env = load_env()
    return (
        os.environ.get("INS_PRODUCT_REVIEW_MODEL")
        or env.get("INS_PRODUCT_REVIEW_MODEL")
        or cfg.get("model")
        or os.environ.get("OPENROUTER_MODEL")
        or env.get("OPENROUTER_MODEL")
        or "qwen/qwen3.7-max"
    )


def compact_item(item: dict[str, Any]) -> dict[str, Any]:
    fit = item.get("insProductFit") if isinstance(item.get("insProductFit"), dict) else {}
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    return {
        "url": clean_text(item.get("hotspotUrl") or item.get("webVideoUrl")),
        "author": clean_text(author.get("nickName") or author.get("uniqueId")),
        "caption": clean_text(item.get("text") or item.get("title") or item.get("desc"), max_len=1200),
        "summary": clean_text(item.get("summary"), max_len=500),
        "hashtags": item.get("hashtags", [])[:15] if isinstance(item.get("hashtags"), list) else [],
        "mediaType": clean_text(item.get("mediaType")),
        "likes": item.get("diggCount") or item.get("likeCount"),
        "comments": item.get("commentCount"),
        "heatValue": item.get("heatValue"),
        "pushObject": item.get("pushObject"),
        "keywordProductFit": fit,
        "mediaUrls": media_urls(item, limit=3),
    }


def normalize_review(raw: dict[str, Any], model: str) -> dict[str, Any]:
    allowed = raw.get("isAllowed", raw.get("allowed", False))
    if isinstance(allowed, str):
        allowed = allowed.strip().lower() in {"true", "1", "yes", "allowed", "pass"}
    product = clean_text(raw.get("primaryProduct") or raw.get("product") or "").lower()
    if product not in {"evoke", "toki", "kavi", "avatar_jigsaw", "ai_avatar_jigsaw", "none"}:
        product = "none"
    if product == "ai_avatar_jigsaw":
        product = "avatar_jigsaw"
    if product == "none":
        allowed = False
    try:
        confidence = float(raw.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "isAllowed": bool(allowed),
        "primaryProduct": product,
        "recommendedPushObject": clean_text(raw.get("recommendedPushObject") or raw.get("pushObject")),
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": clean_text(raw.get("reason") or raw.get("rationale"), max_len=260),
        "model": model,
    }


def fallback_review(item: dict[str, Any], model: str, warning: str) -> dict[str, Any]:
    fit = item.get("insProductFit") if isinstance(item.get("insProductFit"), dict) else {}
    return {
        "isAllowed": bool(fit.get("isRelevant")),
        "primaryProduct": clean_text(fit.get("primaryProduct") or "none"),
        "recommendedPushObject": clean_text(item.get("pushObject")),
        "confidence": 0.0,
        "reason": "model unavailable; kept by keyword product fit" if fit.get("isRelevant") else "model unavailable and keyword product fit failed",
        "model": model,
        "fallback": True,
        "warning": clean_text(warning, max_len=180),
    }


def hard_reject_review(item: dict[str, Any], model: str) -> dict[str, Any] | None:
    text = json.dumps(compact_item(item), ensure_ascii=False).lower()
    hits = [keyword for keyword in POLITICAL_REJECT_KEYWORDS if keyword in text]
    if not hits:
        return None
    return {
        "isAllowed": False,
        "primaryProduct": "none",
        "recommendedPushObject": "",
        "confidence": 1.0,
        "reason": f"hard rejected by sensitive political/social topic keywords: {', '.join(hits[:5])}",
        "model": model,
        "deterministicReject": True,
    }


def review_with_model(item: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    env = load_env()
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    model = review_model(rules)
    hard_reject = hard_reject_review(item, model)
    if hard_reject:
        return hard_reject
    if not api_key:
        return fallback_review(item, model, "missing OPENROUTER_API_KEY")
    prompt = (
        "You are auditing Instagram material against a product requirement manual for a social hotspot pipeline. "
        "Return strict JSON with keys: isAllowed, primaryProduct, recommendedPushObject, confidence, reason. "
        "primaryProduct must be evoke, toki, kavi, avatar_jigsaw, or none. recommendedPushObject must be UA, 浜у搧, ALL, or empty. "
        "Allow only materials with clear UA or product value for the manual. Product-side materials should mainly serve Evoke, Toki, Kavi, or Avatar, with Toki still strongly favored among video-template product materials.\n\n"
        "Prioritize launched-ad patterns: single-photo upload, before/after, portrait-to-live-scene, streamer/creator persona, family-safe storybook/princess/fairy/dress-up transformation, mobile ad UI, CTA/end-card, and template-library selling points. "
        "Reject generic fantasy/anime/pretty portrait material unless it clearly shows product/template/ad-structure evidence.\n\n"
        f"Manual:\n{PRODUCT_REVIEW_MANUAL}\n\n"
        f"Candidate:\n{json.dumps(compact_item(item), ensure_ascii=False)}"
    )
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "max_tokens": 500,
        },
        timeout=45,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"].get("content") or "{}"
    parsed = json.loads(content)
    return normalize_review(parsed if isinstance(parsed, dict) else {}, model)


def apply_product_v2_review(items: list[dict[str, Any]], rules: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not review_enabled(rules):
        return items, []
    kept: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in items:
        updated = dict(item)
        try:
            review = review_with_model(updated, rules)
        except Exception as exc:
            review = fallback_review(updated, review_model(rules), str(exc))
        updated["productManualReview"] = review
        if review.get("isAllowed"):
            kept.append(updated)
        else:
            blocked.append(updated)
    print(f"  - INS product_v2 manual review kept {len(kept)}/{len(items)} items; blocked {len(blocked)}", flush=True)
    return kept, blocked

