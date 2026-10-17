#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python 3 was not found. Install Python 3.10 or newer first." >&2
    exit 1
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    "$PYTHON" -m venv "$ROOT/.venv"
    "$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements.txt"
fi

if [[ "${XDG_SESSION_TYPE:-}" != "wayland" && -n "${DISPLAY:-}" ]] \
    && ! command -v xdotool >/dev/null 2>&1; then
    echo "Note: install xdotool to enable active-window detection in X11."
fi

exec "$ROOT/.venv/bin/python" "$ROOT/main.py" "$@"
