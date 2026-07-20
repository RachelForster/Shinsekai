"""挂给执行代理的 macOS 工具（当前只支持 macOS 就够了）。

对齐 caiclaw ``tools/macos.go`` 的那一组：applescript / shortcuts / open_app /
open_url，外加一个 bash。极简：跑子进程、回收输出即可，异常由
``ToolManager.execute`` 统一兜住。
"""

from __future__ import annotations

import subprocess

from sdk.tool_registry import tool

_LIMIT = 50000


def _run(argv: list[str], timeout: int) -> str:
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    out = r.stdout + (("\nSTDERR: " + r.stderr) if r.stderr else "")
    return out.strip()[:_LIMIT] or "(no output)"


@tool(name="run_shell", group="macos", risk="high",
      description="在 macOS 上执行一条 bash 命令并返回输出。用于文件操作、包管理、git 等系统任务。")
def run_shell(command: str) -> str:
    return _run(["bash", "-c", command], 120)


@tool(name="applescript", group="macos", risk="high",
      description="执行 AppleScript。用于应用自动化、UI 控制、系统对话框、剪贴板、系统通知、日历与提醒事项。")
def applescript(script: str) -> str:
    return _run(["osascript", "-e", script], 30)


@tool(name="list_shortcuts", group="macos", risk="low",
      description="列出本机可用的「快捷指令」名称。")
def list_shortcuts() -> str:
    return _run(["shortcuts", "list"], 30)


@tool(name="run_shortcut", group="macos", risk="medium",
      description="按名称运行一个「快捷指令」。name: 指令名；input: 可选的输入文本。")
def run_shortcut(name: str, input: str = "") -> str:
    if input:
        return _run(["bash", "-c", "printf '%s' \"$1\" | shortcuts run \"$2\" -i -", "_", input, name], 60)
    return _run(["shortcuts", "run", name], 60)


@tool(name="open_app", group="macos", risk="low",
      description="用默认方式打开一个 macOS 应用。name: 应用名，如 'Calendar'。")
def open_app(name: str) -> str:
    return _run(["open", "-a", name], 15)


@tool(name="open_url", group="macos", risk="low",
      description="用默认浏览器打开一个网址。")
def open_url(url: str) -> str:
    return _run(["open", url], 15)
