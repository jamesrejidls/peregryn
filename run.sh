#!/usr/bin/env bash
# Launches the Peregryn app.
# - Creates a virtualenv on first run
# - Installs requirements
# - Copies .env.example to .env if missing
# - Starts uvicorn

set -e
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "▶ Creating virtual environment..."
  $PYTHON -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "▶ Installing dependencies (this is a no-op if already installed)..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  echo "▶ Creating .env from .env.example — edit it to add your GEMINI_API_KEY and CLERK keys."
  cp .env.example .env
fi

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Peregryn is starting on http://localhost:8000"
echo "  (Open that URL in your browser to use the app)"
echo "════════════════════════════════════════════════════════════"
echo ""

exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
