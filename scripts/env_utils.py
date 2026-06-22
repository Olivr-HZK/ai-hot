from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


BASE_DIR = Path(__file__).resolve().parents[1]
ROOT_ENV_FILE = BASE_DIR / ".env"


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_env(env_file: Path | None = None, override: bool = True) -> dict[str, str]:
    path = env_file or ROOT_ENV_FILE
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_quotes(value)
        if not key:
            continue
        env[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return env


def env_bool(name: str, default: bool = False, env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    raw = str(source.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def env_float(name: str, default: float, env: dict[str, str] | None = None) -> float:
    source = env if env is not None else os.environ
    try:
        return float(source.get(name, default))
    except (TypeError, ValueError):
        return default


def env_int(name: str, default: int, env: dict[str, str] | None = None) -> int:
    source = env if env is not None else os.environ
    try:
        return int(source.get(name, default))
    except (TypeError, ValueError):
        return default


def parse_list(raw: str | Iterable[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        values = re.split(r"[\n,;]+", raw)
    else:
        values = [str(item) for item in raw]
    return [item.strip().strip("'\"") for item in values if item and item.strip()]


def parse_bitable_url(url: str) -> dict[str, str]:
    if not url:
        return {}
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    result: dict[str, str] = {}
    if len(parts) >= 2 and parts[-2] == "base":
        result["app_token"] = parts[-1]
    query = parse_qs(parsed.query)
    if query.get("table"):
        result["table_id"] = query["table"][0]
    return result


def remove_bitable_view_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.pop("view", None)
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def resolve_bitable_config() -> dict[str, str]:
    env = load_env()
    raw_url = env.get("FEISHU_BITABLE_URL", "")
    parsed = parse_bitable_url(raw_url)
    return {
        "app_token": env.get("BITABLE_APP_TOKEN") or parsed.get("app_token", ""),
        "table_id": env.get("BITABLE_TABLE_ID") or parsed.get("table_id", ""),
        "url": remove_bitable_view_from_url(raw_url),
    }
