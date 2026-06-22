from __future__ import annotations

import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import requests

from env_utils import env_bool, env_float, env_int, load_env
from visual_dedupe import image_input_urls


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "qwen/qwen3.6-flash"
GENERIC_GROUP_KEYS = {
    "",
    "unique",
    "none",
    "not_duplicate",
    "not_similar",
    "different",
    "dance",
    "dance_challenge",
    "trend",
    "tiktok_trend",
    "video_template",
}


def clean_text(value: Any, max_len: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 3].rstrip() + "..."
    return text


def normalize_key(value: Any) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


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
    return clean_text(" ".join(part for part in parts if part), max_len=1600)


def review_image_urls(item: dict[str, Any], limit: int = 3) -> list[str]:
    urls: list[str] = []
    for url in image_input_urls(item, limit=8):
        text = clean_text(url)
        lowered = text.lower().split("?", 1)[0]
        if not text.startswith(("http://", "https://")):
            continue
        if lowered.endswith((".mp4", ".m3u8", ".mov", ".webm")):
            continue
        if "tiktok.com/@" in lowered and "/video/" in lowered:
            continue
        if text not in urls:
            urls.append(text)
        if len(urls) >= limit:
            break
    return urls


def similarity_config(rules: dict[str, Any] | None = None) -> dict[str, Any]:
    env = load_env(override=False)
    merged_env = {**env, **os.environ}
    configured = (rules or {}).get("tiktok_ua_batch_similarity_filter")
    configured = configured if isinstance(configured, dict) else {}
    enabled_default = bool(configured.get("enabled", True))
    model = (
        os.environ.get("TIKTOK_UA_BATCH_SIMILARITY_FILTER_MODEL")
        or env.get("TIKTOK_UA_BATCH_SIMILARITY_FILTER_MODEL")
        or configured.get("model")
        or os.environ.get("TIKTOK_UA_VIDEO_REVIEW_MODEL")
        or env.get("TIKTOK_UA_VIDEO_REVIEW_MODEL")
        or os.environ.get("OPENROUTER_MODEL")
        or env.get("OPENROUTER_MODEL")
        or DEFAULT_MODEL
    )
    return {
        "enabled": env_bool("TIKTOK_UA_BATCH_SIMILARITY_FILTER_ENABLED", enabled_default, merged_env),
        "model": clean_text(model) or DEFAULT_MODEL,
        "timeout_seconds": env_int(
            "TIKTOK_UA_BATCH_SIMILARITY_FILTER_TIMEOUT_SECONDS",
            int(configured.get("timeout_seconds", 45) or 45),
            merged_env,
        ),
        "max_concurrency": max(
            1,
            env_int(
                "TIKTOK_UA_BATCH_SIMILARITY_FILTER_MAX_CONCURRENCY",
                int(configured.get("max_concurrency", 3) or 3),
                merged_env,
            ),
        ),
        "fail_open": env_bool("TIKTOK_UA_BATCH_SIMILARITY_FILTER_FAIL_OPEN", bool(configured.get("fail_open", True)), merged_env),
        "min_confidence": max(
            0.0,
            min(
                1.0,
                env_float(
                    "TIKTOK_UA_BATCH_SIMILARITY_FILTER_MIN_CONFIDENCE",
                    float(configured.get("min_confidence", 0.72) or 0.72),
                    merged_env,
                ),
            ),
        ),
    }


def cache_key(item: dict[str, Any], image_urls: list[str], model: str) -> str:
    raw = json.dumps(
        {"url": item_url(item), "images": image_urls[:3], "model": model},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def compact_item(item: dict[str, Any], image_urls: list[str]) -> dict[str, Any]:
    author = item.get("authorMeta") if isinstance(item.get("authorMeta"), dict) else {}
    video_meta = item.get("videoMeta") if isinstance(item.get("videoMeta"), dict) else {}
    return {
        "url": item_url(item),
        "author": clean_text(author.get("nickName") or author.get("uniqueId") or author.get("name") or item.get("author")),
        "text": item_text(item),
        "sourceQuery": clean_text(item.get("sourceQuery") or item.get("searchQuery")),
        "views": item.get("playCount") or item.get("views"),
        "likes": item.get("diggCount") or item.get("likeCount") or item.get("likes"),
        "comments": item.get("commentCount") or item.get("comments"),
        "duration": video_meta.get("duration") or item.get("duration"),
        "imageUrls": image_urls,
    }


def build_messages(item: dict[str, Any], image_urls: list[str]) -> list[dict[str, Any]]:
    system = (
        "You create batch-local similarity fingerprints for TikTok-UA materials. "
        "The fingerprint is not a product-quality review. It is only for grouping items in the same current batch "
        "that are interchangeable near-duplicates: same template mechanism, same action pattern, same camera/framing, "
        "and same material use case. Return strict JSON only."
    )
    user_text = (
        "Analyze this one candidate and return a stable visual/template fingerprint. "
        "Use the attached image evidence and the text. Do not output broad keys such as dance_challenge or tiktok_trend. "
        "The groupKey should be specific enough that two items with the same key are safe to dedupe in the same batch. "
        "Different choreography, different template use case, or different scene/action mechanism must receive different keys. "
        "Return JSON keys: groupKey, visualSubject, sceneType, actionPattern, templateMechanism, cameraFraming, "
        "musicDancePattern, confidence, reason.\n\n"
        "Candidate:\n"
        f"{json.dumps(compact_item(item, image_urls), ensure_ascii=False)}"
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    for url in image_urls[:3]:
        content.append({"type": "image_url", "image_url": {"url": url}})
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]


def parse_json_object(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
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
    return parsed if isinstance(parsed, dict) else {}


def float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_fingerprint(raw: dict[str, Any], *, model: str, image_urls: list[str], min_confidence: float) -> dict[str, Any]:
    confidence = max(0.0, min(1.0, float_value(raw.get("confidence"), 0.0)))
    fields = {
        "visualSubject": normalize_key(raw.get("visualSubject")),
        "sceneType": normalize_key(raw.get("sceneType")),
        "actionPattern": normalize_key(raw.get("actionPattern")),
        "templateMechanism": normalize_key(raw.get("templateMechanism")),
        "cameraFraming": normalize_key(raw.get("cameraFraming")),
        "musicDancePattern": normalize_key(raw.get("musicDancePattern")),
    }
    raw_group_key = normalize_key(raw.get("groupKey") or raw.get("nearDuplicateKey"))
    if confidence < min_confidence or raw_group_key in GENERIC_GROUP_KEYS:
        group_key = ""
    else:
        group_key = "|".join(
            part
            for part in [
                raw_group_key,
                fields["templateMechanism"],
                fields["actionPattern"],
                fields["cameraFraming"],
                fields["sceneType"],
            ]
            if part and part not in GENERIC_GROUP_KEYS
        )
    return {
        "groupKey": group_key,
        **fields,
        "isRepresentative": True,
        "isNearDuplicate": False,
        "keptRepresentativeUrl": "",
        "reason": clean_text(raw.get("reason") or raw.get("rationale"), max_len=260),
        "model": model,
        "confidence": confidence,
        "evidence": {"imageUrlsUsed": image_urls},
        "modelFailed": False,
        "cacheHit": False,
    }


def fail_open_fingerprint(*, item: dict[str, Any], model: str, image_urls: list[str], reason: str, category: str) -> dict[str, Any]:
    key_source = item_url(item) or item.get("id") or clean_text(item_text(item), max_len=120)
    return {
        "groupKey": f"unique_{hashlib.sha1(str(key_source).encode('utf-8', errors='ignore')).hexdigest()[:16]}",
        "visualSubject": "",
        "sceneType": "",
        "actionPattern": "",
        "templateMechanism": "",
        "cameraFraming": "",
        "musicDancePattern": "",
        "isRepresentative": True,
        "isNearDuplicate": False,
        "keptRepresentativeUrl": "",
        "reason": clean_text(reason, max_len=260),
        "model": model,
        "confidence": 0.0,
        "evidence": {"imageUrlsUsed": image_urls},
        "failureCategory": category,
        "modelFailed": True,
        "cacheHit": False,
    }


def fingerprint_with_openrouter(item: dict[str, Any], cfg: dict[str, Any], image_urls: list[str]) -> dict[str, Any]:
    env = load_env(override=False)
    model = str(cfg["model"])
    api_key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY", "")
    if not image_urls:
        return fail_open_fingerprint(item=item, model=model, image_urls=[], reason="missing visual evidence image URL", category="no_evidence")
    if not api_key:
        return fail_open_fingerprint(
            item=item,
            model=model,
            image_urls=image_urls,
            reason="OPENROUTER_API_KEY is missing; batch similarity filter is fail-open",
            category="model_failed",
        )
    response = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": build_messages(item, image_urls),
            "response_format": {"type": "json_object"},
            "max_tokens": 650,
        },
        timeout=int(cfg["timeout_seconds"]),
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"].get("content") or "{}"
    parsed = parse_json_object(content)
    if not parsed:
        raise ValueError("TikTok-UA batch similarity model did not return a JSON object")
    return normalize_fingerprint(parsed, model=model, image_urls=image_urls, min_confidence=float(cfg["min_confidence"]))


def review_item(item: dict[str, Any], cfg: dict[str, Any], cached: dict[str, dict[str, Any]]) -> dict[str, Any]:
    image_urls = review_image_urls(item, limit=3)
    key = cache_key(item, image_urls, str(cfg["model"]))
    if key in cached:
        fingerprint = dict(cached[key])
        fingerprint["cacheHit"] = True
    else:
        try:
            fingerprint = fingerprint_with_openrouter(item, cfg, image_urls)
        except Exception as exc:
            fingerprint = fail_open_fingerprint(
                item=item,
                model=str(cfg["model"]),
                image_urls=image_urls,
                reason=f"model fingerprint failed: {exc}",
                category="model_failed",
            )
        fingerprint["cacheKey"] = key
        fingerprint["cacheHit"] = False
    updated = dict(item)
    updated["tiktokUaBatchSimilarityFilter"] = fingerprint
    return updated


def load_cache(artifact_dir: Path | None) -> dict[str, dict[str, Any]]:
    if artifact_dir is None:
        return {}
    cache: dict[str, dict[str, Any]] = {}
    for name in ["08_ua_batch_similarity_filter.json", "08_ua_batch_similarity_filter_rejected.json"]:
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
            fingerprint = item.get("tiktokUaBatchSimilarityFilter")
            if not isinstance(fingerprint, dict):
                continue
            key = clean_text(fingerprint.get("cacheKey"))
            if key:
                cache[key] = fingerprint
    return cache


def item_score(item: dict[str, Any], score_fn: Callable[[dict[str, Any]], float] | None) -> float:
    if score_fn is not None:
        try:
            return float(score_fn(item))
        except Exception:
            pass
    try:
        return float(item.get("heatValue") or 0)
    except (TypeError, ValueError):
        return 0.0


def apply_groups(
    reviewed: list[dict[str, Any]],
    *,
    score_fn: Callable[[dict[str, Any]], float] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    unique_items: list[dict[str, Any]] = []
    for item in reviewed:
        fingerprint = item.get("tiktokUaBatchSimilarityFilter") if isinstance(item.get("tiktokUaBatchSimilarityFilter"), dict) else {}
        group_key = clean_text(fingerprint.get("groupKey"))
        if not group_key:
            unique_items.append(item)
            continue
        groups.setdefault(group_key, []).append(item)

    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    kept_ids: set[int] = set()
    for group_key, group_items in groups.items():
        representative = max(group_items, key=lambda value: item_score(value, score_fn))
        representative_url = item_url(representative)
        for item in group_items:
            updated = dict(item)
            fingerprint = dict(updated.get("tiktokUaBatchSimilarityFilter") or {})
            if item is representative:
                fingerprint.update(
                    {
                        "groupKey": group_key,
                        "isRepresentative": True,
                        "isNearDuplicate": False,
                        "keptRepresentativeUrl": representative_url,
                        "reason": clean_text(fingerprint.get("reason") or "kept as highest-scoring representative", max_len=260),
                    }
                )
                updated["tiktokUaBatchSimilarityFilter"] = fingerprint
                kept.append(updated)
                kept_ids.add(id(item))
            else:
                fingerprint.update(
                    {
                        "groupKey": group_key,
                        "isRepresentative": False,
                        "isNearDuplicate": True,
                        "keptRepresentativeUrl": representative_url,
                        "reason": "removed as near-duplicate in current TikTok-UA batch",
                    }
                )
                updated["tiktokUaBatchSimilarityFilter"] = fingerprint
                rejected.append(updated)
    for item in reviewed:
        if id(item) in kept_ids:
            continue
        fingerprint = item.get("tiktokUaBatchSimilarityFilter") if isinstance(item.get("tiktokUaBatchSimilarityFilter"), dict) else {}
        if fingerprint.get("isNearDuplicate"):
            continue
        if item not in unique_items:
            continue
        updated = dict(item)
        updated_fingerprint = dict(updated.get("tiktokUaBatchSimilarityFilter") or {})
        updated_fingerprint.setdefault("isRepresentative", True)
        updated_fingerprint.setdefault("isNearDuplicate", False)
        updated_fingerprint.setdefault("keptRepresentativeUrl", item_url(updated))
        updated["tiktokUaBatchSimilarityFilter"] = updated_fingerprint
        kept.append(updated)
    input_order = {item_url(item) or str(index): index for index, item in enumerate(reviewed)}
    kept.sort(key=lambda item: input_order.get(item_url(item), len(input_order)))
    return kept, rejected


def summarize(reviewed: list[dict[str, Any]], kept: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {
        clean_text((item.get("tiktokUaBatchSimilarityFilter") or {}).get("groupKey"))
        for item in reviewed
        if clean_text((item.get("tiktokUaBatchSimilarityFilter") or {}).get("groupKey"))
    }
    return {
        "total": len(reviewed),
        "reviewed": len(reviewed),
        "kept": len(kept),
        "rejected": len(rejected),
        "groupCount": len(groups),
        "nearDuplicateGroupCount": sum(1 for key in groups if sum(1 for item in reviewed if (item.get("tiktokUaBatchSimilarityFilter") or {}).get("groupKey") == key) > 1),
        "modelFailed": sum(1 for item in reviewed if (item.get("tiktokUaBatchSimilarityFilter") or {}).get("modelFailed")),
        "cacheHit": sum(1 for item in reviewed if (item.get("tiktokUaBatchSimilarityFilter") or {}).get("cacheHit")),
    }


def write_artifacts(artifact_dir: Path | None, kept: list[dict[str, Any]], rejected: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    if artifact_dir is None:
        return
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "08_ua_batch_similarity_filter.json").write_text(
        json.dumps({"summary": summary, "items": kept}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (artifact_dir / "08_ua_batch_similarity_filter_rejected.json").write_text(
        json.dumps({"summary": summary, "items": rejected}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def apply_tiktok_ua_batch_similarity_filter(
    items: list[dict[str, Any]],
    rules: dict[str, Any],
    *,
    score_fn: Callable[[dict[str, Any]], float] | None = None,
    artifact_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    cfg = similarity_config(rules)
    if not cfg["enabled"]:
        summary = {"total": len(items), "reviewed": 0, "kept": len(items), "rejected": 0, "disabled": True}
        write_artifacts(artifact_dir, items, [], summary)
        print("  - TikTok-UA batch similarity filter disabled", flush=True)
        return items, [], summary

    cached = load_cache(artifact_dir)
    with ThreadPoolExecutor(max_workers=int(cfg["max_concurrency"])) as executor:
        reviewed = list(executor.map(lambda item: review_item(item, cfg, cached), items))

    kept, rejected = apply_groups(reviewed, score_fn=score_fn)
    summary = summarize(reviewed, kept, rejected)
    summary["model"] = cfg["model"]
    summary["minConfidence"] = cfg["min_confidence"]
    write_artifacts(artifact_dir, kept, rejected, summary)
    print(
        "  - TikTok-UA batch similarity filter kept "
        f"{summary['kept']}/{summary['total']}; rejected={summary['rejected']}, "
        f"groups={summary['groupCount']}, modelFailed={summary['modelFailed']}, cacheHit={summary['cacheHit']}",
        flush=True,
    )
    return kept, rejected, summary
