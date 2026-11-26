#!/bin/bash

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

CONDA_ENV_NAME="${SHINSEKAI_CONDA_ENV:-shinsekai}"

find_conda() {
    if [ -n "${CONDA_EXE:-}" ] && [ -x "$CONDA_EXE" ]; then
        printf '%s\n' "$CONDA_EXE"
        return 0
    fi
    if command -v conda > /dev/null 2>&1; then
        command -v conda
        return 0
    fi
    for candidate in "$HOME/miniconda3/bin/conda" "$HOME/anaconda3/bin/conda" "/opt/miniconda3/bin/conda" "/opt/anaconda3/bin/conda"; do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# Ensure PulseAudio default on Linux when unset
if [ "$(uname -s 2>/dev/null || true)" = "Linux" ]; then
    export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-pulseaudio}"
fi

# Check embedded python, active non-base conda env, project .venv, named conda env, then system python
if [ -x "runtime/bin/python3" ] || [ -f "runtime/bin/python3" ]; then
    PYTHON_CMD=("runtime/bin/python3")
elif [ -f "runtime/python.exe" ]; then
    PYTHON_CMD=("runtime/python.exe")
elif [ -n "${CONDA_PREFIX:-}" ] && [ -n "${CONDA_DEFAULT_ENV:-}" ] && [ "${CONDA_DEFAULT_ENV:-}" != "base" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
    echo "Embedded Python not found, using active conda env ${CONDA_DEFAULT_ENV}..."
    PYTHON_CMD=("$CONDA_PREFIX/bin/python")
elif [ -x ".venv/bin/python" ]; then
    echo "Embedded Python not found, using project .venv..."
    PYTHON_CMD=(".venv/bin/python")
elif CONDA_CMD="$(find_conda)"; then
    echo "Embedded Python not found, using conda env ${CONDA_ENV_NAME}..."
    PYTHON_CMD=("$CONDA_CMD" run -n "$CONDA_ENV_NAME" python)
elif command -v python3.10 > /dev/null 2>&1; then
    echo "Embedded Python not found, falling back to python3.10..."
    PYTHON_CMD=("$(command -v python3.10)")
else
    echo "Embedded Python not found, falling back to system python3..."
    if ! command -v python3 &> /dev/null; then
        echo "Error: neither .venv, conda env ${CONDA_ENV_NAME}, nor python3 was found"
        exit 1
    fi
    PYTHON_CMD=(python3)
fi

"${PYTHON_CMD[@]}" webui_react.py "$@"
