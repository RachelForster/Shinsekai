"""Runtime environment snapshot for diagnostic logs and bundles."""

from __future__ import annotations

import logging
import os
import platform
import sys
from pathlib import Path
from typing import Any


def _detect_gpus() -> list[dict[str, Any]]:
    """GPU probing belonged to the retired Qt settings process."""
    return []


def runtime_environment(
    project_root: Path,
    *,
    level: int | None = None,
    log_path: Path | None = None,
) -> dict[str, Any]:
    gpus = _detect_gpus()
    payload: dict[str, Any] = {
        "cwd": Path.cwd().as_posix(),
        "executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
        "gpu_count": len(gpus),
        "gpus": gpus,
        "machine": platform.machine(),
        "os": platform.platform(),
        "pid": os.getpid(),
        "project_root": project_root.as_posix(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
    }
    if level is not None:
        payload["log_level"] = logging.getLevelName(level)
    if log_path is not None:
        payload["log_path"] = str(log_path)
    else:
        payload["log_path"] = ""
    return payload
