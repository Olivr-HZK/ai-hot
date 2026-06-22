from __future__ import annotations

import re
from typing import Any

from feedback_rules import video_haystack


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "ua_keywords": [],
    "product_keywords": [],
    "min_keyword_hits": 1,
}


def config(rules: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    configured = rules.get("audience_targeting", {})
    if isinstance(configured, dict):
        for key, value in configured.items():
            if value is not None:
                merged[key] = value
    return merged


def clean_keyword(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def keyword_hits(haystack: str, keywords: list[str]) -> list[str]:
    hits: list[str] = []
    for keyword in keywords:
        cleaned = clean_keyword(keyword)
        if cleaned and cleaned in haystack:
            hits.append(cleaned)
    return hits


def target_for_item(item: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    cfg = config(rules)
    if not cfg.get("enabled", True):
        return {"pushObject": "", "reason": "audience targeting disabled", "uaHits": [], "productHits": []}
    haystack = video_haystack(item, include_summary=True)
    ua_hits = keyword_hits(haystack, list(cfg.get("ua_keywords", [])))
    product_hits = keyword_hits(haystack, list(cfg.get("product_keywords", [])))
    min_hits = int(cfg.get("min_keyword_hits", 1) or 1)
    ua_ok = len(ua_hits) >= min_hits
    product_ok = len(product_hits) >= min_hits
    if ua_ok and not product_ok:
        return {"pushObject": "UA", "reason": "matched UA-only feedback material type", "uaHits": ua_hits[:8], "productHits": []}
    if product_ok and not ua_ok:
        return {"pushObject": "产品", "reason": "matched product-only feedback material type", "uaHits": [], "productHits": product_hits[:8]}
    if ua_ok and product_ok:
        return {
            "pushObject": "",
            "reason": "matched both UA and product targeting keywords; keep existing audience",
            "uaHits": ua_hits[:8],
            "productHits": product_hits[:8],
        }
    return {"pushObject": "", "reason": "no audience-specific material match", "uaHits": [], "productHits": []}


def apply_audience_targeting(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    updated_items: list[dict[str, Any]] = []
    for item in items:
        updated = dict(item)
        existing = str(updated.get("pushObject") or "").strip()
        details = target_for_item(updated, rules)
        updated["audienceTargeting"] = details
        if not existing and details.get("pushObject"):
            updated["pushObject"] = details["pushObject"]
        updated_items.append(updated)
    return updated_items
