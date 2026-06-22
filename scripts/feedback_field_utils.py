from __future__ import annotations

from typing import Any


UA_ACCEPTANCE_FIELDS = [
    "\u0055\u0041\u91c7\u7eb3\u610f\u613f",
    "\u6d69\u9e4f\u610f\u613f",
]
UA_REASON_FIELDS = [
    "\u0055\u0041\u539f\u56e0",
    "\u6d69\u9e4f\u539f\u56e0",
]
PRODUCT_ACCEPTANCE_FIELD = "\u4ea7\u54c1\u91c7\u7eb3\u610f\u613f"
PRODUCT_REASON_FIELD = "\u4ea7\u54c1\u539f\u56e0"
MATERIAL_ACCEPTANCE_FIELD = "\u91c7\u7eb3\u610f\u613f"
MATERIAL_REASON_FIELD = "\u539f\u56e0"
IGNORED_FEISHU_FIELDS = {
    "\u7d20\u6750\u7c7b\u578b",
    "\u0070\u0072\u006f\u006d\u0070\u0074\u53cd\u63a8\u7ed3\u679c",
}
READONLY_FEISHU_FIELDS = {
    MATERIAL_ACCEPTANCE_FIELD,
    MATERIAL_REASON_FIELD,
    *UA_ACCEPTANCE_FIELDS,
    *UA_REASON_FIELDS,
    PRODUCT_ACCEPTANCE_FIELD,
    PRODUCT_REASON_FIELD,
    *IGNORED_FEISHU_FIELDS,
}


def field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return str(value.get("link") or value.get("text") or value.get("name") or "").strip()
    if isinstance(value, list):
        return " ".join(field_text(item) for item in value if item is not None).strip()
    return str(value).strip()


def field_url(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        return text if text.startswith(("http://", "https://")) else ""
    if isinstance(value, dict):
        for key in ("link", "url", "href", "value"):
            found = field_url(value.get(key))
            if found:
                return found
        for child in value.values():
            found = field_url(child)
            if found:
                return found
        return ""
    if isinstance(value, list):
        for item in value:
            found = field_url(item)
            if found:
                return found
    return ""


def normalize_acceptance(value: Any) -> str:
    rating = rating_value(value)
    if rating == 1:
        return "\u5426\u51b3"
    if rating == 2:
        return "\u4e2d"
    if rating == 3:
        return "\u9ad8"
    text = field_text(value)
    if text == "\u65e0":
        return "\u5426\u51b3"
    lowered = text.lower()
    if any(marker in lowered for marker in ["reject", "veto", "deny"]):
        return "\u5426\u51b3"
    if "1\u661f" in text or text in {"1", "1.0"} or "\u2605" in text and text.count("\u2605") == 1:
        return "\u5426\u51b3"
    if "2\u661f" in text or text in {"2", "2.0"} or "\u2605" in text and text.count("\u2605") == 2:
        return "\u4e2d"
    if "3\u661f" in text or text in {"3", "3.0"} or "\u2605" in text and text.count("\u2605") >= 3:
        return "\u9ad8"
    for item in ["\u5426\u51b3", "\u9ad8", "\u4e2d", "\u4f4e"]:
        if item in text:
            return "\u5426\u51b3" if item == "\u4f4e" else item
    return ""


def rating_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number in {1, 2, 3} else None
    if isinstance(value, str):
        text = value.strip()
        if text in {"1", "1.0"} or "1\u661f" in text:
            return 1
        if text in {"2", "2.0"} or "2\u661f" in text:
            return 2
        if text in {"3", "3.0"} or "3\u661f" in text:
            return 3
        star_count = text.count("\u2605")
        if star_count in {1, 2}:
            return star_count
        if star_count >= 3:
            return 3
        return None
    if isinstance(value, dict):
        for key in ("rating", "score", "value", "number", "text", "name"):
            found = rating_value(value.get(key))
            if found:
                return found
        return None
    if isinstance(value, list):
        for item in value:
            found = rating_value(item)
            if found:
                return found
    return None


def acceptance_score_values(values: list[str]) -> list[str]:
    normalized = [normalize_acceptance(value) for value in values]
    normalized = [value for value in normalized if value]
    if "\u9ad8" in normalized:
        return ["\u9ad8"]
    if any(value in {"\u4f4e", "\u5426\u51b3"} for value in normalized) and "\u4e2d" in normalized:
        return ["\u4e2d", "\u5426\u51b3"]
    if any(value in {"\u4f4e", "\u5426\u51b3"} for value in normalized):
        return ["\u5426\u51b3"]
    if "\u4e2d" in normalized:
        return ["\u4e2d"]
    return normalized


def display_acceptance(values: list[str]) -> str:
    scored = acceptance_score_values(values)
    if not scored:
        return ""
    if scored == ["\u4e2d", "\u5426\u51b3"]:
        return "\u4e2d + \u5426\u51b3"
    return scored[0]


def combined_ua_feedback(fields: dict[str, Any]) -> dict[str, Any]:
    feedback = material_feedback(fields)
    return {
        "ua_acceptance": feedback["material_acceptance"],
        "ua_acceptance_values": feedback["material_acceptance_values"],
        "ua_reason": feedback["material_reason"],
        "ua_feedback_sources": feedback["material_feedback_sources"],
        "ua_blocked": feedback["material_blocked"],
    }


def material_feedback(fields: dict[str, Any]) -> dict[str, Any]:
    raw_material_acceptance = fields.get(MATERIAL_ACCEPTANCE_FIELD)
    material_acceptance = normalize_acceptance(raw_material_acceptance)
    raw_product_acceptance = fields.get(PRODUCT_ACCEPTANCE_FIELD)
    product_legacy_acceptance = normalize_acceptance(raw_product_acceptance)
    acceptance = material_acceptance or product_legacy_acceptance
    values = [acceptance] if acceptance else []
    material_reason = field_text(fields.get(MATERIAL_REASON_FIELD))
    product_legacy_reason = field_text(fields.get(PRODUCT_REASON_FIELD))
    reason = material_reason or product_legacy_reason
    sources: list[dict[str, str]] = []
    if material_acceptance or material_reason:
        sources.append(
            {
                "source": "material",
                "acceptance": material_acceptance,
                "rawAcceptance": field_text(raw_material_acceptance),
                "reason": material_reason,
            }
        )
    if (not material_acceptance and product_legacy_acceptance) or (not material_reason and product_legacy_reason):
        sources.append(
            {
                "source": "product_legacy",
                "acceptance": product_legacy_acceptance,
                "rawAcceptance": field_text(raw_product_acceptance),
                "reason": product_legacy_reason,
            }
        )
    scored_values = acceptance_score_values(values)
    blocked = any(value in {"\u4f4e", "\u5426\u51b3"} for value in scored_values)
    return {
        "material_acceptance": display_acceptance(values),
        "material_acceptance_values": scored_values,
        "material_reason": reason,
        "material_feedback_sources": sources,
        "material_blocked": blocked,
        # Compatibility keys for modules that still expect side-specific feedback.
        "ua_acceptance": display_acceptance(values),
        "ua_acceptance_values": scored_values,
        "ua_reason": reason,
        "ua_feedback_sources": sources,
        "ua_blocked": blocked,
        "product_acceptance": display_acceptance(values),
        "product_reason": reason,
    }
