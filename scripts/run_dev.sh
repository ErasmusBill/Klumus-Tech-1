#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

PORT="${1:-8000}"

if [ -d "${PROJECT_ROOT}/.venv" ]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
elif [ -d "${PROJECT_ROOT}/../.venv" ]; then
    PYTHON_BIN="${PROJECT_ROOT}/../.venv/bin/python"
else
    PYTHON_BIN="python3"
fi

echo "Starting development server on http://127.0.0.1:${PORT}/ ..."
exec "$PYTHON_BIN" manage.py runserver "127.0.0.1:${PORT}"
