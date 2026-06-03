"""Runtime environment snapshot for diagnostic logs and bundles."""

from __future__ import annotations

import logging
import os
import platform
import sys
from pathlib import Path
from typing import Any


def _detect_gpus() -> list[dict[str, Any]]:
    try:
        from ui.settings_ui.tts.tts_env_probe import get_gpu_list

        rows = get_gpu_list()
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    gpus: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            gpus.append(
                {
                    "device": row.get("device", ""),
                    "vendor": row.get("vendor", ""),
                    "vendor_id": row.get("vendor_id", ""),
                    "vram_gb": row.get("vram_gb", ""),
                }
            )
    return gpus


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
