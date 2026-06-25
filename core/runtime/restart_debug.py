from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


def _restart_debug_log_path() -> Path:
    if raw_path := os.environ.get("SHINSEKAI_RESTART_LOG"):
        return Path(raw_path)
    return Path(tempfile.gettempdir()) / "shinsekai-restart-debug.log"


def write_restart_debug_log(component: str, message: str) -> None:
    name = str(component or "runtime").strip() or "runtime"
    line = f"ts={time.time():.3f} pid={os.getpid()} component={name} {message}\n"
    print(f"[restart-debug] {line}", end="")
    try:
        with _restart_debug_log_path().open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass
