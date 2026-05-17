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
set "SHINSEKAI_TTS_PROVIDER=gpt-sovits"
set "SHINSEKAI_T2I_PROVIDER=comfyui"
"%PY%" "scripts\launch_chat_stable.py"
if errorlevel 1 pause

endlocal
