#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="$REPO_ROOT/skill_runs/logs"
LOCK_DIR="$REPO_ROOT/skill_runs/locks"
LOCK_FILE="$LOCK_DIR/ins_keyword_discovery.lock"
LOG_FILE="$LOG_DIR/ins_keyword_discovery_$STAMP.log"

is_enabled() {
  case "${INS_KEYWORD_DISCOVERY_DAILY_ENABLED:-false}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

mkdir -p "$LOG_DIR" "$LOCK_DIR"

if ! is_enabled; then
  echo "INS keyword discovery daily task disabled by INS_KEYWORD_DISCOVERY_DAILY_ENABLED" | tee -a "$LOG_FILE"
  exit 0
fi

if ! ( set -o noclobber; echo "$$ $(date -Iseconds)" > "$LOCK_FILE" ) 2>/dev/null; then
  echo "INS keyword discovery already running; lock exists: $LOCK_FILE" | tee -a "$LOG_FILE"
  exit 0
fi
trap 'rm -f "$LOCK_FILE"' EXIT

cd "$REPO_ROOT"
{
  echo "[$(date -Iseconds)] INS keyword discovery daily run started"
  echo "Repo: $REPO_ROOT"
  "$PYTHON_BIN" scripts/manual/ins_keyword_discovery.py --max-pool-terms 0
  echo "[$(date -Iseconds)] INS keyword discovery daily run finished"
} 2>&1 | tee -a "$LOG_FILE"
