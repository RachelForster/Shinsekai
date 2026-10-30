@echo off
chcp 65001 > nul
setlocal

cd /d "%~dp0"

set "SHINSEKAI_SHOW_BACKEND_CONSOLE="
if /i "%~1"=="--backend-console" set "SHINSEKAI_SHOW_BACKEND_CONSOLE=1"
if /i "%~1"=="/backend-console" set "SHINSEKAI_SHOW_BACKEND_CONSOLE=1"
if /i "%~1"=="backend-console" set "SHINSEKAI_SHOW_BACKEND_CONSOLE=1"
if /i "%~1"=="--help" goto :usage
if /i "%~1"=="/?" goto :usage

:: Check that the current path contains only ASCII characters.
powershell -NoProfile -Command "if ('%cd%' -match '[^\x20-\x7E]') { exit 1 } else { exit 0 }" > nul 2>&1
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

:: Existing terminals may still have an older PATH after installing pnpm.
where pnpm > nul 2>&1
if errorlevel 1 (
    if defined PNPM_HOME if exist "%PNPM_HOME%\pnpm.cmd" (
        set "PATH=%PNPM_HOME%;%PATH%"
    )
)

where pnpm > nul 2>&1
if errorlevel 1 (
    if exist "%APPDATA%\npm\pnpm.cmd" (
        set "PATH=%APPDATA%\npm;%PATH%"
    )
)

where pnpm > nul 2>&1
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\pnpm\pnpm.cmd" (
        set "PATH=%LOCALAPPDATA%\pnpm;%PATH%"
    )
)

where pnpm > nul 2>&1
if errorlevel 1 (
    echo Error: pnpm was not found in PATH or the user install directories.
    echo Please install pnpm or enable it with: corepack enable
    pause
    exit /b 1
)

where cargo > nul 2>&1
if errorlevel 1 (
    if exist "%USERPROFILE%\.cargo\bin\cargo.exe" (
        set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
    )
)

where cargo > nul 2>&1
if errorlevel 1 (
    echo Error: cargo was not found in PATH.
    echo Please install Rust with rustup, then reopen this terminal.
    pause
    exit /b 1
)

if not exist "frontend\package.json" (
    echo Error: frontend\package.json was not found.
    pause
    exit /b 1
)

pushd frontend
call :ensure_frontend_dependencies
if errorlevel 1 (
    popd
    echo.
    echo Frontend dependency repair failed. See the error above.
    pause
    exit /b 1
)

echo Building Tauri app...
call pnpm exec tauri build --no-bundle
if errorlevel 1 (
    popd
    echo.
    echo Tauri build failed.
    pause
    exit /b 1
)
popd

set "EXE_PATH=frontend\src-tauri\target\release\Shinsekai.exe"
if not exist "%EXE_PATH%" (
    for /f "delims=" %%F in ('dir /b /s "frontend\src-tauri\target\release\*.exe" 2^>nul ^| findstr /v /i "\\deps\\ \\build\\ \\examples\\"') do (
        set "EXE_PATH=%%F"
        goto :found_exe
    )
)

:found_exe
if not exist "%EXE_PATH%" (
    echo.
    echo Build succeeded, but no release exe was found under:
    echo frontend\src-tauri\target\release
    pause
    exit /b 1
)

echo.
echo Opening %EXE_PATH%...
if "%SHINSEKAI_SHOW_BACKEND_CONSOLE%"=="1" (
    echo Backend console debug mode enabled.
)
start "" "%EXE_PATH%"
endlocal
exit /b 0

:ensure_frontend_dependencies
:: Check the actual CLI, including its native binary, instead of trusting node_modules.
call pnpm --config.verifyDepsBeforeRun=false exec tauri --version > nul 2>&1
if not errorlevel 1 exit /b 0

echo Tauri CLI is missing or incomplete. Restoring frontend dependencies...
:: pnpm 11 can otherwise skip repeat installs based on stale workspace metadata.
call pnpm install --frozen-lockfile --prod=false --force --config.optimisticRepeatInstall=false
if errorlevel 1 exit /b 1

call pnpm --config.verifyDepsBeforeRun=false exec tauri --version
if errorlevel 1 (
    echo Error: the project Tauri CLI is still unavailable after installing dependencies.
    exit /b 1
)
exit /b 0

:usage
echo Usage: start-tauri.bat [--backend-console]
echo.
echo   --backend-console   Show the backend Python terminal window for debugging.
endlocal
exit /b 0
