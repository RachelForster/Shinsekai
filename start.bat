@echo off
chcp 65001 > nul

:: Check for embedded python, fall back to system python
if exist "runtime\python.exe" (
    set "PYTHON_EXE=runtime\python.exe"
) else (
    echo Embedded Python not found, falling back to system python...
    where python > nul 2>&1
    if %errorlevel% neq 0 (
        echo Error: python not found in PATH either
        pause
        exit /b 1
    )
    set "PYTHON_EXE=python"
)

%PYTHON_EXE% webui_qt.py
pause
