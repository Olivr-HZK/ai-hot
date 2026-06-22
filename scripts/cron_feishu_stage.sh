#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export PYTHONIOENCODING="utf-8"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    PYTHON_BIN="$(command -v python)"
  fi
fi

LOG_DIR="$REPO_ROOT/skill_runs/logs"
mkdir -p "$LOG_DIR"
STAMP="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="$LOG_DIR/cron_feishu_stage_$STAMP.log"
WAIT_SECONDS="${FEISHU_STAGE_WAIT_SECONDS:-1800}"
POLL_SECONDS="${FEISHU_STAGE_POLL_SECONDS:-60}"
HOTSPOTS="$REPO_ROOT/skill_runs/hotspots.json"

check_ready() {
  "$PYTHON_BIN" - "$REPO_ROOT" "$HOTSPOTS" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

repo_root = Path(sys.argv[1])
hotspots = Path(sys.argv[2])
today = date.today()

if not hotspots.exists():
    print(f"Hotspots file not found: {hotspots}")
    raise SystemExit(2)

hotspots_mtime = datetime.fromtimestamp(hotspots.stat().st_mtime).date()
if hotspots_mtime != today:
    print(f"Hotspots file is stale: {hotspots}; mtime={hotspots_mtime.isoformat()}")
    raise SystemExit(2)

try:
    data = json.loads(hotspots.read_text(encoding="utf-8-sig"))
except Exception as exc:
    print(f"Hotspots JSON is invalid: {exc}")
    raise SystemExit(1)

if not isinstance(data, list) or not data:
    print("Hotspots JSON has no usable items")
    raise SystemExit(1)

report_path = repo_root / "skill_runs" / "pipeline_monitor" / "latest.json"
if report_path.exists():
    try:
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        print(f"Monitor report JSON is invalid: {exc}")
        raise SystemExit(1)
    finished_at = str(report.get("finishedAt") or "")
    if finished_at[:10] != today.isoformat():
        print(f"Monitor report is stale: finishedAt={finished_at}")
        raise SystemExit(2)
    status = str(report.get("status") or "")
    if status not in {"success", "partial_success"}:
        print(f"Monitor report is not successful: status={status}; error={report.get('error')}")
        raise SystemExit(1)
    if int(report.get("hotspotCount") or 0) <= 0:
        print("Monitor report has hotspotCount=0")
        raise SystemExit(1)

print("Feishu stage input is ready")
raise SystemExit(0)
PY
}

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Feishu stage"
  echo "RepoRoot=$REPO_ROOT"
  echo "Python=$PYTHON_BIN"
  echo "Hotspots=$HOTSPOTS"
  echo "WaitSeconds=$WAIT_SECONDS"

  deadline=$(( $(date +%s) + WAIT_SECONDS ))
  while true; do
    set +e
    check_ready
    ready_code=$?
    set -e
    if [ "$ready_code" -eq 0 ]; then
      break
    fi
    now="$(date +%s)"
    if [ "$ready_code" -eq 1 ] || [ "$now" -ge "$deadline" ]; then
      echo "Feishu stage input check failed with exit code $ready_code"
      exit "$ready_code"
    fi
    echo "Feishu stage input is not ready yet; retrying in ${POLL_SECONDS}s"
    sleep "$POLL_SECONDS"
  done

  set +e
  "$PYTHON_BIN" scripts/feishu_push.py --hotspots "$HOTSPOTS"
  code=$?
  set -e
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Feishu stage finished with exit code $code"
  exit "$code"
} >> "$LOG_FILE" 2>&1
