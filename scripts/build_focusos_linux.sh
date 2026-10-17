#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHON="${PYTHON:-python3}"
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    "$PYTHON" -m venv "$ROOT/.venv"
fi

"$ROOT/.venv/bin/python" -m pip install -r "$ROOT/requirements.txt"
"$ROOT/.venv/bin/python" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --name FocusOS \
    --add-data "$ROOT/qml:qml" \
    --add-data "$ROOT/extensions:extensions" \
    "$ROOT/main.py"
