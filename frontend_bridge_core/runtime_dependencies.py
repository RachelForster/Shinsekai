from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from core.plugins.pip_runner import (
    apply_pip_index_and_extra_args as _apply_pip_index_and_extra_args,
    run_pip_install as _run_pip_install,
)
from sdk.exception.types import (
    MODULE_PACKAGE_MAP,
    missing_module_from_text,
    package_for_module,
    runtime_dependency_error_from_text,
)
_SAFE_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?$")


def _runtime_pip_install_cmd(package_name: str) -> list[str]:
    return _apply_pip_index_and_extra_args(
        [sys.executable, "-m", "pip", "install", package_name],
        primary_flag="-i",
    )


def install_runtime_dependency(module_name: str) -> dict[str, Any]:
    module_name = (module_name or "").strip()
    if not module_name:
        raise ValueError("moduleName is required")
    package_name = package_for_module(module_name)
    if not _SAFE_PACKAGE_RE.match(package_name):
        raise ValueError(f"unsafe package name: {package_name}")
    if getattr(sys, "frozen", False):
        raise RuntimeError("cannot run pip from a frozen executable; install dependencies in the bundled Python runtime")

    output_lines: list[str] = []
    code, detail = _run_pip_install(
        _runtime_pip_install_cmd(package_name),
        cwd=Path.cwd(),
        timeout_sec=900,
        on_output_line=output_lines.append,
    )
    output = "\n".join(output_lines).strip()
    if code != "pip_ok":
        raise RuntimeError(detail or output[-4000:] or f"pip install failed ({code})")
    return {
        "message": f"Installed {package_name}. Please launch chat again.",
        "moduleName": module_name,
        "packageName": package_name,
        "pipCode": 0,
        "pipOutput": output[-4000:],
    }
