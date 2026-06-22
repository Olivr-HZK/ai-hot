from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CHECKPOINT_DIR = BASE_DIR / "skill_runs" / "scrape_checkpoints"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def env_bool(name: str, default: bool = False, env: dict[str, str] | None = None) -> bool:
    values = env or os.environ
    raw = str(values.get(name, "")).strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def resolve_checkpoint_root(env: dict[str, str] | None = None) -> Path:
    values = env or os.environ
    raw = str(values.get("SCRAPE_CHECKPOINT_DIR", "")).strip()
    if not raw:
        return DEFAULT_CHECKPOINT_DIR
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


def platform_checkpoint_dir(platform: str, env: dict[str, str] | None = None) -> Path:
    return resolve_checkpoint_root(env) / platform


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def write_checkpoint(
    platform: str,
    raw_data: list[dict[str, Any]],
    *,
    status: str,
    run_id: str | None = None,
    completed: list[str] | None = None,
    failed: list[dict[str, Any]] | None = None,
    error: str = "",
    extra: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    run_id = run_id or os.environ.get("PIPELINE_RUN_ID") or datetime.now().strftime("%Y%m%d_%H%M%S")
    checkpoint_dir = platform_checkpoint_dir(platform, env)
    raw_path = checkpoint_dir / "latest_raw.json"
    archive_path = checkpoint_dir / "runs" / f"{run_id}_raw.json"
    status_path = checkpoint_dir / "latest_status.json"
    atomic_write_json(raw_path, raw_data)
    atomic_write_json(archive_path, raw_data)
    payload: dict[str, Any] = {
        "platform": platform,
        "runId": run_id,
        "status": status,
        "updatedAt": now_iso(),
        "itemCount": len(raw_data),
        "checkpointPath": raw_path.as_posix(),
        "archivePath": archive_path.as_posix(),
        "completed": completed or [],
        "failed": failed or [],
        "error": error,
    }
    if extra:
        payload.update(extra)
    atomic_write_json(status_path, payload)
    return payload


def read_latest_status(platform: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    path = platform_checkpoint_dir(platform, env) / "latest_status.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def partial_continue_enabled(env: dict[str, str] | None = None) -> bool:
    return env_bool("SCRAPE_PARTIAL_CONTINUE", True, env)
