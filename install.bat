@echo off
chcp 65001 > nul
echo ========================================
echo   安装程序中
echo ========================================
echo.

REM 检查是否存在嵌入式Python
if not exist "runtime\python.exe" (
    echo 错误: 未找到嵌入式Python运行时
    echo 请确保runtime文件夹包含python.exe
    pause
    exit /b 1
)

REM 检查是否存在requirements.txt
if not exist "requirements.txt" (
    echo 错误: 未找到requirements.txt文件
    echo 请确保requirements.txt存在于当前目录
    pause
    exit /b 1
)

echo 正在安装依赖包...
echo.

REM 使用嵌入式Python安装依赖
runtime\python.exe -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple  --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple  --extra-index-url https://pypi.org/simple

REM 检查安装是否成功
if %errorlevel% neq 0 (
    echo.
    echo 依赖安装过程中出现错误
    pause
    exit /b 1
)


setlocal
REM 添加QT 路径到用户环境变量里
:: 获取当前目录
for /f "delims=" %%i in ('cd') do set "CURRENT_DIR=%%i"

:: 设置QML路径
set "QML_PATH=%CURRENT_DIR%\runtime\Lib\site-packages\PyQt5\Qt5\qml\Qt\labs\platform"

:: 检查路径是否存在
if exist "%QML_PATH%" (
    :: 添加到用户PATH
    setx PATH "%PATH%;%QML_PATH%"
    echo 成功将QT路径添加到PATH: %QML_PATH%
) else (
    echo QT路径不存在: %QML_PATH%
)

endlocal

echo.
echo ========================================
echo   安装完成！
echo ========================================
echo.
echo 您现在可以运行 start.bat 启动应用程序
pause