#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================"
echo "  costsight"
echo "============================================"
echo

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 is not installed or not in PATH."
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
python -m costsight.web.app
