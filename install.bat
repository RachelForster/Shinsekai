@echo off
chcp 65001 > nul
echo ========================================
echo   Installing...
echo ========================================
echo.

REM Check for embedded python, fall back to system python
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

REM Check if requirements.txt exists
if not exist "requirements.txt" (
    echo Error: requirements.txt not found
    echo Please ensure requirements.txt exists in the current directory
    pause
    exit /b 1
)

echo Installing dependencies...
echo.

%PYTHON_EXE% -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple  --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple  --extra-index-url https://pypi.org/simple

REM Check if installation succeeded
if %errorlevel% neq 0 (
    echo.
    echo Error occurred during dependency installation
    pause
    exit /b 1
)


setlocal
REM Add QT path to user environment variable
:: Get current directory
for /f "delims=" %%i in ('cd') do set "CURRENT_DIR=%%i"

:: Set QML path
set "QML_PATH=%CURRENT_DIR%\runtime\Lib\site-packages\PyQt5\Qt5\qml\Qt\labs\platform"

:: Check if path exists
if exist "%QML_PATH%" (
    :: Add to user PATH
    setx PATH "%PATH%;%QML_PATH%"
    echo Successfully added QT path to PATH: %QML_PATH%
) else (
    echo QT path does not exist: %QML_PATH%
)

endlocal

echo.
echo ========================================
echo   Installation complete!
echo ========================================
echo.
echo You can now run start.bat to launch the application
pause