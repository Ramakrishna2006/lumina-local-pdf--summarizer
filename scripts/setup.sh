#!/usr/bin/env bash
# One-time setup for macOS / Linux.   Run:  bash scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[1/5] Checking tools..."
for tool in python3 node npm; do command -v "$tool" >/dev/null || { echo "$tool is not installed"; exit 1; }; done
command -v ollama >/dev/null || echo "WARNING: Ollama not found – install it from https://ollama.com/download"
command -v tesseract >/dev/null || echo "NOTE: Tesseract not found – needed only for scanned PDFs and images"

echo "[2/5] Creating Python virtual environment (.venv)..."
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements.txt

echo "[3/5] Creating .env..."
[ -f .env ] || cp .env.example .env

echo "[4/5] Installing frontend packages..."
(cd frontend && npm install)

echo "[5/5] Downloading AI models..."
if command -v ollama >/dev/null; then ollama pull llama3.2:3b; ollama pull embeddinggemma; fi

echo "Setup complete. Start with:  bash scripts/start.sh"
