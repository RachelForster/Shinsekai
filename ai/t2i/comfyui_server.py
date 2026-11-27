"""ComfyUI child process startup and managed lifecycle registration."""

from __future__ import annotations

import ipaddress
import os
import shlex
import subprocess
from typing import Any, Callable
from urllib.parse import urlsplit

from sdk.process_guard import get_process_registry


def start_comfyui_server(
    *,
    api_url: str,
    work_path: str,
    startup_args: str,
    auto_start: bool,
    is_server_ready: Callable[[], bool],
    wait_for_ready: Callable[[], bool],
    popen: Callable[..., Any] = subprocess.Popen,
) -> Any | None:
    """Start a local portable ComfyUI instance when not already running.

    Returns the spawned ``Popen`` handle registered with host lifetime, or
    ``None`` when reusing an externally started server.
    """
    if is_server_ready():
        print("ComfyUI server is already running.")
        return None

    if not auto_start:
        raise RuntimeError(
            "无法连接 ComfyUI API。请先用秋叶／绘世等自带启动器或原有方式启动 ComfyUI，"
            "等待网页可用，再将相同的服务根地址（含实际端口，不含 /prompt）填入 API 设定。"
            "整合包无需填写 ComfyUI 目录，也无需开启自动启动。"
        )

    host = urlsplit(api_url).hostname or ""
    try:
        local = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False
    if not local:
        raise ValueError("自动启动仅支持本机 ComfyUI；连接其他电脑时请关闭自动启动并在服务端启动 ComfyUI。")

    os_path = work_path
    embeded_python_path = os.path.join(os_path, "python_embeded", "python.exe")
    api_path = os.path.join(os_path, "ComfyUI", "main.py")
    if not os.path.isfile(embeded_python_path) or not os.path.isfile(api_path):
        raise ValueError(
            "自动启动目录必须是官方 Windows 便携版根目录，包含 python_embeded/python.exe "
            "和 ComfyUI/main.py。秋叶／绘世、桌面版或其他安装方式请关闭自动启动，"
            "使用自己的启动器启动后连接。"
        )

    port = urlsplit(api_url).port or 8188
    popen_kwargs: dict[str, Any] = {
        "cwd": os_path,
        "creationflags": subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    }
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True
    proc = popen(
        [embeded_python_path, "-s", api_path, "--port", str(port), *shlex.split(startup_args)],
        **popen_kwargs,
    )
    get_process_registry().register(
        proc,
        name="comfyui",
        kind="t2i",
        scope="host",
        name_hint="python",
    )
    print("ComfyUI server starting...")
    if wait_for_ready():
        print("ComfyUI server is ready.")
        return proc

    stop_comfyui_server(proc)
    raise RuntimeError("ComfyUI 启动后仍无法连接 API，请检查 ComfyUI 启动日志和 API 地址中的端口。")


def stop_comfyui_server(proc: Any | None, *, timeout: float = 5.0) -> None:
    """Terminate a Shinsekai-managed ComfyUI subprocess tree if still running."""
    if proc is not None:
        get_process_registry().stop_process(proc, timeout=timeout)
