#!/bin/sh
set -eu
if [ "${OPYT50_PREVIEW_SEED_DEMO:-0}" = "1" ]; then
  if [ -z "${OPYT50_PREVIEW_PASSWORD:-}" ]; then
    echo "ERROR: OPYT50_PREVIEW_PASSWORD must be set for a public preview with demo users" >&2
    exit 2
  fi
  python scripts/seed_demo.py
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
