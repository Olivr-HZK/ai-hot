from __future__ import annotations

import re
from typing import Any

from ins_scoring import clean_text, ranking_score


AD_FANTASY_TERMS = ["dream portrait", "storybook portrait", "princess portrait", "fairy portrait", "dress up"]
AD_STRUCTURE_TERMS = [
    "prompt",
    "workflow",
    "template",
    "photo to video",
    "image to video",
    "before after",
    "before/after",
    "single photo upload",
    "upload an image",
    "portrait to live moment",
    "stream dream",
    "streamer transformation",
    "creator persona",
    "image/video template",
    "template library",
    "create now",
    "cta",
    "end card",
    "mobile ad",
    "app store",
    "google play",
    "generated",
    "generator",
    "transformation",
]


def haystack(item: dict[str, Any]) -> str:
    parts = [
        item.get("title"),
        item.get("text"),
        item.get("desc"),
        item.get("summary"),
        item.get("hotspotIntro"),
        " ".join(str(tag) for tag in item.get("hashtags") or []),
        clean_text((item.get("authorMeta") or {}).get("nickName") if isinstance(item.get("authorMeta"), dict) else ""),
    ]
    return re.sub(r"\s+", " ", " ".join(str(part or "") for part in parts)).lower()


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword and keyword.lower() in text]


def product_fit_details(item: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    cfg = rules.get("product_fit", {})
    text = haystack(item)
    min_score = int(cfg.get("min_score", 2) or 2)
    product_scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    products = ["evoke", "toki", "kavi", "avatar_jigsaw"]
    for product in products:
        product_cfg = cfg.get(product, {}) if isinstance(cfg.get(product), dict) else {}
        ua_hits = keyword_hits(text, list(product_cfg.get("ua_keywords", [])))
        product_hits = keyword_hits(text, list(product_cfg.get("product_keywords", [])))
        score = len(ua_hits) + len(product_hits) * 2
        product_scores[product] = float(score)
        reasons[product] = [*product_hits[:5], *ua_hits[:5]]
    exclude_hits = keyword_hits(text, list(cfg.get("exclude_for_product_keywords", [])))
    fantasy_hits = keyword_hits(text, AD_FANTASY_TERMS)
    ad_structure_hits = keyword_hits(text, AD_STRUCTURE_TERMS)
    if exclude_hits:
        for product in ["evoke", "toki", "kavi", "avatar_jigsaw"]:
            product_scores[product] = 0.0
    if fantasy_hits and not ad_structure_hits:
        for product in ["evoke", "toki", "kavi", "avatar_jigsaw"]:
            product_scores[product] = 0.0
        exclude_hits = [*exclude_hits, "fantasy/dress-up lacks product evidence"]
    primary = max(product_scores, key=lambda key: product_scores[key]) if product_scores else ""
    if product_scores.get(primary, 0.0) < min_score:
        primary = ""
    is_ua = any(product_scores.get(product, 0.0) >= min_score for product in products)
    is_product = bool(
        not exclude_hits
        and max(
            product_scores.get("evoke", 0.0),
            product_scores.get("toki", 0.0),
            product_scores.get("kavi", 0.0),
            product_scores.get("avatar_jigsaw", 0.0),
        )
        >= min_score
    )
    return {
        "primaryProduct": primary,
        "productScores": product_scores,
        "reasons": reasons,
        "excludeHits": exclude_hits[:8],
        "isUaCandidate": is_ua,
        "isProductCandidate": is_product,
        "isRelevant": is_ua or is_product,
    }


def decide_push_object(item: dict[str, Any], fit: dict[str, Any]) -> str:
    existing = clean_text(item.get("pushObject"))
    if existing in {"UA", "产品", "ALL"}:
        return existing
    if fit.get("isProductCandidate") and fit.get("isUaCandidate"):
        return "ALL"
    if fit.get("isProductCandidate"):
        return "产品"
    if fit.get("isUaCandidate"):
        return "UA"
    return ""


def is_product_side(item: dict[str, Any]) -> bool:
    return clean_text(item.get("pushObject")) in {"产品", "ALL"}


def is_toki_product(item: dict[str, Any]) -> bool:
    fit = item.get("insProductFit") if isinstance(item.get("insProductFit"), dict) else {}
    scores = fit.get("productScores") if isinstance(fit.get("productScores"), dict) else {}
    return bool(fit.get("isProductCandidate")) and float(scores.get("toki", 0) or 0) >= float(scores.get("evoke", 0) or 0)


def apply_toki_product_quota(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = rules.get("product_fit", {})
    min_share = float(cfg.get("toki_product_min_share", 0.7) or 0.7)
    product_items = [item for item in items if is_product_side(item)]
    if not product_items:
        return items
    toki_items = [item for item in product_items if is_toki_product(item)]
    target_toki_count = int(len(product_items) * min_share + 0.999)
    if len(toki_items) >= target_toki_count:
        return items
    demotable = [
        item
        for item in product_items
        if not is_toki_product(item) and clean_text(item.get("pushObject")) == "产品"
    ]
    demote_count = min(len(demotable), max(0, target_toki_count - len(toki_items)))
    demote_keys = {
        clean_text(item.get("hotspotUrl") or item.get("upsertKey") or item.get("id"))
        for item in sorted(demotable, key=lambda item: ranking_score(item, rules))[:demote_count]
    }
    result: list[dict[str, Any]] = []
    for item in items:
        key = clean_text(item.get("hotspotUrl") or item.get("upsertKey") or item.get("id"))
        if key in demote_keys:
            updated = dict(item)
            updated["pushObject"] = "UA"
            fit = dict(updated.get("insProductFit") or {})
            fit["quotaNote"] = "demoted from product to UA because INS Toki product share was below target"
            updated["insProductFit"] = fit
            updated["productFit"] = fit
            result.append(updated)
        else:
            result.append(item)
    return result


def apply_product_fit(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    if not rules.get("product_fit", {}).get("enabled", True):
        return items
    updated_items: list[dict[str, Any]] = []
    for item in items:
        updated = dict(item)
        fit = product_fit_details(updated, rules)
        updated["insProductFit"] = fit
        updated["productFit"] = fit
        push_object = decide_push_object(updated, fit)
        if push_object:
            updated["pushObject"] = push_object
        updated_items.append(updated)
    return apply_toki_product_quota(updated_items, rules)
