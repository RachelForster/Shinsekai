#!/bin/bash
set -e

echo "========================================"
echo "  Installing..."
echo "========================================"
echo ""

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

# Check for embedded python, then the project conda env, then system python
if [ -f "runtime/bin/python3" ]; then
    PYTHON_CMD=("runtime/bin/python3")
elif [ -f "runtime/python.exe" ]; then
    PYTHON_CMD=("runtime/python.exe")
elif [ "${CONDA_DEFAULT_ENV:-}" = "$CONDA_ENV_NAME" ] && [ -n "${CONDA_PREFIX:-}" ] && [ -x "$CONDA_PREFIX/bin/python" ]; then
    echo "Embedded Python not found, using active conda env ${CONDA_ENV_NAME}..."
    PYTHON_CMD=("$CONDA_PREFIX/bin/python")
elif CONDA_CMD="$(find_conda)"; then
    echo "Embedded Python not found, using conda env ${CONDA_ENV_NAME}..."
    PYTHON_CMD=("$CONDA_CMD" run -n "$CONDA_ENV_NAME" python)
else
    echo "Embedded Python not found, falling back to system python3..."
    if ! command -v python3 &> /dev/null; then
        echo "Error: neither conda env ${CONDA_ENV_NAME} nor python3 was found"
        exit 1
    fi
    PYTHON_CMD=(python3)
fi

# Check if requirements.txt exists
if [ ! -f "requirements.txt" ]; then
    echo "Error: requirements.txt not found"
    echo "Please ensure requirements.txt exists in the current directory"
    exit 1
fi

echo "Installing dependencies..."
echo ""

"${PYTHON_CMD[@]}" -m pip install -r requirements.txt

echo ""
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo ""
echo "You can now run scripts/start.sh to launch the React settings center"
