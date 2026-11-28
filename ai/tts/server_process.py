"""Launch and stop local TTS servers with managed lifecycle tracking."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any

from sdk.process_guard import get_process_registry, subprocess_isolation_kwargs


def server_python(executable):
    path = Path(executable)
    if os.name == "nt":
        windowless = path.with_name("pythonw.exe")
        if windowless.is_file():
            return windowless
    return path


def start_server_process(executable, script, *, cwd, name: str = "tts-server"):
    options: dict[str, Any] = dict(subprocess_isolation_kwargs(hide_window=True))
    if os.name == "nt":
        # pythonw needs valid streams for server logging initialization.
        options["stdout"] = subprocess.DEVNULL
        options["stderr"] = subprocess.STDOUT
    proc = subprocess.Popen(
        [str(server_python(executable)), str(script)], cwd=str(cwd), **options
    )
    get_process_registry().register(
        proc,
        name=name,
        kind="tts",
        scope="host",
        name_hint="python",
    )
    return proc


def stop_server_process(proc: Any | None, *, timeout: float = 5.0) -> None:
    if proc is not None:
        get_process_registry().stop_process(proc, timeout=timeout)
