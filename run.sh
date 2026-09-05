#!/usr/bin/env bash
# Run SpendSlicer from a source checkout: create a venv, install, serve.
# Prefer the desktop build or `pip install spendslicer[web,cur]` for normal use.
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================"
echo "  SpendSlicer"
echo "============================================"
echo

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 is not installed or not in PATH."
    exit 1
fi

PY_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 10) else 0)')
if [ "$PY_OK" != "1" ]; then
    echo "ERROR: Python 3.10 or newer is required (found $(python3 -V))."
    exit 1
fi

if [ ! -f "venv/bin/activate" ]; then
    if [ -d "venv" ]; then
        echo "Removing incompatible virtual environment (created on another OS)..."
        rm -rf venv
    fi
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate

echo "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -e ".[web,cur]"

echo
echo "Starting dashboard at http://127.0.0.1:8080/app"
echo "Press Ctrl+C to stop."
echo
# SPENDSLICER_RELOAD=1 enables uvicorn's autoreload for frontend/backend hacking.
exec python -m spendslicer.web.app
