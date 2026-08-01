@echo off
chcp 65001 > nul
setlocal
set "PROJECT_ROOT=%~dp0"

if not exist "%PROJECT_ROOT%webui_react.py" (
    echo Error: launcher could not identify the Shinsekai project root:
    echo "%PROJECT_ROOT%"
    pause
    exit /b 1
)
if not exist "%PROJECT_ROOT%requirements.txt" (
    echo Error: launcher could not identify the Shinsekai project root:
    echo "%PROJECT_ROOT%"
    pause
    exit /b 1
)
call :paths_are_non_reparse "%PROJECT_ROOT%webui_react.py" "%PROJECT_ROOT%requirements.txt"
if errorlevel 1 (
    echo Error: project identity files are linked, missing, or unsafe:
    echo "%PROJECT_ROOT%"
    pause
    exit /b 1
)

set "CONDA_ENV_NAME=shinsekai"
if not defined SHINSEKAI_CONDA_ENV goto :conda_env_name_ready
call :configured_conda_env_name_is_safe
if errorlevel 1 goto :invalid_conda_env_name
set "CONDA_ENV_NAME=%SHINSEKAI_CONDA_ENV%"
goto :conda_env_name_ready
:invalid_conda_env_name
echo Error: SHINSEKAI_CONDA_ENV must be a portable conda environment name.
pause
exit /b 1
:conda_env_name_ready

if defined CONDA_EXE (
    call :paths_are_non_reparse "%CONDA_EXE%"
    if errorlevel 1 (
        echo Error: CONDA_EXE must be an absolute, existing, non-reparse path:
        echo "%CONDA_EXE%"
        pause
        exit /b 1
    )
)
if defined CONDA_PREFIX if /i "%CONDA_DEFAULT_ENV%"=="%CONDA_ENV_NAME%" (
    call :paths_are_non_reparse "%CONDA_PREFIX%" "%CONDA_PREFIX%\python.exe"
    if errorlevel 1 (
        echo Error: active CONDA_PREFIX must be an absolute, existing, non-reparse path:
        echo "%CONDA_PREFIX%"
        pause
        exit /b 1
    )
)

:: Check for embedded python, then the project conda env, then system python
if exist "%PROJECT_ROOT%runtime\python.exe" (
    call :paths_are_non_reparse "%PROJECT_ROOT%runtime" "%PROJECT_ROOT%runtime\python.exe"
    if errorlevel 1 (
        echo Error: embedded Python path is linked or unsafe:
        echo "%PROJECT_ROOT%runtime\python.exe"
        pause
        exit /b 1
    )
    set "PYTHON_EXE=%PROJECT_ROOT%runtime\python.exe"
    goto :run_python
)
if defined CONDA_PREFIX if /i "%CONDA_DEFAULT_ENV%"=="%CONDA_ENV_NAME%" if exist "%CONDA_PREFIX%\python.exe" (
    echo Embedded Python not found, using active conda env "%CONDA_ENV_NAME%"...
    set "PYTHON_EXE=%CONDA_PREFIX%\python.exe"
    goto :run_python
)
set "CONDA_CMD="
if defined CONDA_EXE if exist "%CONDA_EXE%" set "CONDA_CMD=%CONDA_EXE%"
if defined CONDA_CMD goto :run_conda
call :resolve_command conda
if not errorlevel 1 (
    set "CONDA_CMD=%SHINSEKAI_RESOLVED_COMMAND%"
    goto :run_conda
)

echo Embedded Python not found, falling back to system python...
call :resolve_command python
if errorlevel 1 (
    echo Error: neither conda env "%CONDA_ENV_NAME%" nor python was found
    pause
    exit /b 1
)
set "PYTHON_EXE=%SHINSEKAI_RESOLVED_COMMAND%"

:run_python
"%PYTHON_EXE%" "%PROJECT_ROOT%webui_react.py" %*
goto :finish

:run_conda
echo Embedded Python not found, using conda env "%CONDA_ENV_NAME%"...
call :resolve_conda_python "%CONDA_CMD%" "%CONDA_ENV_NAME%"
if errorlevel 1 (
    echo Error: conda env "%CONDA_ENV_NAME%" does not expose a safe absolute Python path.
    pause
    exit /b 1
)
"%CONDA_CMD%" run --cwd "%PROJECT_ROOT%" -n "%CONDA_ENV_NAME%" "%SHINSEKAI_CONDA_PYTHON%" "%PROJECT_ROOT%webui_react.py" %*

:finish
set "SHINSEKAI_EXIT_CODE=%ERRORLEVEL%"
pause
endlocal & exit /b %SHINSEKAI_EXIT_CODE%

:resolve_command
set "SHINSEKAI_RESOLVED_COMMAND="
if not defined SystemRoot exit /b 1
if not exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" exit /b 1
set "SHINSEKAI_COMMAND_RESOLVER=%PROJECT_ROOT%scripts\resolve-command.ps1"
call :paths_are_non_reparse "%PROJECT_ROOT%scripts" "%SHINSEKAI_COMMAND_RESOLVER%"
if errorlevel 1 exit /b 1
for /f "delims=" %%I in ('"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -File "%SHINSEKAI_COMMAND_RESOLVER%" -Name "%~1" 2^>nul') do if not defined SHINSEKAI_RESOLVED_COMMAND set "SHINSEKAI_RESOLVED_COMMAND=%%I"
if not defined SHINSEKAI_RESOLVED_COMMAND exit /b 1
call :paths_are_non_reparse "%SHINSEKAI_RESOLVED_COMMAND%"
if errorlevel 1 (
    set "SHINSEKAI_RESOLVED_COMMAND="
    exit /b 1
)
exit /b 0

:configured_conda_env_name_is_safe
if not defined SystemRoot exit /b 1
if not exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" exit /b 1
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "$value=$env:SHINSEKAI_CONDA_ENV; if($value -cnotmatch '\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\z' -or $value.EndsWith('.')){exit 1}; $stem=$value.Split('.')[0].ToUpperInvariant(); if($stem -match '\A(CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])\z'){exit 1}; exit 0" > nul 2>&1
exit /b %ERRORLEVEL%

:resolve_conda_python
set "SHINSEKAI_CONDA_PYTHON="
set "SHINSEKAI_CONDA_PREFIX="
if not defined SystemRoot exit /b 1
if not exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" exit /b 1
for /f "tokens=1,* delims==" %%A in ('"%~1" run --cwd "%SystemRoot%\System32" -n "%~2" "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "[Console]::Out.WriteLine('__SHINSEKAI_CONDA_PREFIX__=' + $env:CONDA_PREFIX)" 2^>nul') do if "%%A"=="__SHINSEKAI_CONDA_PREFIX__" set "SHINSEKAI_CONDA_PREFIX=%%B"
if not defined SHINSEKAI_CONDA_PREFIX exit /b 1
set "SHINSEKAI_CONDA_PYTHON=%SHINSEKAI_CONDA_PREFIX%\python.exe"
call :paths_are_non_reparse "%SHINSEKAI_CONDA_PREFIX%" "%SHINSEKAI_CONDA_PYTHON%"
if errorlevel 1 (
    set "SHINSEKAI_CONDA_PYTHON="
    exit /b 1
)
exit /b 0

:paths_are_non_reparse
set "SHINSEKAI_CHECK_PATH_1=%~1"
set "SHINSEKAI_CHECK_PATH_2=%~2"
if not defined SystemRoot exit /b 1
if not exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" exit /b 1
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "$ErrorActionPreference='Stop'; $paths=@($env:SHINSEKAI_CHECK_PATH_1,$env:SHINSEKAI_CHECK_PATH_2); foreach($path in $paths){if([string]::IsNullOrWhiteSpace($path)){continue}; $driveAbsolute=$path -match '^[A-Za-z]:[\\/]'; $uncAbsolute=$path -match '^[\\/]{2}[^\\/]+[\\/][^\\/]+'; if(-not ($driveAbsolute -or $uncAbsolute)){exit 1}; $item=Get-Item -LiteralPath $path -Force; while($null -ne $item){if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){exit 1}; $item=$item.Parent}}; exit 0" > nul 2>&1
set "SHINSEKAI_CHECK_RESULT=%ERRORLEVEL%"
set "SHINSEKAI_CHECK_PATH_1="
set "SHINSEKAI_CHECK_PATH_2="
exit /b %SHINSEKAI_CHECK_RESULT%
