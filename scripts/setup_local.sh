#!/usr/bin/env bash
# One-shot local setup for amzphunt: venv, dependencies, tests, live smoke test.
# Usage: bash scripts/setup_local.sh [--no-live]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || { echo "ERROR: Python 3.9+ required (found $("$PY" --version 2>&1))"; exit 1; }

if [ ! -d .venv ]; then
  echo "==> creating virtualenv .venv"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> installing amzphunt"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e ".[dev]"

echo "==> running tests"
python -m pytest -q

mkdir -p reports logs
[ -f settings.json ] || cp settings.example.json settings.json

if [ "${1:-}" != "--no-live" ]; then
  echo "==> live smoke test against amazon.ae (1 search request)"
  if amzphunt niche "lunch box" --category kitchen --no-history -q; then
    echo "==> live access OK"
  else
    echo "WARNING: live request failed - check internet access / captcha (see HERMES_DEPLOY.md troubleshooting)"
    exit 2
  fi
fi

echo
echo "Setup complete. Activate with:  source $ROOT/.venv/bin/activate"
echo "Run a hunt with:               bash $ROOT/scripts/run_hunt.sh"
