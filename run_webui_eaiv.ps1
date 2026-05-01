# 使用 conda 环境 eaiv 启动 PySide6 设置界面（不依赖当前 shell 是否已 activate）
$py = Join-Path $env:USERPROFILE ".conda\envs\eaiv\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "未找到 $py ，请先: conda create -n eaiv ... 或检查环境名是否为 eaiv"
    exit 1
}
& $py (Join-Path $PSScriptRoot "webui_qt.py")
