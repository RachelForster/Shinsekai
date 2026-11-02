"""Launch local TTS servers without a Windows console window."""

import os
from pathlib import Path
import subprocess


def server_python(executable):
    path = Path(executable)
    if os.name == "nt":
        windowless = path.with_name("pythonw.exe")
        if windowless.is_file():
            return windowless
    return path


def start_server_process(executable, script, *, cwd):
    options = {}
    if os.name == "nt":
        options = {
            "creationflags": subprocess.CREATE_NO_WINDOW,
            # pythonw needs valid streams for server logging initialization.
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.STDOUT,
        }
    return subprocess.Popen(
        [str(server_python(executable)), str(script)], cwd=str(cwd), **options
    )
