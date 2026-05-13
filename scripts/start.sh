#!/bin/bash

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

$PYTHON_EXE webui_qt.py
