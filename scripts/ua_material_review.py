from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

from env_utils import load_env


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "review_pool_size": 10,
    "daily_min": 1,
    "daily_max": 1,
    "require_model": True,
    "model": "qwen/qwen3.7-max",
}

UA_MATERIAL_MANUAL = """
You are reviewing high-heat social posts for UA advertising material.

Products:
Primary focus products: Evoke, Toki, Kavi, Avatar. Most accepted materials should serve these four products.
1. Evoke: UA and product. Accept high-quality photo materials that can sell enhancement/restoration/portrait/style benefits.
2. Toki: UA and product. Accept high-quality photo/video ideas that can sell photo-to-video, face animation, pet/couple/family motion, emotional scenes, short templates, or shareable transformations.
3. Kavi: UA and product. Accept photo-to-video, selfie-to-video, viral AI effects, stylized animation, custom 3D figure, and one-photo short-video ideas.
4. Avatar: UA and product. Accept Facebook Instant Game/social puzzle ideas that turn profile photos into AI avatars or clay-style images, then split them into shareable jigsaw puzzles.

Proven ad reference patterns from already-launched creatives:
- Single real-person photo upload -> dramatic result, especially portrait-to-live-scene, streamer/creator persona, fantasy dress-up, princess/fairy/storybook portrait, or family-safe child dream portrait.
- Clear before/after or input/result layout, with an arrow, phone UI, upload button, result carousel, CTA/end-card, App Store/Google Play badge, template-library claim, or "Create Now" style conversion cue.
- Favor vertical mobile ad structures and materials that can become a finished ad, product template, or reusable template-library entry.

Allow non-AI materials when they are high-quality, safe, popular, and reusable as ad creative or product-side material reference: real-person portraits, family/couple/pet scenes, fashion/makeup/hairstyle/outfit, wedding/graduation/holiday/travel, cinematic/creative photos, before-after concepts, emotional scenes, or strong social hooks.
Also allow sports and movie/TV-adjacent real-person/effect references only when they are useful as product material: athlete highlights, celebration poses, training transformations, jersey/poster/card styles, cinematic match entrances, real-person character transformations, trailer/opening-title style edits, red-carpet/interview transformations, or identity-upgrade structures that can become Evoke/Toki/Kavi/Avatar templates or ads.

Reject politics or social-political campaigns, news, hardware/model release/funding, crypto/Web3, adult/suggestive bait, weak celebrity/IP leaks, paparazzi/gossip/spoiler content, pure IP screenshots/role copies, pure memes, low-quality images, pure beautiful fantasy/anime images without upload/template/product evidence, IP-dependent princess/Disney-like concepts, child sexualization, generic AI portrait prompt dumps without clear before/after or template UI, one-click makeup/beauty-filter/try-on clips with only cosmetic retouching, traditional sports/MTB/cycling cinematic edits without AI/template/upload/product evidence, commercial advertising storyboards or luxury fashion commercial prompts without broad user-template reuse, baseball spectator/broadcast-girl fan edits without explicit user-upload transformation or reusable product workflow, and anything without a clear UA hook or reusable ad concept.
"""

HARD_REJECT_KEYWORDS = [
    "politics",
    "political",
    "election",
    "government",
    "president",
    "minister",
    "parliament",
    "war",
    "crypto",
    "web3",
    "hardware leak",
    "model release",
    "funding",
    "onlyfans",
    "nsfw",
    "porn",
    "nude",
    "lingerie",
    "bikini",
    "cleavage",
    "soft porn",
    "ai girlfriend",
    "anime girl",
    "disney princess",
    "ip princess",
    "adultized child",
    "sexy child",
    "one-click makeup",
    "ai makeup",
    "beauty filter",
    "makeup filter",
    "bare face makeup",
    "generic ai portrait prompt",
    "face lock prompt",
    "high-fidelity ai portrait",
    "baseball spectator girl",
    "baseball broadcast girl",
    "korean baseball girl",
    "sports broadcast girl",
    "random spectator girl",
    "mtb",
    "mountain bike",
    "commencal",
    "advertising storyboard",
    "commercial ad storyboard",
    "luxury fashion commercial",
    "high-end luxury fashion commercial",
    "9-panel cinematic storyboard",
    "\u68d2\u7403\u5973\u5b69",
    "\u68d2\u7403\u89c2\u4f17\u5e2d\u5973\u5b69",
    "\u8d5b\u4e8b\u955c\u5934\u5973\u5b69",
    "\u7403\u573a\u5973\u5b69",
    "\u4e00\u952e\u7f8e\u5986",
    "\u7f8e\u5986\u6ee4\u955c",
    "\u7d20\u989c\u7f8e\u5986",
    "\u9ad8\u4fdd\u771fAI\u4eba\u50cf",
    "\u4eba\u50cf\u63d0\u793a\u8bcd",
    "\u5199\u771f\u63d0\u793a\u8bcd",
    "\u9762\u90e8\u7279\u5f81\u9501\u5b9a",
]


def config(rules: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    configured = rules.get("ua_material_review", {})
    if isinstance(configured, dict):
        for key, value in configured.items():
            if value is not None:
                merged[key] = value
    return merged


def clean_text(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def item_key(item: dict[str, Any]) -> str:
    return clean_text(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url") or item.get("upsertKey") or item.get("id"))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def is_ua_material_candidate(item: dict[str, Any]) -> bool:
    details = item.get("uaMaterialTargeting")
    return isinstance(details, dict) and bool(details.get("isTarget"))


def review_pool_size(rules: dict[str, Any]) -> int:
    cfg = config(rules)
    return max(1, int(cfg.get("review_pool_size", 10) or 10))


def daily_max(rules: dict[str, Any]) -> int:
    return max(0, int(config(rules).get("daily_max", 1) or 1))


def daily_min(rules: dict[str, Any]) -> int:
    return max(0, int(config(rules).get("daily_min", 1) or 1))


def media_urls(item: dict[str, Any], limit: int = 3) -> list[str]:
    values: list[Any] = []
    for key in ["mediaUrls", "imageUrls", "images", "photos", "media"]:
        value = item.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value:
            values.append(value)
    for key in ["displayUrl", "display_url", "thumbnail", "image", "photo", "url"]:
        value = item.get(key)
        if value:
            values.append(value)
    urls: list[str] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("url") or value.get("src") or value.get("display_url") or value.get("image_url")
        text = clean_text(value)
        if text.startswith("http") and text not in urls:
            urls.append(text)
        if len(urls) >= limit:
            break
    return urls


def item_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("text"),
        item.get("title"),
        item.get("desc"),
        item.get("summary"),
        item.get("video_summary"),
        item.get("hotspotIntro"),
        " ".join(str(tag) for tag in item.get("hashtags") or []),
    ]
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    parts.append(author.get("nickName"))
    parts.append(author.get("name"))
    return clean_text(" ".join(str(part or "") for part in parts if part), max_len=1800)


def compact_item(item: dict[str, Any], platform: str) -> dict[str, Any]:
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    return {
        "platform": platform,
        "url": clean_text(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url")),
        "author": clean_text(author.get("nickName") or author.get("name")),
        "text": item_text(item),
        "mediaType": clean_text(item.get("mediaType")),
        "views": item.get("playCount") or item.get("view_count") or item.get("views"),
        "likes": item.get("diggCount") or item.get("likeCount") or item.get("likes"),
        "comments": item.get("commentCount") or item.get("reply_count") or item.get("comments"),
        "topComments": item.get("topComments", [])[:5] if isinstance(item.get("topComments"), list) else [],
        "targeting": item.get("uaMaterialTargeting", {}),
        "mediaUrls": media_urls(item, limit=3),
    }


def hard_reject_review(item: dict[str, Any], model: str, platform: str) -> dict[str, Any] | None:
    text = json.dumps(compact_item(item, platform), ensure_ascii=False).lower()
    hits = [keyword for keyword in HARD_REJECT_KEYWORDS if keyword in text]
    if not hits:
        return None
    return {
        "isAllowed": False,
        "recommendedProduct": "none",
        "recommendedPushObject": "",
        "adUseCase": "",
        "confidence": 1.0,
        "reason": f"hard rejected by UA material risk keywords: {', '.join(hits[:5])}",
        "model": model,
        "deterministicReject": True,
    }


def normalize_review(raw: dict[str, Any], model: str) -> dict[str, Any]:
    allowed = raw.get("isAllowed", raw.get("allowed", False))
    if isinstance(allowed, str):
        allowed = allowed.strip().lower() in {"true", "1", "yes", "allowed", "pass"}
    product = clean_text(raw.get("recommendedProduct") or raw.get("primaryProduct") or raw.get("product") or "none").lower()
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
        "recommendedProduct": product,
        "recommendedPushObject": clean_text(raw.get("recommendedPushObject") or raw.get("pushObject") or "UA") or "UA",
        "adUseCase": clean_text(raw.get("adUseCase") or raw.get("useCase") or raw.get("creativeAngle"), max_len=220),
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": clean_text(raw.get("reason") or raw.get("rationale"), max_len=260),
        "model": model,
    }


def normalize_push_object(value: Any) -> str:
    text = clean_text(value).lower()
    if text in {"all", "aii"}:
        return "ALL"
    if text in {"product", "\u4ea7\u54c1"}:
        return "\u4ea7\u54c1"
    if text == "ua":
        return "UA"
    return ""


def push_object_for_material_review(item: dict[str, Any]) -> str:
    review = item.get("uaMaterialReview")
    review = review if isinstance(review, dict) else {}
    product = clean_text(review.get("recommendedProduct")).lower()
    recommended = normalize_push_object(review.get("recommendedPushObject"))
    if product in {"evoke", "toki", "kavi", "avatar_jigsaw"}:
        return "ALL"
    if recommended in {"ALL", "\u4ea7\u54c1"}:
        return "ALL"
    return "UA"


def blocked_review(model: str, reason: str) -> dict[str, Any]:
    return {
        "isAllowed": False,
        "recommendedProduct": "none",
        "recommendedPushObject": "",
        "adUseCase": "",
        "confidence": 0.0,
        "reason": clean_text(reason, max_len=260),
        "model": model,
        "blockedBySystem": True,
    }


def review_model(rules: dict[str, Any]) -> str:
    cfg = config(rules)
    env = load_env()
    return (
        os.environ.get("UA_MATERIAL_REVIEW_MODEL")
        or env.get("UA_MATERIAL_REVIEW_MODEL")
        or cfg.get("model")
        or os.environ.get("OPENROUTER_MODEL")
        or env.get("OPENROUTER_MODEL")
        or DEFAULT_CONFIG["model"]
    )


def review_with_model(item: dict[str, Any], rules: dict[str, Any], platform: str) -> dict[str, Any]:
    cfg = config(rules)
    model = review_model(rules)
    hard_reject = hard_reject_review(item, model, platform)
    if hard_reject:
        return hard_reject
    env = load_env()
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        reason = "model required but OPENROUTER_API_KEY is missing" if cfg.get("require_model", True) else "OPENROUTER_API_KEY is missing; no non-model UA fallback is configured"
        return blocked_review(model, reason)
    prompt = (
        "Audit this social post against the UA material manual. "
        "Return strict JSON with keys: isAllowed, recommendedProduct, recommendedPushObject, adUseCase, confidence, reason. "
        "recommendedProduct must be evoke, toki, kavi, avatar_jigsaw, or none. recommendedPushObject must be UA or ALL when allowed. "
        "Use ALL for Evoke/Toki/Kavi/Avatar ad material references that are also useful for product-side template, effect, game-loop, or material-library discovery; "
        "use UA only for purely ad-copy/positioning references that still clearly serve Evoke, Toki, Kavi, or Avatar. "
        "Give extra credit to proven ad patterns: single-photo upload, strong before/after, portrait-to-live-scene, streamer/creator persona, family-safe storybook/princess/fairy/dress-up transformation, vertical mobile ad UI, CTA/end-card, and template-library selling points. "
        "For sports or movie/TV-adjacent material, allow only reusable human/effect structures such as athlete action, celebration, training transformation, poster/card styling, cinematic entrance, character identity transformation, trailer/opening-title edit, or red-carpet/interview transformation. "
        "Do not allow generic fantasy/anime/pretty portrait material unless it has clear upload/template/product/ad-structure evidence. "
        "Do not allow pure sports/news discussion, score updates, celebrity gossip, paparazzi/leaks/spoilers, pure IP screenshots, or low-quality cosplay. "
        "Allow non-AI materials only when they are clearly reusable as UA advertising creative or product-side material reference for one of the products.\n\n"
        f"Manual:\n{UA_MATERIAL_MANUAL}\n\n"
        f"Candidate:\n{json.dumps(compact_item(item, platform), ensure_ascii=False)}"
    )
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "max_tokens": 600,
        },
        timeout=45,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"].get("content") or "{}"
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("UA material review model did not return a JSON object")
    return normalize_review(parsed, model)


def mark_ua_material_candidates(items: list[dict[str, Any]], rules: dict[str, Any], *, platform: str, reason: str) -> list[dict[str, Any]]:
    limit = review_pool_size(rules)
    marked: list[dict[str, Any]] = []
    for index, item in enumerate(items[:limit], 1):
        updated = dict(item)
        updated["pushObject"] = "UA"
        updated["uaMaterialTargeting"] = {
            "isTarget": True,
            "platform": platform,
            "reviewPoolRank": index,
            "reviewPoolSize": limit,
            "reason": reason,
        }
        marked.append(updated)
    return marked


def force_ua_material_push_object(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated_items: list[dict[str, Any]] = []
    for item in items:
        if not is_ua_material_candidate(item):
            updated_items.append(item)
            continue
        updated = dict(item)
        details = dict(updated.get("uaMaterialTargeting") or {})
        push_object = push_object_for_material_review(updated)
        details["pushObject"] = push_object
        updated["uaMaterialTargeting"] = details
        updated["pushObject"] = push_object
        updated_items.append(updated)
    return updated_items


def merge_unique_preserving_ua_material(primary: list[dict[str, Any]], extras: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for item in [*extras, *primary]:
        key = item_key(item)
        if key and key in index_by_key:
            existing_index = index_by_key[key]
            existing = merged[existing_index]
            if is_ua_material_candidate(existing) and not is_ua_material_candidate(item):
                updated = dict(item)
                details = dict(existing.get("uaMaterialTargeting") or {})
                if isinstance(existing.get("uaMaterialReview"), dict):
                    updated["uaMaterialReview"] = existing["uaMaterialReview"]
                push_object = push_object_for_material_review(updated)
                details["pushObject"] = push_object
                updated["uaMaterialTargeting"] = details
                updated["pushObject"] = push_object
                merged[existing_index] = updated
            elif is_ua_material_candidate(item) and not is_ua_material_candidate(existing):
                updated = dict(existing)
                details = dict(item.get("uaMaterialTargeting") or {})
                if isinstance(item.get("uaMaterialReview"), dict):
                    updated["uaMaterialReview"] = item["uaMaterialReview"]
                push_object = push_object_for_material_review(updated)
                details["pushObject"] = push_object
                updated["uaMaterialTargeting"] = details
                updated["pushObject"] = push_object
                merged[existing_index] = updated
            continue
        if key:
            index_by_key[key] = len(merged)
        merged.append(item)
    return merged


def apply_ua_material_review(
    items: list[dict[str, Any]],
    rules: dict[str, Any],
    *,
    platform: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cfg = config(rules)
    if not cfg.get("enabled", True):
        return items, []
    kept: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    reviewed = 0
    for item in items:
        if not is_ua_material_candidate(item):
            kept.append(item)
            continue
        reviewed += 1
        updated = dict(item)
        try:
            review = review_with_model(updated, rules, platform)
        except Exception as exc:
            review = blocked_review(review_model(rules), f"model review failed: {exc}")
        updated["uaMaterialReview"] = review
        if review.get("isAllowed"):
            push_object = push_object_for_material_review(updated)
            details = dict(updated.get("uaMaterialTargeting") or {})
            details["pushObject"] = push_object
            updated["uaMaterialTargeting"] = details
            updated["pushObject"] = push_object
            kept.append(updated)
        else:
            blocked.append(updated)
    if reviewed:
        print(f"  - {platform.upper()} UA material review kept {len([item for item in kept if is_ua_material_candidate(item)])}/{reviewed}; blocked {len(blocked)}", flush=True)
    return kept, blocked


def keep_required_ua_material(items: list[dict[str, Any]], rules: dict[str, Any], *, platform: str) -> list[dict[str, Any]]:
    max_count = daily_max(rules)
    min_count = daily_min(rules)
    regular = [item for item in items if not is_ua_material_candidate(item)]
    ua_items = force_ua_material_push_object([item for item in items if is_ua_material_candidate(item)])
    if max_count <= 0:
        return regular
    selected = sorted(ua_items, key=lambda item: safe_float(item.get("heatValue")), reverse=True)[:max_count]
    if selected:
        best = selected[0]
        print(
            f"  - Required {platform.upper()} UA material kept {len(selected)}/{len(ua_items)} passed candidates; best heat {best.get('heatValue', 0)}",
            flush=True,
        )
    elif min_count > 0:
        print(f"  - WARNING: no {platform.upper()} UA material candidate survived downstream filters/reviews", flush=True)
    return [*regular, *selected]

