from __future__ import annotations

import os
from datetime import date
from typing import Any


VALID_VARIANTS = {"legacy", "product_v2", "auto"}


def parse_target_date(raw: Any = None) -> date:
    value = str(raw if raw is not None else os.environ.get("TARGET_DATE", "")).strip()
    if value:
        return date.fromisoformat(value)
    return date.today()


def normalize_variant(value: Any) -> str:
    variant = str(value or "").strip().lower()
    if not variant:
        return "auto"
    if variant not in VALID_VARIANTS:
        raise ValueError(f"Unsupported PIPELINE_VARIANT: {value}. Supported: legacy, product_v2, auto")
    return variant


def resolve_pipeline_variant(value: Any = None, target_date: date | None = None) -> str:
    variant = normalize_variant(value if value is not None else os.environ.get("PIPELINE_VARIANT", "auto"))
    if variant != "auto":
        return variant
    resolved_date = target_date or parse_target_date()
    return "legacy" if resolved_date.day % 2 == 0 else "product_v2"


def is_product_v2(value: Any = None) -> bool:
    return resolve_pipeline_variant(value) == "product_v2"


def mark_pipeline_variant(items: list[dict[str, Any]], variant: str) -> list[dict[str, Any]]:
    return [dict(item, pipelineVariant=variant) for item in items]
