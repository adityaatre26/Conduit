#!/usr/bin/env bash
# Conduit backend start script for Git Bash / WSL
# Usage: ./run.sh
set -e
cd "$(dirname "$0")"

echo "[Conduit] Backend starting..."

# ── Find Python ────────────────────────────────────────────────────────────────
PYTHON=""
for cmd in python python3 py; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ERROR] Python not found. Install Python 3.11+ and add it to PATH."
    exit 1
fi

echo "[Conduit] Using: $($PYTHON --version)"

# ── Ensure dependencies ────────────────────────────────────────────────────────
if ! $PYTHON -c "import uvicorn" &>/dev/null; then
    echo "[Conduit] Installing dependencies..."
    $PYTHON -m pip install -r requirements.txt --quiet
fi

# ── Load .env so Python picks it up even without python-dotenv in uvicorn ─────
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

# ── Start ──────────────────────────────────────────────────────────────────────
echo "[Conduit] Listening on http://localhost:8000"
$PYTHON -m uvicorn app.main:app --reload --port 8000
