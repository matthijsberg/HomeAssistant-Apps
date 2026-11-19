#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

echo "[setup] Setting up KiCad Headless MCP local dev environment in $APP_DIR"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "[setup] Created .env from .env.example"
fi

if command -v uv >/dev/null 2>&1; then
    uv venv --allow-existing .venv
    uv pip install --python .venv/bin/python -r requirements.txt pytest pytest-asyncio httpx ruff
    uv pip install --python .venv/bin/python --no-deps -e .
else
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt pytest pytest-asyncio httpx ruff
    .venv/bin/pip install --no-deps -e .
fi

echo "[setup] Done. Run tests with: .venv/bin/pytest tests/"
