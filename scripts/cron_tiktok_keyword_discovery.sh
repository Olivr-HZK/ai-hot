#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="$REPO_ROOT/skill_runs/logs"
LOG_FILE="$LOG_DIR/tiktok_keyword_discovery_$STAMP.log"
ROOT_ENV_FILE="$REPO_ROOT/.env"

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

load_root_env() {
  [ -f "$ROOT_ENV_FILE" ] || return 0
  local raw line key value first last
  while IFS= read -r raw || [ -n "$raw" ]; do
    line="${raw%$'\r'}"
    line="$(trim "$line")"
    [ -n "$line" ] || continue
    case "$line" in
      \#*) continue ;;
      *=*) ;;
      *) continue ;;
    esac
    key="$(trim "${line%%=*}")"
    value="$(trim "${line#*=}")"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [ "${#value}" -ge 2 ]; then
      first="${value:0:1}"
      last="${value: -1}"
      if { [ "$first" = "'" ] && [ "$last" = "'" ]; } || { [ "$first" = '"' ] && [ "$last" = '"' ]; }; then
        value="${value:1:${#value}-2}"
      fi
    fi
    export "$key=$value"
  done < "$ROOT_ENV_FILE"
}

is_enabled() {
  case "${TIKTOK_KEYWORD_DISCOVERY_DAILY_ENABLED:-false}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

mkdir -p "$LOG_DIR"
load_root_env
echo "Loaded root env: $ROOT_ENV_FILE" | tee -a "$LOG_FILE"

if ! is_enabled; then
  echo "TikTok keyword discovery daily task disabled by TIKTOK_KEYWORD_DISCOVERY_DAILY_ENABLED" | tee -a "$LOG_FILE"
  exit 0
fi

cd "$REPO_ROOT"
{
  echo "[$(date -Iseconds)] TikTok keyword discovery daily run started"
  echo "Repo: $REPO_ROOT"
  "$PYTHON_BIN" scripts/tiktok_keyword_discovery.py
  echo "[$(date -Iseconds)] TikTok keyword discovery daily run finished"
} 2>&1 | tee -a "$LOG_FILE"
