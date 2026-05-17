@echo off
chcp 65001 > nul
setlocal

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "PY=%USERPROFILE%\.codex\venvs\shinsekai-py312\Scripts\python.exe"

if not exist "%PY%" (
    echo Python virtual environment not found:
    echo %PY%
    echo.
    echo Please ask Codex to reinstall the Shinsekai environment.
    pause
    exit /b 1
)

cd /d "%ROOT%"
"%PY%" "webui_qt.py"
if errorlevel 1 pause

endlocal
