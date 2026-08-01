#!/bin/bash
set -euo pipefail

resolve_script_directory() {
    local source_path="${BASH_SOURCE[0]}"
    local source_dir
    local link_hops=0
    while [[ -L "$source_path" ]]; do
        ((link_hops += 1))
        if ((link_hops > 64)); then
            echo "Error: launcher path contains too many symbolic-link hops: $source_path" >&2
            return 1
        fi
        source_dir="$(CDPATH= cd -P -- "$(/usr/bin/dirname "$source_path")" && pwd)"
        source_path="$(/usr/bin/readlink "$source_path")"
        [[ "$source_path" = /* ]] || source_path="$source_dir/$source_path"
    done
    CDPATH= cd -P -- "$(/usr/bin/dirname "$source_path")" && pwd
}

SCRIPT_DIR="$(resolve_script_directory)"
PROJECT_ROOT="$(CDPATH= cd -P -- "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

PATH_CONTRACT="$PROJECT_ROOT/tools/launcher/shell-path-contract.sh"
if [[ -L "$PROJECT_ROOT/scripts" || ! -d "$PROJECT_ROOT/scripts" ||
      -L "$PATH_CONTRACT" || ! -f "$PATH_CONTRACT" ]]; then
    echo "Error: launcher path contract is missing or unsafe: $PATH_CONTRACT" >&2
    exit 1
fi
# shellcheck source=tools/launcher/shell-path-contract.sh
source "$PATH_CONTRACT"

if ! shinsekai_project_file_is_real "webui_react.py" ||
   ! shinsekai_project_file_is_real "requirements.txt"; then
    echo "Error: launcher could not identify the Shinsekai project root: $PROJECT_ROOT" >&2
    exit 1
fi

CONDA_ENV_NAME="${SHINSEKAI_CONDA_ENV:-shinsekai}"
if ! shinsekai_portable_environment_name "$CONDA_ENV_NAME"; then
    echo "Error: SHINSEKAI_CONDA_ENV must be a portable conda environment name" >&2
    exit 1
fi

if [[ -n "${CONDA_EXE:-}" && ( "$CONDA_EXE" != /* || ! -x "$CONDA_EXE" ) ]]; then
    echo "Error: CONDA_EXE must be an absolute executable path: $CONDA_EXE" >&2
    exit 1
fi
if [[ -n "${CONDA_PREFIX:-}" && "$CONDA_PREFIX" != /* ]]; then
    echo "Error: CONDA_PREFIX must be an absolute path: $CONDA_PREFIX" >&2
    exit 1
fi
if [[ -n "${HOME:-}" && "$HOME" != /* ]]; then
    echo "Error: HOME must be an absolute path when set: $HOME" >&2
    exit 1
fi

find_conda() {
    local -a candidates=("/opt/miniconda3/bin/conda" "/opt/anaconda3/bin/conda")
    local resolved
    if [[ -n "${HOME:-}" ]]; then
        candidates=("$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" "${candidates[@]}")
    fi
    if [ -n "${CONDA_EXE:-}" ] &&
       resolved="$(shinsekai_resolve_executable "$CONDA_EXE")"; then
        printf '%s\n' "$resolved"
        return 0
    fi
    if resolved="$(shinsekai_resolve_executable conda)"; then
        printf '%s\n' "$resolved"
        return 0
    fi
    for candidate in "${candidates[@]}"; do
        if resolved="$(shinsekai_resolve_executable "$candidate")"; then
            printf '%s\n' "$resolved"
            return 0
        fi
    done
    return 1
}

# Check for embedded python, then the project conda env, then system python
if EMBEDDED_PYTHON="$(shinsekai_find_embedded_python)"; then
    PYTHON_CMD=("$EMBEDDED_PYTHON")
elif [ "${CONDA_DEFAULT_ENV:-}" = "$CONDA_ENV_NAME" ] && [ -n "${CONDA_PREFIX:-}" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
    echo "Embedded Python not found, using active conda env ${CONDA_ENV_NAME}..."
    PYTHON_CMD=("$CONDA_PREFIX/bin/python")
elif CONDA_CMD="$(find_conda)"; then
    echo "Embedded Python not found, using conda env ${CONDA_ENV_NAME}..."
    if ! CONDA_PYTHON="$(shinsekai_resolve_conda_python "$CONDA_CMD" "$CONDA_ENV_NAME")"; then
        echo "Error: conda env ${CONDA_ENV_NAME} does not expose a deterministic Python path"
        exit 1
    fi
    PYTHON_CMD=("$CONDA_CMD" run --cwd / -n "$CONDA_ENV_NAME" "$CONDA_PYTHON")
else
    echo "Embedded Python not found, falling back to system python3..."
    if ! SYSTEM_PYTHON="$(shinsekai_resolve_executable python3)"; then
        echo "Error: neither conda env ${CONDA_ENV_NAME} nor python3 was found"
        exit 1
    fi
    PYTHON_CMD=("$SYSTEM_PYTHON")
fi

"${PYTHON_CMD[@]}" "$PROJECT_ROOT/webui_react.py" "$@"
