@echo off
chcp 65001 > nul
setlocal
set "PROJECT_ROOT=%~dp0"

set "SHINSEKAI_SHOW_BACKEND_CONSOLE="
if /i "%~1"=="--backend-console" set "SHINSEKAI_SHOW_BACKEND_CONSOLE=1"
if /i "%~1"=="/backend-console" set "SHINSEKAI_SHOW_BACKEND_CONSOLE=1"
if /i "%~1"=="backend-console" set "SHINSEKAI_SHOW_BACKEND_CONSOLE=1"
if /i "%~1"=="--help" goto :usage
if /i "%~1"=="/?" goto :usage

call :resolve_command pnpm
if errorlevel 1 (
    echo Error: pnpm was not found in PATH.
    echo Please install pnpm or enable it with: corepack enable
    pause
    exit /b 1
)
set "PNPM_CMD=%SHINSEKAI_RESOLVED_COMMAND%"

set "CARGO_CMD="
call :resolve_command cargo
if not errorlevel 1 set "CARGO_CMD=%SHINSEKAI_RESOLVED_COMMAND%"
if not defined CARGO_CMD (
    if defined USERPROFILE if exist "%USERPROFILE%\.cargo\bin\cargo.exe" (
        call :paths_are_non_reparse "%USERPROFILE%" "%USERPROFILE%\.cargo" "%USERPROFILE%\.cargo\bin" "%USERPROFILE%\.cargo\bin\cargo.exe"
        if errorlevel 1 (
            echo Error: USERPROFILE or the rustup cargo path is not an absolute, existing, non-reparse path.
            pause
            exit /b 1
        )
        set "CARGO_CMD=%USERPROFILE%\.cargo\bin\cargo.exe"
    )
)

if not defined CARGO_CMD (
    echo Error: cargo was not found in PATH.
    echo Please install Rust with rustup, then reopen this terminal.
    pause
    exit /b 1
)
for %%I in ("%CARGO_CMD%") do set "PATH=%%~dpI;%PATH%"
set "CARGO=%CARGO_CMD%"

if not exist "%PROJECT_ROOT%frontend\package.json" (
    echo Error: frontend\package.json was not found.
    pause
    exit /b 1
)
if not exist "%PROJECT_ROOT%frontend\src-tauri\Cargo.toml" (
    echo Error: frontend\src-tauri\Cargo.toml was not found.
    pause
    exit /b 1
)
call :paths_are_non_reparse "%PROJECT_ROOT%frontend" "%PROJECT_ROOT%frontend\package.json" "%PROJECT_ROOT%frontend\src-tauri" "%PROJECT_ROOT%frontend\src-tauri\Cargo.toml"
if errorlevel 1 (
    echo Error: frontend source paths are linked, missing, or unsafe.
    pause
    exit /b 1
)

echo Building Tauri app...
pushd "%PROJECT_ROOT%frontend"
call "%PNPM_CMD%" tauri build --no-bundle
if errorlevel 1 (
    popd
    echo.
    echo Tauri build failed.
    pause
    exit /b 1
)
popd

set "EXE_PATH=%PROJECT_ROOT%frontend\src-tauri\target\release\shinsekai.exe"
if not exist "%EXE_PATH%" (
    echo.
    echo Build succeeded, but the expected release executable was not found:
    echo "%EXE_PATH%"
    pause
    exit /b 1
)
call :paths_are_non_reparse "%PROJECT_ROOT%frontend" "%PROJECT_ROOT%frontend\src-tauri" "%PROJECT_ROOT%frontend\src-tauri\target" "%PROJECT_ROOT%frontend\src-tauri\target\release" "%EXE_PATH%"
if errorlevel 1 (
    echo.
    echo Build output path is linked, missing, or unsafe:
    echo "%EXE_PATH%"
    pause
    exit /b 1
)

echo.
echo Opening "%EXE_PATH%"...
if "%SHINSEKAI_SHOW_BACKEND_CONSOLE%"=="1" (
    echo Backend console debug mode enabled.
)
start "" "%EXE_PATH%"
endlocal
exit /b 0

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

:paths_are_non_reparse
set "SHINSEKAI_CHECK_PATH_1=%~1"
set "SHINSEKAI_CHECK_PATH_2=%~2"
set "SHINSEKAI_CHECK_PATH_3=%~3"
set "SHINSEKAI_CHECK_PATH_4=%~4"
set "SHINSEKAI_CHECK_PATH_5=%~5"
if not defined SystemRoot exit /b 1
if not exist "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" exit /b 1
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -Command "$ErrorActionPreference='Stop'; $paths=@($env:SHINSEKAI_CHECK_PATH_1,$env:SHINSEKAI_CHECK_PATH_2,$env:SHINSEKAI_CHECK_PATH_3,$env:SHINSEKAI_CHECK_PATH_4,$env:SHINSEKAI_CHECK_PATH_5); foreach($path in $paths){if([string]::IsNullOrWhiteSpace($path)){continue}; $driveAbsolute=$path -match '^[A-Za-z]:[\\/]'; $uncAbsolute=$path -match '^[\\/]{2}[^\\/]+[\\/][^\\/]+'; if(-not ($driveAbsolute -or $uncAbsolute)){exit 1}; $item=Get-Item -LiteralPath $path -Force; while($null -ne $item){if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){exit 1}; $item=$item.Parent}}; exit 0" > nul 2>&1
set "SHINSEKAI_CHECK_RESULT=%ERRORLEVEL%"
set "SHINSEKAI_CHECK_PATH_1="
set "SHINSEKAI_CHECK_PATH_2="
set "SHINSEKAI_CHECK_PATH_3="
set "SHINSEKAI_CHECK_PATH_4="
set "SHINSEKAI_CHECK_PATH_5="
exit /b %SHINSEKAI_CHECK_RESULT%

:usage
echo Usage: start-tauri.bat [--backend-console]
echo.
echo   --backend-console   Show the backend Python terminal window for debugging.
endlocal
exit /b 0
