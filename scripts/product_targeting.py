from __future__ import annotations

import re
from typing import Any

from feedback_rules import ranking_score, video_haystack


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "toki_product_min_share": 0.7,
    "min_score": 2,
    "evoke": {
        "ua_keywords": [
            "old photo",
            "restore photo",
            "photo enhancer",
            "enhance photo",
            "blurry photo",
            "colorize",
            "scratch",
            "damaged photo",
            "before after",
            "ai portrait",
            "dream portrait",
            "storybook portrait",
            "portrait to live moment",
            "single photo upload",
            "upload an image",
            "\u8001\u7167\u7247",
            "\u4fee\u590d",
            "\u4e0a\u8272",
            "\u6a21\u7cca",
            "\u5199\u771f",
        ],
        "product_keywords": [
            "old photo",
            "restore photo",
            "photo restoration",
            "photo enhancer",
            "enhance photo",
            "colorize",
            "scratch",
            "wrinkle",
            "damaged photo",
            "ai portrait",
            "portrait generator",
            "dream portrait",
            "storybook portrait",
            "portrait to live moment",
            "before after portrait",
            "photo style template",
            "ai photo editing",
            "ai creative editing",
            "ai editing photo effect",
            "ai photo effect",
            "ai photo filter",
            "hypic",
            "gemini ai photo edit",
            "sports poster",
            "jersey portrait",
            "athlete portrait",
            "movie poster",
            "tv show poster",
            "film look portrait",
            "character card",
            "cinematic portrait",
            "\u8001\u7167\u7247",
            "\u4fee\u590d",
            "\u4e0a\u8272",
            "\u5212\u75d5",
            "\u7834\u635f",
            "\u5199\u771f",
        ],
    },
    "toki": {
        "ua_keywords": [
            "photo to video",
            "image to video",
            "ai video",
            "ai action figure",
            "figurine",
            "labubu",
            "ai emote",
            "face animation",
            "ai transform",
            "ai magic",
            "ai dance",
            "ai hug",
            "ai couple",
            "portrait to live moment",
            "stream dream",
            "streamer transformation",
            "creator persona",
            "single photo upload",
            "upload an image",
            "dream portrait",
            "storybook portrait",
            "princess portrait",
            "fairy portrait",
            "dress up template",
            "image/video template",
            "template library",
            "create now",
            "ai template link",
            "ai creative editing",
            "ai photo editing",
            "ai editing photo effect",
            "hypic",
            "gemini ai photo edit",
            "one click",
            "pet singing",
            "pet talking",
            "\u56fe\u751f\u89c6\u9891",
            "\u7167\u7247\u8f6c\u89c6\u9891",
            "\u624b\u529e",
            "\u516c\u4ed4",
            "\u62e5\u62b1",
            "\u821e\u8e48",
        ],
        "product_keywords": [
            "photo to video",
            "image to video",
            "ai video generator",
            "ai action figure",
            "action figure",
            "figurine",
            "ai figurine",
            "labubu",
            "ai emote",
            "face animation",
            "ai transform",
            "ai magic",
            "ai dance",
            "ai hug",
            "ai kiss",
            "ai couple",
            "portrait to live moment",
            "stream dream",
            "streamer transformation",
            "creator persona",
            "single photo upload",
            "upload an image",
            "dress up template",
            "image/video template",
            "template library",
            "create now",
            "ai template link",
            "ai creative editing",
            "ai photo editing",
            "ai editing photo effect",
            "hypic",
            "gemini ai photo edit",
            "one click",
            "pet singing",
            "pet talking",
            "pet animation",
            "animate photo",
            "talking photo",
            "sports highlight",
            "athlete celebration",
            "match entrance",
            "training transformation",
            "cinematic sports",
            "action freeze",
            "character transformation",
            "movie poster transition",
            "movie transition",
            "cinematic trailer",
            "trailer edit",
            "scene transformation",
            "\u56fe\u751f\u89c6\u9891",
            "\u7167\u7247\u8f6c\u89c6\u9891",
            "\u624b\u529e",
            "\u516c\u4ed4",
            "\u52a8\u6001\u8868\u60c5",
            "\u53d8\u8eab",
            "\u62e5\u62b1",
            "\u821e\u8e48",
        ],
    },
    "kavi": {
        "ua_keywords": [
            "kavi",
            "ai video generator",
            "ai video maker",
            "photo to video",
            "image to video",
            "selfie video",
            "single selfie",
            "single photo upload",
            "upload an image",
            "portrait to live moment",
            "stream dream",
            "streamer transformation",
            "creator persona",
            "lifelike motion",
            "stylized animation",
            "dream portrait",
            "storybook portrait",
            "princess portrait",
            "fairy portrait",
            "dress up template",
            "image/video template",
            "template library",
            "create now",
            "3d figure",
            "custom 3d figure",
            "viral video",
            "trending ai effect",
            "ai effects",
            "animate selfie",
            "ai template link",
            "ai creative editing",
            "ai photo editing",
            "ai editing photo effect",
            "hypic",
            "gemini ai photo edit",
            "one click",
            "\u56fe\u751f\u89c6\u9891",
            "\u7167\u7247\u8f6c\u89c6\u9891",
            "\u81ea\u62cd",
            "\u98ce\u683c\u5316\u52a8\u753b",
            "\u0033\u0064\u624b\u529e",
            "\u7206\u6b3e\u89c6\u9891",
        ],
        "product_keywords": [
            "kavi",
            "ai video generator",
            "ai video maker",
            "photo to video",
            "image to video",
            "selfie video",
            "single selfie",
            "single photo upload",
            "upload an image",
            "portrait to live moment",
            "stream dream",
            "streamer transformation",
            "creator persona",
            "lifelike motion",
            "stylized animation",
            "dress up template",
            "image/video template",
            "template library",
            "create now",
            "3d figure",
            "custom 3d figure",
            "trending styles",
            "video creator",
            "ai effects",
            "animate selfie",
            "ai template link",
            "ai creative editing",
            "ai photo editing",
            "ai editing photo effect",
            "hypic",
            "gemini ai photo edit",
            "one click",
            "sports highlight",
            "athlete celebration",
            "match entrance",
            "training transformation",
            "cinematic sports",
            "character transformation",
            "movie poster transition",
            "movie transition",
            "cinematic trailer",
            "trailer edit",
            "creator persona",
            "scene transformation",
            "\u56fe\u751f\u89c6\u9891",
            "\u7167\u7247\u8f6c\u89c6\u9891",
            "\u81ea\u62cd",
            "\u98ce\u683c\u5316\u52a8\u753b",
            "\u0033\u0064\u624b\u529e",
            "\u89c6\u9891\u751f\u6210",
        ],
    },
    "avatar_jigsaw": {
        "ua_keywords": [
            "ai avatar jigsaw",
            "avatar jigsaw",
            "ai avatar puzzle",
            "ai avatars puzzle",
            "facebook instant game",
            "facebook gaming",
            "profile photo",
            "avatar puzzle",
            "jigsaw puzzle",
            "clay avatar",
            "claymation avatar",
            "face retouching game",
            "ai photos",
            "share and get",
            "free ai photos",
            "\u5934\u50cf\u62fc\u56fe",
            "\u5934\u50cf\u5c0f\u6e38\u620f",
            "\u62fc\u56fe\u5c0f\u6e38\u620f",
            "\u8138\u90e8\u6ee4\u955c",
            "\u7c98\u571f\u98ce\u5934\u50cf",
        ],
        "product_keywords": [
            "ai avatar jigsaw",
            "avatar jigsaw",
            "ai avatar puzzle",
            "ai avatars puzzle",
            "facebook instant game",
            "facebook gaming",
            "profile photo",
            "avatar puzzle",
            "jigsaw puzzle",
            "clay avatar",
            "claymation avatar",
            "face retouching game",
            "ai photos",
            "puzzle pieces",
            "4 pieces",
            "16 pieces",
            "36 pieces",
            "fan avatar",
            "player avatar",
            "character avatar",
            "avatar challenge",
            "profile card",
            "sports avatar",
            "\u5934\u50cf\u62fc\u56fe",
            "\u5934\u50cf\u5c0f\u6e38\u620f",
            "\u62fc\u56fe\u5c0f\u6e38\u620f",
            "\u8138\u90e8\u6ee4\u955c",
            "\u7c98\u571f\u98ce\u5934\u50cf",
        ],
    },
    "exclude_for_product_keywords": [
        "ai news",
        "model release",
        "funding",
        "stock",
        "crypto",
        "web3",
        "hardware",
        "regulator",
        "politics",
        "war",
        "leak",
        "leaked",
        "spoiler",
        "paparazzi",
        "gossip",
        "box office",
        "dating rumor",
        "celebrity news",
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
    ],
}

FOCUS_PRODUCTS = ["evoke", "toki", "kavi", "avatar_jigsaw"]
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
    "sports highlight",
    "athlete celebration",
    "sports poster",
    "jersey portrait",
    "training transformation",
    "match entrance",
    "movie poster",
    "tv show poster",
    "character transformation",
    "trailer edit",
    "cinematic transition",
]

LOW_QUALITY_PRODUCT_GROUPS = [
    ["makeup", "one click"],
    ["makeup", "capcut"],
    ["beauty", "filter"],
    ["\u7f8e\u5986", "\u4e00\u952e"],
    ["\u7f8e\u5986", "capcut"],
    ["\u7d20\u989c", "\u5986"],
    ["baseball", "girl"],
    ["baseball", "broadcast"],
    ["sports", "spectator"],
    ["sports", "broadcast girl"],
    ["mtb", "cinematic"],
    ["mountain bike", "cinematic"],
    ["mountain bike", "edit"],
    ["commencal", "mtb"],
    ["cleanest", "commencal"],
    ["luxury fashion commercial", "storyboard"],
    ["high-end luxury fashion commercial", "prompt"],
    ["9-panel cinematic storyboard"],
    ["commercial video", "storyboard"],
    ["\u68d2\u7403", "\u5973\u5b69"],
    ["\u68d2\u7403", "\u89c2\u4f17"],
    ["\u68d2\u7403", "\u8d5b\u4e8b"],
    ["portrait prompt", "face lock"],
    ["\u4eba\u50cf", "\u63d0\u793a\u8bcd", "\u9762\u90e8\u7279\u5f81"],
]

GENERIC_PORTRAIT_PROMPT_TERMS = [
    "ai portrait prompt",
    "portrait prompt",
    "photorealistic portrait prompt",
    "high-fidelity ai portrait",
    "\u9ad8\u4fdd\u771fai\u4eba\u50cf",
    "\u4eba\u50cf\u63d0\u793a\u8bcd",
    "\u5199\u771f\u63d0\u793a\u8bcd",
    "\u9762\u90e8\u7279\u5f81\u9501\u5b9a",
]

PORTRAIT_PROMPT_REQUIRED_EVIDENCE = [
    "before after",
    "before/after",
    "upload",
    "template",
    "photo to video",
    "image to video",
    "old photo",
    "restore",
    "restoration",
    "enhance",
    "enhancer",
    "avatar",
    "jigsaw",
    "cta",
    "create now",
    "\u4e0a\u4f20",
    "\u6a21\u677f",
    "\u7167\u7247\u8f6c\u89c6\u9891",
    "\u56fe\u751f\u89c6\u9891",
    "\u4fee\u590d",
    "\u589e\u5f3a",
]

SPORTS_EDIT_TERMS = [
    "mtb",
    "mountain bike",
    "commencal",
    "cycling edit",
    "bike edit",
    "sports edit",
    "cinematic sports",
    "sports highlight",
]

SPORTS_REQUIRED_PRODUCT_EVIDENCE = [
    "ai",
    "prompt",
    "template",
    "upload",
    "before after",
    "before/after",
    "photo to video",
    "image to video",
    "generated",
    "generator",
    "poster",
    "jersey portrait",
    "card styling",
    "transformation",
    "create now",
]


def config(rules: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    configured = rules.get("product_targeting", {})
    if isinstance(configured, dict):
        for key, value in configured.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                product_cfg = dict(merged[key])
                for product_key, product_value in value.items():
                    if (
                        product_key in {"ua_keywords", "product_keywords"}
                        and isinstance(product_value, list)
                        and isinstance(product_cfg.get(product_key), list)
                    ):
                        product_cfg[product_key] = list(dict.fromkeys([*product_cfg[product_key], *product_value]))
                    else:
                        product_cfg[product_key] = product_value
                merged[key] = product_cfg
            elif value is not None:
                merged[key] = value
    return merged


def clean_keyword(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def keyword_hits(haystack: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in (clean_keyword(item) for item in keywords) if keyword and keyword in haystack]


def keyword_group_hits(haystack: str, groups: list[list[str]]) -> list[str]:
    hits: list[str] = []
    for group in groups:
        terms = [clean_keyword(term) for term in group if clean_keyword(term)]
        if terms and all(term in haystack for term in terms):
            hits.append(" + ".join(terms))
    return hits


def is_generic_portrait_prompt_without_product_evidence(haystack: str) -> bool:
    has_prompt = ("prompt" in haystack and "portrait" in haystack) or keyword_hits(haystack, GENERIC_PORTRAIT_PROMPT_TERMS)
    if not has_prompt:
        return False
    has_evidence = bool(keyword_hits(haystack, PORTRAIT_PROMPT_REQUIRED_EVIDENCE))
    return not has_evidence


def is_traditional_sports_edit_without_product_evidence(haystack: str) -> bool:
    if not keyword_hits(haystack, SPORTS_EDIT_TERMS):
        return False
    if not any(marker in haystack for marker in ["edit", "cinematic", "highlight", "mtb", "bike"]):
        return False
    return not bool(keyword_hits(haystack, SPORTS_REQUIRED_PRODUCT_EVIDENCE))


def product_fit_details(item: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    cfg = config(rules)
    haystack = video_haystack(item, include_summary=True)
    min_score = int(cfg.get("min_score", 2) or 2)
    product_scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    for product in FOCUS_PRODUCTS:
        product_cfg = cfg.get(product, {}) if isinstance(cfg.get(product), dict) else {}
        ua_hits = keyword_hits(haystack, list(product_cfg.get("ua_keywords", [])))
        product_hits = keyword_hits(haystack, list(product_cfg.get("product_keywords", [])))
        score = len(ua_hits) + len(product_hits) * 2
        product_scores[product] = float(score)
        reasons[product] = [*product_hits[:5], *ua_hits[:5]]
    exclude_hits = keyword_hits(haystack, list(cfg.get("exclude_for_product_keywords", [])))
    low_quality_hits = keyword_group_hits(haystack, LOW_QUALITY_PRODUCT_GROUPS)
    if low_quality_hits:
        exclude_hits = [*exclude_hits, *low_quality_hits]
    if is_generic_portrait_prompt_without_product_evidence(haystack):
        exclude_hits = [*exclude_hits, "generic portrait prompt lacks product evidence"]
    if is_traditional_sports_edit_without_product_evidence(haystack):
        exclude_hits = [*exclude_hits, "traditional sports edit lacks AI/template/product evidence"]
    fantasy_hits = keyword_hits(haystack, AD_FANTASY_TERMS)
    ad_structure_hits = keyword_hits(haystack, AD_STRUCTURE_TERMS)
    if exclude_hits:
        for product in FOCUS_PRODUCTS:
            product_scores[product] = 0.0
    if fantasy_hits and not ad_structure_hits:
        for product in FOCUS_PRODUCTS:
            product_scores[product] = 0.0
        exclude_hits = [*exclude_hits, "fantasy/dress-up lacks product evidence"]
    primary = max(product_scores, key=lambda key: product_scores[key]) if product_scores else ""
    primary_score = product_scores.get(primary, 0.0)
    is_ua = any(product_scores.get(product, 0.0) >= min_score for product in FOCUS_PRODUCTS)
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
    if primary_score < min_score:
        primary = ""
    return {
        "primaryProduct": primary,
        "productScores": product_scores,
        "reasons": reasons,
        "excludeHits": exclude_hits[:8],
        "isProductCandidate": is_product,
        "isUaCandidate": is_ua,
    }


def is_forced_ua_geo_candidate(item: dict[str, Any]) -> bool:
    details = item.get("uaGeoTargeting")
    return isinstance(details, dict) and bool(details.get("isTarget"))


def is_forced_ua_material_candidate(item: dict[str, Any]) -> bool:
    details = item.get("uaMaterialTargeting")
    return isinstance(details, dict) and bool(details.get("isTarget"))


def decide_push_object(item: dict[str, Any], fit: dict[str, Any]) -> str:
    existing = str(item.get("pushObject") or "").strip()
    product_candidate = bool(fit.get("isProductCandidate"))
    ua_candidate = bool(fit.get("isUaCandidate"))
    if existing == "UA" and is_forced_ua_geo_candidate(item):
        return "ALL" if product_candidate else "UA"
    if existing == "UA" and is_forced_ua_material_candidate(item):
        return "ALL" if product_candidate else "UA"
    if existing == "UA" and product_candidate:
        return "ALL"
    if existing in {"UA", "\u4ea7\u54c1", "ALL"}:
        return existing
    if product_candidate and ua_candidate:
        return "ALL"
    if product_candidate:
        return "\u4ea7\u54c1"
    return existing


def apply_product_targeting(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    if not config(rules).get("enabled", True):
        return items
    updated_items: list[dict[str, Any]] = []
    for item in items:
        updated = dict(item)
        fit = product_fit_details(updated, rules)
        updated["productFit"] = fit
        push_object = decide_push_object(updated, fit)
        if push_object:
            updated["pushObject"] = push_object
        updated_items.append(updated)
    return apply_toki_product_quota(updated_items, rules)


def is_product_side(item: dict[str, Any]) -> bool:
    return str(item.get("pushObject") or "").strip() in {"\u4ea7\u54c1", "ALL"}


def is_toki_product(item: dict[str, Any]) -> bool:
    fit = item.get("productFit") if isinstance(item.get("productFit"), dict) else {}
    scores = fit.get("productScores") if isinstance(fit.get("productScores"), dict) else {}
    return bool(fit.get("isProductCandidate")) and float(scores.get("toki", 0) or 0) >= float(scores.get("evoke", 0) or 0)


def apply_toki_product_quota(items: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = config(rules)
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
        if not is_toki_product(item) and str(item.get("pushObject") or "").strip() == "\u4ea7\u54c1"
    ]
    demote_count = min(len(demotable), max(0, target_toki_count - len(toki_items)))
    demote_keys = {
        str(item.get("hotspotUrl") or item.get("upsertKey") or item.get("id") or "")
        for item in sorted(demotable, key=lambda item: float(item.get("heatValue") or ranking_score(item, rules)))[:demote_count]
    }
    result: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get("hotspotUrl") or item.get("upsertKey") or item.get("id") or "")
        if key in demote_keys:
            updated = dict(item)
            updated["pushObject"] = "UA"
            fit = dict(updated.get("productFit") or {})
            fit["quotaNote"] = "demoted from product to UA because Toki product share was below target"
            updated["productFit"] = fit
            result.append(updated)
        else:
            result.append(item)
    if demote_count:
        print(
            f"  - Product targeting warning: Toki product candidates {len(toki_items)}/{len(product_items)} below target {min_share:.0%}; demoted {demote_count} non-Toki product items",
            flush=True,
        )
    else:
        print(
            f"  - Product targeting warning: Toki product candidates {len(toki_items)}/{len(product_items)} below target {min_share:.0%}; no demotable non-Toki product items",
            flush=True,
        )
    return result
