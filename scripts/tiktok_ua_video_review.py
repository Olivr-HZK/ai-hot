from __future__ import annotations

import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import requests

from env_utils import env_bool, env_int, load_env
from visual_dedupe import image_input_urls


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3.6-flash"
VALID_PRODUCTS = {"evoke", "toki", "kavi", "avatar"}
VALID_VISIBILITY = {"full_body", "half_body", "portrait", "group", "tiny_unclear", "none"}

PRODUCT_RUBRIC = """
TikTok-UA video material must serve Evoke, Toki, Kavi, or Avatar.

Hard gates:
- The attached visual evidence must show a real person or a clear human portrait/subject.
- Text alone is not enough to claim a person is visible.
- The material must be reusable as a video template or image template.
- Reject pure text, logos, scoreboards, distant stadium views, pure gameplay, object-only clips,
  landscape footage, meme screenshots, pure IP clips, news, politics, war, gossip, and score discussion.

Accept when reusable:
- Toki/Kavi: real-person dance trend/challenge, fixed-camera choreography, visible body movement,
  hand/foot/floor moves, repeatable pose/action, photo-to-video motion template, selfie-to-video,
  action template, celebration pose, training transformation, match entrance, short vertical template.
- Evoke: portrait/photo before-after, portrait transition, photo slideshow, family/holiday memory photo,
  old photo to video, high-quality real-person portrait style reference.
- Avatar: profile/avatar/puzzle/social game structure with a human headshot or avatar result.
- Sports can pass only when it is human-centered and reusable as a pose, poster/card, jersey portrait,
  cinematic entrance, celebration, action freeze, or ad/template structure.
- Dance can pass only when it has clear reusable choreography, challenge/remix value, or motion-template value.
"""


def clean_text(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "on", "allowed", "pass"}


def float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def review_config(rules: dict[str, Any] | None = None) -> dict[str, Any]:
    env = load_env(override=False)
    configured = (rules or {}).get("tiktok_ua_video_review")
    configured = configured if isinstance(configured, dict) else {}
    enabled_default = bool(configured.get("enabled", True))
    return {
        "enabled": env_bool("TIKTOK_UA_VIDEO_REVIEW_ENABLED", enabled_default, {**env, **os.environ}),
        "model": (
            os.environ.get("TIKTOK_UA_VIDEO_REVIEW_MODEL")
            or env.get("TIKTOK_UA_VIDEO_REVIEW_MODEL")
            or configured.get("model")
            or os.environ.get("OPENROUTER_MODEL")
            or env.get("OPENROUTER_MODEL")
            or DEFAULT_MODEL
        ),
        "timeout_seconds": env_int("TIKTOK_UA_VIDEO_REVIEW_TIMEOUT_SECONDS", int(configured.get("timeout_seconds", 45) or 45), {**env, **os.environ}),
        "max_concurrency": max(
            1,
            env_int("TIKTOK_UA_VIDEO_REVIEW_MAX_CONCURRENCY", int(configured.get("max_concurrency", 3) or 3), {**env, **os.environ}),
        ),
        "fail_open": env_bool("TIKTOK_UA_VIDEO_REVIEW_FAIL_OPEN", bool(configured.get("fail_open", False)), {**env, **os.environ}),
        "frame_mode": clean_text(
            os.environ.get("TIKTOK_UA_VIDEO_REVIEW_FRAME_MODE")
            or env.get("TIKTOK_UA_VIDEO_REVIEW_FRAME_MODE")
            or configured.get("frame_mode")
            or "cover_only"
        ),
    }


def item_url(item: dict[str, Any]) -> str:
    video_meta = item.get("videoMeta") if isinstance(item.get("videoMeta"), dict) else {}
    return clean_text(item.get("hotspotUrl") or item.get("webVideoUrl") or video_meta.get("webVideoUrl") or item.get("url"))


def item_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ["title", "text", "desc", "summary", "video_summary", "hotspotIntro", "sourceQuery", "searchQuery"]:
        if item.get(key):
            parts.append(str(item.get(key)))
    hashtags = item.get("hashtags")
    if isinstance(hashtags, list):
        for tag in hashtags:
            if isinstance(tag, dict):
                parts.append(str(tag.get("name") or tag.get("title") or tag.get("hashtag") or ""))
            else:
                parts.append(str(tag))
    discovery = item.get("tiktokKeywordDiscovery") if isinstance(item.get("tiktokKeywordDiscovery"), dict) else {}
    for key in ["keywordLayers", "fitTypes", "sourceQueries"]:
        value = discovery.get(key)
        if isinstance(value, list):
            parts.extend(str(entry) for entry in value)
    return clean_text(" ".join(part for part in parts if part), max_len=1600)


def compact_item(item: dict[str, Any], image_urls: list[str]) -> dict[str, Any]:
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    return {
        "url": item_url(item),
        "author": clean_text(author.get("nickName") or author.get("name") or item.get("author")),
        "text": item_text(item),
        "sourceQuery": clean_text(item.get("sourceQuery") or item.get("searchQuery")),
        "layer": clean_text(item.get("tiktokKeywordDiscoveryLayer")),
        "fitType": clean_text(item.get("tiktokKeywordDiscoveryFitType")),
        "views": item.get("playCount") or item.get("views"),
        "likes": item.get("diggCount") or item.get("likeCount") or item.get("likes"),
        "comments": item.get("commentCount") or item.get("comments"),
        "duration": (item.get("videoMeta") or {}).get("duration") if isinstance(item.get("videoMeta"), dict) else item.get("duration"),
        "imageUrls": image_urls,
    }


def is_review_image_url(url: str) -> bool:
    text = clean_text(url)
    if not text.startswith(("http://", "https://")):
        return False
    lowered = text.lower().split("?", 1)[0]
    if lowered.endswith((".mp4", ".m3u8", ".mov", ".webm")):
        return False
    if "tiktok.com/@" in lowered and "/video/" in lowered:
        return False
    if "www.tiktok.com" in lowered or "m.tiktok.com" in lowered:
        return False
    return True


def review_image_urls(item: dict[str, Any], limit: int = 3) -> list[str]:
    urls: list[str] = []
    for url in image_input_urls(item, limit=8):
        if is_review_image_url(url) and url not in urls:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def cache_key(item: dict[str, Any], image_urls: list[str]) -> str:
    raw = json.dumps(
        {
            "url": item_url(item),
            "images": image_urls[:3],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def blocked_review(
    *,
    model: str,
    reason: str,
    image_urls: list[str] | None = None,
    category: str = "model_failed",
    confidence: float = 0.0,
    fail_open: bool = False,
) -> dict[str, Any]:
    allow = bool(fail_open)
    return {
        "allow": allow,
        "hasHuman": allow,
        "humanVisibility": "none" if not allow else "tiny_unclear",
        "isTemplateMaterial": allow,
        "templateFormats": [],
        "matchedProducts": [],
        "confidence": confidence,
        "reason": clean_text(reason, max_len=260),
        "rejectReason": "" if allow else clean_text(reason, max_len=260),
        "model": model,
        "evidence": {"imageUrlsUsed": image_urls or [], "frameMode": "cover_only"},
        "failureCategory": category,
    }


def normalize_products(values: Any) -> list[str]:
    if isinstance(values, str):
        values = re.split(r"[,;/\s]+", values)
    if not isinstance(values, list):
        return []
    products: list[str] = []
    for value in values:
        text = clean_text(value).lower().replace("avatar_jigsaw", "avatar")
        if text in VALID_PRODUCTS and text not in products:
            products.append(text)
    return products


def normalize_template_formats(values: Any) -> list[str]:
    if isinstance(values, str):
        values = re.split(r"[,;/]+", values)
    if not isinstance(values, list):
        return []
    formats: list[str] = []
    for value in values:
        text = re.sub(r"[^a-z0-9_]+", "_", clean_text(value).lower()).strip("_")
        if text and text not in formats:
            formats.append(text)
    return formats


def normalize_review(raw: dict[str, Any], model: str, image_urls: list[str]) -> dict[str, Any]:
    has_human = bool_value(raw.get("hasHuman"), False)
    is_template = bool_value(raw.get("isTemplateMaterial"), False)
    products = normalize_products(raw.get("matchedProducts"))
    requested_allow = bool_value(raw.get("allow", raw.get("isAllowed")), False)
    visibility = clean_text(raw.get("humanVisibility") or "none").lower()
    if visibility not in VALID_VISIBILITY:
        visibility = "none"
    confidence = max(0.0, min(1.0, float_value(raw.get("confidence"), 0.0)))
    allow = bool(requested_allow and has_human and is_template and products)
    if not has_human:
        reject = "no visible person or clear human subject in visual evidence"
    elif not is_template:
        reject = "not reusable as a video or image template"
    elif not products:
        reject = "does not match Evoke/Toki/Kavi/Avatar material needs"
    elif not requested_allow:
        reject = clean_text(raw.get("rejectReason") or raw.get("reason") or "model rejected candidate", max_len=260)
    else:
        reject = ""
    return {
        "allow": allow,
        "hasHuman": has_human,
        "humanVisibility": visibility,
        "isTemplateMaterial": is_template,
        "templateFormats": normalize_template_formats(raw.get("templateFormats")),
        "matchedProducts": products,
        "confidence": confidence,
        "reason": clean_text(raw.get("reason") or raw.get("rationale"), max_len=260),
        "rejectReason": reject or None,
        "model": model,
        "evidence": {"imageUrlsUsed": image_urls, "frameMode": "cover_only"},
    }


def parse_json_object(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        for entry in content:
            if isinstance(entry, dict):
                return entry
        return {}
    text = clean_text(content)
    if not text:
        return {}
    text = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text.strip()).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        for entry in parsed:
            if isinstance(entry, dict):
                return entry
    return {}


def build_messages(item: dict[str, Any], image_urls: list[str]) -> list[dict[str, Any]]:
    system = (
        "You are a strict TikTok-UA visual material reviewer. "
        "You must decide whether a TikTok video can enter UA material output. "
        "Use attached image evidence as the only proof that a person is visible. "
        "Return strict JSON only."
    )
    user_text = (
        "Audit this TikTok candidate. It may pass only when visual evidence shows a person and "
        "the material can become a video template or image template for Evoke, Toki, Kavi, or Avatar. "
        "Return JSON keys: allow, hasHuman, humanVisibility, isTemplateMaterial, templateFormats, "
        "matchedProducts, confidence, reason, rejectReason. "
        "humanVisibility must be full_body, half_body, portrait, group, tiny_unclear, or none. "
        "matchedProducts must contain only evoke, toki, kavi, avatar.\n\n"
        f"Rubric:\n{PRODUCT_RUBRIC}\n\n"
        f"Candidate:\n{json.dumps(compact_item(item, image_urls), ensure_ascii=False)}"
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for url in image_urls[:3]:
        content.append({"type": "image_url", "image_url": {"url": url}})
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]


def review_with_openrouter(item: dict[str, Any], cfg: dict[str, Any], image_urls: list[str]) -> dict[str, Any]:
    env = load_env(override=False)
    model = str(cfg["model"])
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    if not image_urls:
        return blocked_review(model=model, reason="missing visual evidence image URL", image_urls=[], category="no_evidence", fail_open=bool(cfg["fail_open"]))
    if not api_key:
        return blocked_review(
            model=model,
            reason="OPENROUTER_API_KEY is missing; TikTok-UA visual review is fail-closed",
            image_urls=image_urls,
            category="model_failed",
            fail_open=bool(cfg["fail_open"]),
        )
    response = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": build_messages(item, image_urls),
            "response_format": {"type": "json_object"},
            "max_tokens": 700,
        },
        timeout=int(cfg["timeout_seconds"]),
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"].get("content") or "{}"
    parsed = parse_json_object(content)
    if not parsed:
        raise ValueError("TikTok-UA video review model did not return a JSON object")
    return normalize_review(parsed, model, image_urls)


def review_item(item: dict[str, Any], cfg: dict[str, Any], cached: dict[str, dict[str, Any]]) -> dict[str, Any]:
    image_urls = review_image_urls(item, limit=3)
    key = cache_key(item, image_urls)
    if key in cached:
        review = dict(cached[key])
        review["cacheHit"] = True
        updated = dict(item)
        updated["tiktokUaVideoReview"] = review
        return updated
    try:
        review = review_with_openrouter(item, cfg, image_urls)
    except Exception as exc:
        review = blocked_review(
            model=str(cfg["model"]),
            reason=f"model review failed: {exc}",
            image_urls=image_urls,
            category="model_failed",
            fail_open=bool(cfg["fail_open"]),
        )
    review["cacheKey"] = key
    review["cacheHit"] = False
    updated = dict(item)
    updated["tiktokUaVideoReview"] = review
    return updated


def load_cache(artifact_dir: Path | None) -> dict[str, dict[str, Any]]:
    if artifact_dir is None:
        return {}
    cache: dict[str, dict[str, Any]] = {}
    for name in ["08_ua_video_review.json", "08_ua_video_review_rejected.json"]:
        path = artifact_dir / name
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            review = item.get("tiktokUaVideoReview")
            if not isinstance(review, dict):
                continue
            key = clean_text(review.get("cacheKey"))
            if key:
                cache[key] = review
    return cache


def summarize(reviewed: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total": len(reviewed),
        "reviewed": len(reviewed),
        "allowed": 0,
        "rejected": 0,
        "noHuman": 0,
        "noTemplate": 0,
        "noProduct": 0,
        "noEvidence": 0,
        "modelFailed": 0,
        "cacheHit": 0,
    }
    for item in reviewed:
        review = item.get("tiktokUaVideoReview") if isinstance(item.get("tiktokUaVideoReview"), dict) else {}
        if review.get("allow"):
            summary["allowed"] += 1
        else:
            summary["rejected"] += 1
        if review.get("cacheHit"):
            summary["cacheHit"] += 1
        if not review.get("hasHuman"):
            summary["noHuman"] += 1
        if not review.get("isTemplateMaterial"):
            summary["noTemplate"] += 1
        if not review.get("matchedProducts"):
            summary["noProduct"] += 1
        category = clean_text(review.get("failureCategory"))
        if category == "no_evidence":
            summary["noEvidence"] += 1
        if category == "model_failed":
            summary["modelFailed"] += 1
    return summary


def write_artifacts(artifact_dir: Path | None, kept: list[dict[str, Any]], rejected: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    if artifact_dir is None:
        return
    artifact_dir.mkdir(parents=True, exist_ok=True)
    allowed_payload = {"summary": summary, "items": kept}
    rejected_payload = {"summary": summary, "items": rejected}
    (artifact_dir / "08_ua_video_review.json").write_text(json.dumps(allowed_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (artifact_dir / "08_ua_video_review_rejected.json").write_text(json.dumps(rejected_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_tiktok_ua_video_review(
    items: list[dict[str, Any]],
    rules: dict[str, Any],
    *,
    artifact_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    cfg = review_config(rules)
    if not cfg["enabled"]:
        summary = {"total": len(items), "reviewed": 0, "allowed": len(items), "rejected": 0, "disabled": True}
        write_artifacts(artifact_dir, items, [], summary)
        print("  - TikTok-UA video review disabled", flush=True)
        return items, [], summary

    cached = load_cache(artifact_dir)
    with ThreadPoolExecutor(max_workers=int(cfg["max_concurrency"])) as executor:
        reviewed = list(executor.map(lambda item: review_item(item, cfg, cached), items))

    kept = [item for item in reviewed if (item.get("tiktokUaVideoReview") or {}).get("allow")]
    rejected = [item for item in reviewed if not (item.get("tiktokUaVideoReview") or {}).get("allow")]
    summary = summarize(reviewed)
    summary["model"] = cfg["model"]
    summary["frameMode"] = cfg["frame_mode"]
    write_artifacts(artifact_dir, kept, rejected, summary)
    print(
        "  - TikTok-UA video review kept "
        f"{summary['allowed']}/{summary['total']}; rejected={summary['rejected']}, "
        f"noHuman={summary['noHuman']}, noTemplate={summary['noTemplate']}, "
        f"modelFailed={summary['modelFailed']}, cacheHit={summary['cacheHit']}",
        flush=True,
    )
    return kept, rejected, summary
