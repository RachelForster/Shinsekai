#!/bin/bash
set -euo pipefail

resolve_script_directory() {
    local source_path="${BASH_SOURCE[0]}"
    local link_hops=0
    while [[ -L "$source_path" ]]; do
        local source_dir
        ((link_hops += 1))
        if ((link_hops > 64)); then
            echo "Error: launcher path contains too many symbolic-link hops: $source_path" >&2
            return 1
        fi
        source_dir="$(CDPATH= cd -P -- "$(/usr/bin/dirname "$source_path")" && pwd)"
        source_path="$(/usr/bin/readlink "$source_path")"
        [[ "$source_path" != /* ]] && source_path="$source_dir/$source_path"
    done
    CDPATH= cd -P -- "$(/usr/bin/dirname "$source_path")" && pwd
}

PROJECT_ROOT="$(resolve_script_directory)"
cd "$PROJECT_ROOT"
DELEGATED_SCRIPT="$PROJECT_ROOT/scripts/install.sh"
if [[ -L "$PROJECT_ROOT/scripts" || ! -d "$PROJECT_ROOT/scripts" ||
      -L "$DELEGATED_SCRIPT" || ! -f "$DELEGATED_SCRIPT" ]]; then
    echo "Error: delegated installer is missing or unsafe: $DELEGATED_SCRIPT" >&2
    exit 1
fi
exec /bin/bash "$DELEGATED_SCRIPT" "$@"
