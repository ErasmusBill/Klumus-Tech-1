#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

VENV_DIR="${PROJECT_ROOT}/.venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment at $VENV_DIR..."
    if command -v uv >/dev/null 2>&1; then
        uv venv "$VENV_DIR"
    else
        python3 -m venv "$VENV_DIR"
    fi
fi

if [ -f "$VENV_DIR/bin/activate" ]; then
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"
fi

echo "Installing requirements..."
if command -v uv >/dev/null 2>&1; then
    uv pip install -r requirements.txt
else
    pip install --upgrade pip
    pip install -r requirements.txt
fi

if [ ! -f .env.local ] && [ -f .env.local.example ]; then
    cp .env.local.example .env.local
    echo "Created .env.local from .env.local.example"
fi

python manage.py migrate --noinput
python manage.py check

echo ""
echo "Setup complete! Run the server with: ./scripts/run_dev.sh"
