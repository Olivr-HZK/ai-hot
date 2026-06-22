from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

from env_utils import load_env
from ua_material_review import media_urls


DEFAULT_MODEL = "qwen/qwen3.7-max"

PRODUCT_MANUAL = """
You are auditing X/Twitter posts for a team-facing social hotspot pipeline.

The current X requirement is based on examples like:
- ChatGPT + Seedance used to create an iPhone-style real-person photo album / vlog workflow.
- GPT Images + Seedance + Suno used to create an iPhone-shot couple video, with prompts and workflow notes.

Products:
Primary focus products: Evoke, Toki, Kavi, Avatar. X product-side acceptance should mainly serve these four products.
1. Evoke: product/UA value for AI portraits, photo enhancement, restoration, style transfer, before-after, old-photo-to-video, real-person photo generation.
2. Toki: product/UA priority for photo-to-video, image-to-video, AI couple/family/pet animation, iPhone/vlog style video, storyboard/prompt workflows, short reusable social video templates.
3. Kavi: product/UA value for one-photo/selfie-to-video, viral AI effects, stylized animation, custom 3D figure, lifelike motion, and trending short-video styles.
4. Avatar: product/UA value for Facebook Instant Game/social puzzle loops that turn profile photos into AI avatars or clay-style images, split them into jigsaw puzzles, and drive sharing/invites.

Proven ad reference patterns from launched creatives:
- A single real-person photo is uploaded and transformed into a finished ad-like result: streamer/creator persona, portrait-to-live-scene, dream portrait, family-safe child princess/fairy/storybook dress-up, or other strong identity upgrade.
- The post shows input/result, before/after, arrow transformation, phone UI, upload button, result carousel, CTA/end-card, App Store/Google Play badge, template-library claim, or "Create Now" style conversion cue.
- Favor materials that can directly become product templates or UA ad scenes, not just attractive images.

Allow product-side X posts only when they clearly provide at least one of:
- an AI tool chain with reusable workflow/prompt/storyboard/process;
- an AI image/video/game generation result that maps to Evoke, Toki, Kavi, or Avatar product features;
- a real-person image material that has explicit AI product, prompt, transformation, template, before-after, enhancement, or photo-to-video value.
- a social game material with avatar generation, puzzle pieces, Facebook Instant Game mechanics, share loops, or friend challenge value for Avatar.

Reject:
- ordinary celebrity, paparazzi, IP/leak, fan, entertainment, or street-style posts;
- celebrity/actor/actress likeness prompts or IP-dependent portrait packs even when they include a prompt;
- traditional photographer portfolio/client shoot/wedding/engagement photos with no AI/tool/template evidence;
- pure anime, manga, illustration, fanart, character design, fantasy character, or game-character content;
- generic beautiful photos without AI product value;
- generic fantasy/anime/princess/fairy images unless they are real-person transformations with clear upload/template/product/ad-structure evidence;
- generic AI portrait prompt dumps without strong before/after, upload/template UI, or clear Evoke/Toki/Kavi/Avatar product mechanics;
- one-click makeup, beauty-filter, or try-on clips where the only value is cosmetic retouching rather than a distinctive reusable AI transformation;
- commercial advertising storyboards, luxury fashion commercial prompts, or brand-ad scripts that mainly demonstrate agency-style ad production rather than broad user-upload templates;
- baseball spectator/broadcast-girl or sports fan-edit derivatives unless user-upload identity transformation, prompt workflow, and reusable product template value are explicit;
- child fantasy portraits that are adultized, suggestive, unsafe, or IP-dependent;
- model/company news, hardware, crypto/Web3, politics, adult/suggestive content, low-quality or weakly reusable material.

Return strict JSON with keys: isAllowed, primaryProduct, recommendedPushObject, confidence, reason.
primaryProduct must be evoke, toki, kavi, avatar_jigsaw, or none. For product-side acceptance, primaryProduct must be one of evoke, toki, kavi, or avatar_jigsaw.
recommendedPushObject must be 浜у搧 when allowed.
"""

HARD_REJECT_KEYWORDS = [
    "anime",
    "manga",
    "ova",
    "cel shading",
    "cel-shading",
    "priestess",
    "salamander spirit",
    "fantasy character",
    "disney princess",
    "ip princess",
    "adultized child",
    "sexy child",
    "character design",
    "character sheet",
    "game character",
    "fanart",
    "genshin",
    "paparazzi",
    "celebrity",
    "celebrity portrait",
    "actor",
    "actress",
    "sadie sink",
    "sydney sweeney",
    "lindsay lohan",
    "street style",
    "bikini",
    "swimsuit",
    "lingerie",
    "cleavage",
    "sexy",
    "seductive",
    "sensual",
    "nsfw",
    "prompt gallery",
    "prompt library",
    "prompt resource",
    "free gallery",
    "viral prompts",
    "copy the ones",
    "meigen7982",
    "booked their photoshoot",
    "engagement shoot",
    "wedding photographer",
    "photographer portfolio",
    "one-click makeup",
    "ai makeup",
    "beauty filter",
    "makeup filter",
    "bare face makeup",
    "generic ai portrait prompt",
    "face lock prompt",
    "high-fidelity ai portrait",
    "advertising storyboard",
    "commercial ad storyboard",
    "commercial video for",
    "luxury fashion commercial",
    "high-end luxury fashion commercial",
    "9-panel cinematic storyboard",
    "strictly following the 9-panel",
    "baseball spectator girl",
    "baseball broadcast girl",
    "korean baseball girl",
    "sports broadcast girl",
    "random spectator girl",
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


def clean_text(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def review_enabled(rules: dict[str, Any]) -> bool:
    cfg = rules.get("x_team_demand", {}) if isinstance(rules.get("x_team_demand"), dict) else {}
    return bool(cfg.get("product_review_enabled", True))


def review_model(rules: dict[str, Any]) -> str:
    cfg = rules.get("x_team_demand", {}) if isinstance(rules.get("x_team_demand"), dict) else {}
    env = load_env()
    return (
        os.environ.get("X_TEAM_PRODUCT_REVIEW_MODEL")
        or env.get("X_TEAM_PRODUCT_REVIEW_MODEL")
        or cfg.get("product_review_model")
        or os.environ.get("OPENROUTER_MODEL")
        or env.get("OPENROUTER_MODEL")
        or DEFAULT_MODEL
    )


def item_text(item: dict[str, Any]) -> str:
    parts = [
        item.get("title"),
        item.get("text"),
        item.get("desc"),
        item.get("summary"),
        item.get("video_summary"),
        item.get("hotspotIntro"),
        " ".join(str(comment) for comment in (item.get("topComments") or [])[:5]),
    ]
    hashtags = item.get("hashtags") or []
    if isinstance(hashtags, list):
        parts.extend(str(tag.get("name") if isinstance(tag, dict) else tag) for tag in hashtags)
    return clean_text(" ".join(str(part or "") for part in parts if part), max_len=1800)


def compact_item(item: dict[str, Any]) -> dict[str, Any]:
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    return {
        "url": clean_text(item.get("hotspotUrl") or item.get("webVideoUrl") or item.get("url")),
        "author": clean_text(author.get("nickName") or author.get("name")),
        "text": item_text(item),
        "mediaType": clean_text(item.get("mediaType")),
        "views": item.get("playCount") or item.get("views"),
        "likes": item.get("diggCount") or item.get("likeCount") or item.get("likes"),
        "comments": item.get("commentCount") or item.get("comments"),
        "searchTerm": item.get("search_term") or item.get("searchQuery"),
        "matchedSearchTerms": item.get("matched_search_terms"),
        "xTeamDemand": item.get("xTeamDemand", {}),
        "xPhotoRelevance": item.get("xPhotoRelevance", {}),
        "keywordProductFit": item.get("productFit", {}),
        "mediaUrls": media_urls(item, limit=3),
    }


def normalize_review(raw: dict[str, Any], model: str) -> dict[str, Any]:
    allowed = raw.get("isAllowed", raw.get("allowed", False))
    if isinstance(allowed, str):
        allowed = allowed.strip().lower() in {"true", "1", "yes", "allowed", "pass"}
    product = clean_text(raw.get("primaryProduct") or raw.get("recommendedProduct") or raw.get("product") or "none").lower()
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
        "recommendedPushObject": clean_text(raw.get("recommendedPushObject") or raw.get("pushObject") or ("浜у搧" if allowed else "")),
        "confidence": max(0.0, min(1.0, confidence)),
        "reason": clean_text(raw.get("reason") or raw.get("rationale"), max_len=280),
        "model": model,
    }


def blocked_review(model: str, reason: str) -> dict[str, Any]:
    return {
        "isAllowed": False,
        "primaryProduct": "none",
        "recommendedPushObject": "",
        "confidence": 0.0,
        "reason": clean_text(reason, max_len=280),
        "model": model,
        "blockedBySystem": True,
    }


def hard_reject_review(item: dict[str, Any], model: str) -> dict[str, Any] | None:
    text = json.dumps(compact_item(item), ensure_ascii=False).lower()
    hits = [keyword for keyword in HARD_REJECT_KEYWORDS if keyword in text]
    if not hits:
        return None
    return blocked_review(model, f"hard rejected by X team product keywords: {', '.join(hits[:5])}")


def review_with_model(item: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    model = review_model(rules)
    hard_reject = hard_reject_review(item, model)
    if hard_reject:
        return hard_reject
    env = load_env()
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return blocked_review(model, "product manual review requires OPENROUTER_API_KEY")
    prompt = (
        "Audit this X post against the product manual. "
        "Return strict JSON only.\n\n"
        f"Manual:\n{PRODUCT_MANUAL}\n\n"
        f"Candidate:\n{json.dumps(compact_item(item), ensure_ascii=False)}"
    )
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "max_tokens": 550,
        },
        timeout=45,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"].get("content") or "{}"
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        return blocked_review(model, "product manual review model did not return a JSON object")
    return normalize_review(parsed, model)


def apply_x_team_product_review(
    items: list[dict[str, Any]],
    rules: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not review_enabled(rules):
        return items, []
    kept: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in items:
        updated = dict(item)
        try:
            review = review_with_model(updated, rules)
        except Exception as exc:
            review = blocked_review(review_model(rules), f"product manual review failed: {exc}")
        updated["xTeamDemandReview"] = review
        if review.get("isAllowed"):
            updated["pushObject"] = "浜у搧"
            details = dict(updated.get("xTeamDemand") or {})
            details["pushObject"] = "浜у搧"
            details["primaryProduct"] = review.get("primaryProduct")
            updated["xTeamDemand"] = details
            kept.append(updated)
        else:
            blocked.append(updated)
    print(f"  - X team product manual review kept {len(kept)}/{len(items)} items; blocked {len(blocked)}", flush=True)
    return kept, blocked

