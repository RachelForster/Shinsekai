@echo off
chcp 65001 > nul

:: Check that the current path contains only ASCII characters
powershell -Command "if ('%cd%' -match '[^\x20-\x7E]') { Write-Host 'Error: The current path contains non-ASCII characters (e.g. Chinese, Japanese).'; Write-Host 'Please move the folder to a path with only English characters, e.g. D:\Shinsekai'; Write-Host 'Current path: %cd%'; exit 1 } else { exit 0 }" > nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ========================================
    echo   Path contains non-ASCII characters!
    echo   Please move this folder to a path
    echo   with only English letters and numbers.
    echo   e.g. D:\Shinsekai
    echo ========================================
    echo   Current: %cd%
    echo ========================================
    pause
    exit /b 1
)

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
