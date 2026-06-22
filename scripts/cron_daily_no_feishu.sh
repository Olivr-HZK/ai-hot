#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export PYTHONIOENCODING="utf-8"
export PIPELINE_PLATFORMS="${PIPELINE_PLATFORMS:-tiktok,x,ins}"

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
LOG_FILE="$LOG_DIR/cron_daily_no_feishu_$STAMP.log"

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting daily no-Feishu pipeline"
  echo "RepoRoot=$REPO_ROOT"
  echo "Python=$PYTHON_BIN"
  echo "Platforms=$PIPELINE_PLATFORMS"
  set +e
  "$PYTHON_BIN" run_pipeline.py --platforms "$PIPELINE_PLATFORMS" --skip-feishu
  code=$?
  set -e
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Daily no-Feishu pipeline finished with exit code $code"
  exit "$code"
} >> "$LOG_FILE" 2>&1
