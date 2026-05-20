#!/bin/bash
echo "============================================"
echo "  AWS Cost Dashboard"
echo "============================================"
echo

if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python is not installed or not in PATH."
    echo "Install Python from https://python.org"
    exit 1
fi

if [ ! -f "venv/bin/activate" ]; then
    if [ -d "venv" ]; then
        echo "Removing incompatible virtual environment (created on another OS)..."
        rm -rf venv
    fi
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    echo "Installing dependencies..."
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

echo
echo "Starting dashboard at http://localhost:5000"
echo "Press Ctrl+C to stop."
echo
python app.py
