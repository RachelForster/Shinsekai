@echo off
setlocal
cd /d "%~dp0.."
set "COMFY_ROOT=%CD%\data\t2i_bundles\comfyui"
set "COMFY_PY=%COMFY_ROOT%\venv\Scripts\python.exe"
set "COMFY_MAIN=%COMFY_ROOT%\ComfyUI\main.py"
if not exist "%COMFY_PY%" (
  echo ComfyUI Python not found: "%COMFY_PY%"
  pause
  exit /b 1
)
if not exist "%COMFY_MAIN%" (
  echo ComfyUI main.py not found: "%COMFY_MAIN%"
  pause
  exit /b 1
)
"%COMFY_PY%" "%COMFY_MAIN%" --lowvram
