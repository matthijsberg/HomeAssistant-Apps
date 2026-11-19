#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

TMP_WS="$(mktemp -d)"
trap 'rm -rf "$TMP_WS"' EXIT

export KICAD_MCP_WORKSPACE_ROOT="$TMP_WS"
export KICAD_MCP_ALLOWED_ROOTS="$TMP_WS"
export KICAD_MCP_BEARER_TOKEN="${DEMO_TOKEN:-local-demo-auth}"
export KICAD_MCP_READ_ONLY="true"

echo "[demo] Running test suite against isolated sandbox workspace: $TMP_WS"
if [ -x .venv/bin/pytest ]; then
    .venv/bin/pytest -v tests/
else
    PYTHONPATH=src /usr/local/bin/uv run --with pytest --with pytest-asyncio --with httpx --with-requirements requirements.txt pytest -v tests/
fi
