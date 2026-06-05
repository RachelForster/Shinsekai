@echo off
chcp 65001 > nul
cd /d "%~dp0"

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

set "CONDA_ENV_NAME=shinsekai"
if not "%SHINSEKAI_CONDA_ENV%"=="" set "CONDA_ENV_NAME=%SHINSEKAI_CONDA_ENV%"

:: Check for embedded python, then the project conda env, then system python
set "PYTHON_CMD="
if exist "runtime\python.exe" (
    set "PYTHON_CMD=runtime\python.exe"
)
if "%PYTHON_CMD%"=="" if "%CONDA_DEFAULT_ENV%"=="%CONDA_ENV_NAME%" if exist "%CONDA_PREFIX%\python.exe" (
    echo Embedded Python not found, using active conda env %CONDA_ENV_NAME%...
    set PYTHON_CMD="%CONDA_PREFIX%\python.exe"
)
if "%PYTHON_CMD%"=="" (
    set "CONDA_CMD="
    if not "%CONDA_EXE%"=="" if exist "%CONDA_EXE%" set "CONDA_CMD=%CONDA_EXE%"
    if "%CONDA_CMD%"=="" (
        where conda > nul 2>&1
        if not errorlevel 1 set "CONDA_CMD=conda"
    )
    if not "%CONDA_CMD%"=="" (
        echo Embedded Python not found, using conda env %CONDA_ENV_NAME%...
        set PYTHON_CMD="%CONDA_CMD%" run -n %CONDA_ENV_NAME% python
    ) else (
        echo Embedded Python not found, falling back to system python...
        where python > nul 2>&1
        if errorlevel 1 (
            echo Error: neither conda env %CONDA_ENV_NAME% nor python was found
            pause
            exit /b 1
        )
        set "PYTHON_CMD=python"
    )
)

%PYTHON_CMD% webui_react.py %*
pause
