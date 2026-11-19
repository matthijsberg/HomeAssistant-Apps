#!/usr/bin/env bash
set -euo pipefail

# Headless wrapper for /usr/bin/kicad-cli.
# Only wraps `pcb render` in an ephemeral xvfb-run + Mesa llvmpipe context when DISPLAY is unset.
# All other subcommands execute /usr/bin/kicad-cli directly with zero overhead.

REAL_BIN="/usr/bin/kicad-cli"

if [ ! -x "$REAL_BIN" ]; then
    echo "ERROR: $REAL_BIN not found or not executable" >&2
    exit 127
fi

if [ "${1:-}" = "pcb" ] && [ "${2:-}" = "render" ] && [ -z "${DISPLAY:-}" ]; then
    export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"
    export GALLIUM_DRIVER="${GALLIUM_DRIVER:-llvmpipe}"
    export MESA_GL_VERSION_OVERRIDE="${MESA_GL_VERSION_OVERRIDE:-3.3}"
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/xdg-runtime}"
    mkdir -p "$XDG_RUNTIME_DIR"
    chmod 0700 "$XDG_RUNTIME_DIR" || true
    exec xvfb-run -a -s "-screen 0 1920x1080x24" "$REAL_BIN" "$@"
fi

exec "$REAL_BIN" "$@"
