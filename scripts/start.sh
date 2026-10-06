#!/usr/bin/env bash
# Starts backend + frontend together. Press Ctrl+C to stop both.
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 5001 &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT
cd frontend && npm run dev
