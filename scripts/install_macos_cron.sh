#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DAILY_CRON="${DAILY_CRON:-0 7 * * 1-5}"
MARKER_BEGIN="# social-media-hotspots cron begin"
MARKER_END="# social-media-hotspots cron end"

TMP_CRON="$(mktemp)"
trap 'rm -f "$TMP_CRON"' EXIT

{
  crontab -l 2>/dev/null | awk "
    BEGIN { skip = 0 }
    /^$MARKER_BEGIN$/ { skip = 1; next }
    /^$MARKER_END$/ { skip = 0; next }
    skip == 0 { print }
  "
  echo "$MARKER_BEGIN"
  echo "$DAILY_CRON /bin/bash \"$REPO_ROOT/scripts/cron_daily_full.sh\""
  echo "$MARKER_END"
} > "$TMP_CRON"

crontab "$TMP_CRON"

echo "Installed social-media-hotspots cron entries:"
echo "$DAILY_CRON /bin/bash \"$REPO_ROOT/scripts/cron_daily_full.sh\""
