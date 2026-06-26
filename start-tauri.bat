@echo off
chcp 65001 > nul
setlocal

cd /d "%~dp0"

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

where pnpm > nul 2>&1
if errorlevel 1 (
    echo Error: pnpm was not found in PATH.
    echo Please install pnpm or enable it with: corepack enable
    pause
    exit /b 1
)

if not exist "frontend\package.json" (
    echo Error: frontend\package.json was not found.
    pause
    exit /b 1
)

echo Building Tauri app...
pushd frontend
call pnpm tauri build --no-bundle
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
start "" "%EXE_PATH%"
endlocal
