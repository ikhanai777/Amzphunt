#!/usr/bin/env bash
# Run a live hunt with safe defaults, then print the digest of the results.
# Prevents overlapping runs (Amazon blocks clients that hammer it) and logs output.
#
# Usage: bash scripts/run_hunt.sh [preset] [extra amzphunt hunt args...]
#   presets: quick (~5 min), daily (~20-30 min, default), deep (~60-90 min)
# Example: bash scripts/run_hunt.sh daily -c kitchen pet-products
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source .venv/bin/activate

PRESET="${1:-daily}"
[ $# -gt 0 ] && shift

case "$PRESET" in
  quick) ARGS=(--depth 0 --pages 1 --deep 15) ;;
  daily) ARGS=(--depth 1 --max-subcategories 6 --pages 1 --deep 45) ;;
  deep)  ARGS=(--depth 1 --max-subcategories 15 --pages 2 --deep 90) ;;
  *) echo "unknown preset '$PRESET' (quick|daily|deep)"; exit 2 ;;
esac

SETTINGS=()
[ -f settings.json ] && SETTINGS=(--settings settings.json)

mkdir -p logs reports
LOG="logs/hunt-$(date +%Y%m%d-%H%M%S).log"
LOCK="$ROOT/.hunt.lock"

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  if ! flock -n 9; then
    echo "Another hunt is already running (lock: $LOCK). Not starting a second one."
    exit 3
  fi
else  # macOS has no flock: mkdir is atomic
  LOCK="$LOCK.d"
  if ! mkdir "$LOCK" 2>/dev/null; then
    echo "Another hunt is already running (lock: $LOCK). If none is, remove that directory."
    exit 3
  fi
  trap 'rmdir "$LOCK"' EXIT
fi

echo "==> hunt preset=$PRESET, log: $LOG"
if amzphunt hunt "${ARGS[@]}" "${SETTINGS[@]}" "$@" >"$LOG" 2>&1; then
  echo "==> done"
  grep -E "^Requests:" "$LOG" || true
  echo
  amzphunt latest --top 10
else
  status=$?
  echo "ERROR: hunt failed (exit $status). Last 30 log lines:"
  tail -30 "$LOG"
  exit "$status"
fi
