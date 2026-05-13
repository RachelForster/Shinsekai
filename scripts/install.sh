#!/bin/bash
set -e

echo "========================================"
echo "  Installing..."
echo "========================================"
echo ""

# Check for embedded python, fall back to system python
if [ -f "runtime/bin/python3" ]; then
    PYTHON_EXE="runtime/bin/python3"
elif [ -f "runtime/python.exe" ]; then
    PYTHON_EXE="runtime/python.exe"
else
    echo "Embedded Python not found, falling back to system python3..."
    if ! command -v python3 &> /dev/null; then
        echo "Error: python3 not found in PATH either"
        exit 1
    fi
    PYTHON_EXE="python3"
fi

# Check if requirements.txt exists
if [ ! -f "requirements.txt" ]; then
    echo "Error: requirements.txt not found"
    echo "Please ensure requirements.txt exists in the current directory"
    exit 1
fi

echo "Installing dependencies..."
echo ""

$PYTHON_EXE -m pip install -r requirements.txt

echo ""
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo ""
echo "You can now run scripts/start.sh to launch the application"
