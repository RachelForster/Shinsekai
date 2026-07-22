from __future__ import annotations

import importlib
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
HUGGINGFACE_HUB_VERSION = "1.24.0"
_PINNED_PACKAGE_SPECS = {
    "huggingface_hub": f"huggingface-hub=={HUGGINGFACE_HUB_VERSION}",
}


def _runtime_package_spec(module_name: str, package_name: str) -> str:
    top_level = module_name.split(".", 1)[0]
    return _PINNED_PACKAGE_SPECS.get(
        module_name,
        _PINNED_PACKAGE_SPECS.get(top_level, package_name),
    )


def _runtime_pip_install_cmd(package_name: str) -> list[str]:
    return _apply_pip_index_and_extra_args(
        [sys.executable, "-m", "pip", "install", package_name],
        primary_flag="-i",
    )


def install_runtime_dependency(
    module_name: str,
    *,
    _task_id: str | None = None,
    _state: Any = None,
) -> dict[str, Any]:
    module_name = (module_name or "").strip()
    if not module_name:
        raise ValueError("moduleName is required")
    package_name = package_for_module(module_name)
    if not _SAFE_PACKAGE_RE.match(package_name):
        raise ValueError(f"unsafe package name: {package_name}")
    package_spec = _runtime_package_spec(module_name, package_name)
    if getattr(sys, "frozen", False):
        raise RuntimeError("cannot run pip from a frozen executable; install dependencies in the bundled Python runtime")

    _task_available = bool(_task_id and _state is not None)

    if _task_available:
        from .tasks import _append_task_log, _update_task

        _update_task(
            _state, _task_id,
            message=f"正在安装 {package_spec}…",
            phase="pip",
            progress=0.05,
        )

    output_lines: list[str] = []

    def _on_line(line: str) -> None:
        output_lines.append(line)
        if _task_available:
            _append_task_log(_state, _task_id, line)
            _update_task(
                _state, _task_id,
                message=f"正在安装 {package_spec}…",
                phase="pip",
                progress=min(0.9, 0.05 + len(output_lines) * 0.01),
            )

    code, detail = _run_pip_install(
        _runtime_pip_install_cmd(package_spec),
        cwd=Path.cwd(),
        detail_max=4000,
        timeout_sec=900,
        on_output_line=_on_line,
    )
    output = "\n".join(output_lines).strip()
    if code != "pip_ok":
        if _task_available:
            _update_task(
                _state, _task_id,
                error=detail or output[-4000:],
                message=f"安装 {package_spec} 失败。",
                phase="failed",
                status="failed",
        )
        raise RuntimeError(detail or output[-4000:] or f"pip install failed ({code})")
    importlib.invalidate_caches()
    return {
        "message": f"Installed {package_name}. Please launch chat again.",
        "moduleName": module_name,
        "packageName": package_spec,
        "pipCode": 0,
        "pipOutput": output[-4000:],
    }
