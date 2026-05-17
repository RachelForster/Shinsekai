@echo off
chcp 65001 > nul
setlocal

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "PY=%USERPROFILE%\.codex\venvs\shinsekai-py312\Scripts\python.exe"

cd /d "%ROOT%"
"%PY%" "scripts\switch_t2i_provider.py" api
if errorlevel 1 pause

endlocal
