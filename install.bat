@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ========================================
echo   Installing...
echo ========================================
echo.

set "CONDA_ENV_NAME=shinsekai"
if not "%SHINSEKAI_CONDA_ENV%"=="" set "CONDA_ENV_NAME=%SHINSEKAI_CONDA_ENV%"

REM Check for embedded python, then the project conda env, then system python
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

REM Check if requirements.txt exists
if not exist "requirements.txt" (
    echo Error: requirements.txt not found
    echo Please ensure requirements.txt exists in the current directory
    pause
    exit /b 1
)

echo Installing dependencies...
echo.

%PYTHON_CMD% -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple  --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple  --extra-index-url https://pypi.org/simple

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
echo You can now run start.bat to launch the React settings center
pause
