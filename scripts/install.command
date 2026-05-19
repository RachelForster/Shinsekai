#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/scripts/install.sh" ]; then
    ROOT_DIR="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/install.sh" ]; then
    ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
else
    echo "Error: scripts/install.sh not found next to or above $SCRIPT_DIR"
    exit 1
fi
TARGET="$ROOT_DIR/scripts/install.sh"
if [ "${SHINSEKAI_COMMAND_SMOKE:-}" = "1" ]; then
    printf '%s\n' "$TARGET"
    exit 0
fi
cd "$ROOT_DIR"
exec bash "$TARGET"
