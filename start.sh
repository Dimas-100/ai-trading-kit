#!/usr/bin/env sh
# ai-trading-kit: one-time install into a private folder, then the kit's home screen.
set -e
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
    echo "Setting up a private Python folder for the kit (once)..."
    PY=""
    for candidate in python3.13 python3.12 python3.11 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
                PY="$candidate"
                break
            fi
        fi
    done
    if [ -z "$PY" ]; then
        echo "Python 3.11 or newer was not found. Install it from https://www.python.org/downloads/ and run this again."
        exit 1
    fi
    "$PY" -m venv .venv
    .venv/bin/python -m pip install --quiet --upgrade pip
    .venv/bin/python -m pip install --quiet -e .
fi
.venv/bin/python -m aitk "$@"
if [ $# -eq 0 ]; then
    echo
    echo "To use the kit from any terminal: $(pwd)/.venv/bin/aitk   (or: source .venv/bin/activate)"
fi
