from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from sdk.exception.types import (
    MODULE_PACKAGE_MAP,
    missing_module_from_text,
    package_for_module,
    runtime_dependency_error_from_text,
)
_SAFE_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?$")


def install_runtime_dependency(module_name: str) -> dict[str, Any]:
    module_name = (module_name or "").strip()
    if not module_name:
        raise ValueError("moduleName is required")
    package_name = package_for_module(module_name)
    if not _SAFE_PACKAGE_RE.match(package_name):
        raise ValueError(f"unsafe package name: {package_name}")
    if getattr(sys, "frozen", False):
        raise RuntimeError("cannot run pip from a frozen executable; install dependencies in the bundled Python runtime")

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONUNBUFFERED", "1")
    cmd = [sys.executable, "-m", "pip", "install", package_name]
    completed = subprocess.run(
        cmd,
        cwd=str(Path.cwd()),
        env=env,
        text=True,
        capture_output=True,
        timeout=900,
    )
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if completed.returncode != 0:
        tail = output[-4000:] if output else f"pip exited with code {completed.returncode}"
        raise RuntimeError(tail)
    return {
        "message": f"Installed {package_name}. Please launch chat again.",
        "moduleName": module_name,
        "packageName": package_name,
        "pipCode": completed.returncode,
        "pipOutput": output[-4000:],
    }
