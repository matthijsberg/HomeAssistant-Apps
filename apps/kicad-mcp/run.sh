#!/usr/bin/env bash
set -euo pipefail

export PYTHONUNBUFFERED=1
export TZ="${TZ:-Europe/Amsterdam}"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-/data/kicad-config}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-/data/kicad-cache}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-/data/kicad-data}"
export XDG_STATE_HOME="${XDG_STATE_HOME:-/data/atopile-state}"
export ATO_NON_INTERACTIVE=1
export NONINTERACTIVE=1

mkdir -p "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME"

echo "=========================================================="
echo " Starting KiCad Headless MCP (Home Assistant App)         "
echo "=========================================================="

OPTIONS_FILE="${KICAD_MCP_OPTIONS_FILE:-/data/options.json}"
TOKEN_FILE="${KICAD_MCP_TOKEN_FILE:-/data/bearer_token.txt}"

CONFIGURED_TOKEN=""
if [ -f "$OPTIONS_FILE" ]; then
    CONFIGURED_TOKEN="$(jq -r '.bearer_token // empty' "$OPTIONS_FILE")"
fi

if [ -n "$CONFIGURED_TOKEN" ]; then
    export KICAD_MCP_BEARER_TOKEN="$CONFIGURED_TOKEN"
    echo "[KiCad-MCP] Using bearer token from add-on options."
else
    if [ ! -f "$TOKEN_FILE" ]; then
        /opt/venv/bin/python3 -c "import secrets; print(secrets.token_hex(32))" > "$TOKEN_FILE"
        chmod 600 "$TOKEN_FILE"
        TOKEN_PREVIEW="$(head -c 6 "$TOKEN_FILE")..."
        echo "[KiCad-MCP] Generated persistent bearer token at $TOKEN_FILE (prefix: $TOKEN_PREVIEW)"
    else
        chmod 600 "$TOKEN_FILE" || true
    fi
    export KICAD_MCP_BEARER_TOKEN="$(cat "$TOKEN_FILE")"
fi

echo "[KiCad-MCP] KiCad CLI version: $(/usr/local/bin/kicad-cli --version 2>&1 || echo 'unavailable')"
echo "[KiCad-MCP] ngspice version: $(ngspice --version 2>&1 | head -n 2 | tr '\n' ' ' || echo 'unavailable')"
echo "[KiCad-MCP] atopile version: $(/opt/atopile-venv/bin/ato --version 2>&1 | tail -n 1 || echo 'unavailable')"

# Fail-fast pre-flight compile check
/opt/venv/bin/python3 -m compileall -q /opt/kicad-mcp/src/kicad_mcp_app

echo "[KiCad-MCP] Launching Streamable HTTP MCP server on 0.0.0.0:8000..."
exec /opt/venv/bin/python3 -m kicad_mcp_app.server
