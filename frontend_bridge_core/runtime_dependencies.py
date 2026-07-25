from __future__ import annotations

import importlib
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.plugins.pip_runner import (
    apply_pip_index_and_extra_args as _apply_pip_index_and_extra_args,
    run_pip_install as _run_pip_install,
)
from core.runtime.requirements import RequirementCheck, unsatisfied_requirements
from sdk.exception.types import (
    MODULE_PACKAGE_MAP,
    RuntimeDependencyError,
    missing_module_from_text,
    package_for_module,
    runtime_dependency_error_from_text,
    runtime_dependency_error_from_module,
)
_SAFE_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?$")
HUGGINGFACE_HUB_VERSION = "0.36.2"
HUGGINGFACE_HUB_SPEC = f"huggingface-hub=={HUGGINGFACE_HUB_VERSION}"
TRANSFORMERS_SPEC = "transformers>=4.51.1,<5"
SENTENCE_TRANSFORMERS_SPEC = "sentence-transformers>=5.2,<6"
FASTEMBED_SPEC = "fastembed"
MEM0_SPEC = "mem0ai[nlp]"
CLICK_SPEC = "click>=8.1,<9"
SPACY_SPEC = "spacy>=3.7,<4"
MEMORY_RUNTIME_PACKAGE_SPECS = (
    MEM0_SPEC,
    CLICK_SPEC,
    SPACY_SPEC,
    SENTENCE_TRANSFORMERS_SPEC,
    FASTEMBED_SPEC,
    TRANSFORMERS_SPEC,
    HUGGINGFACE_HUB_SPEC,
)
_RUNTIME_PACKAGE_SPECS = {
    "huggingface_hub": (HUGGINGFACE_HUB_SPEC,),
    "mem0": MEMORY_RUNTIME_PACKAGE_SPECS,
    "sentence_transformers": (
        SENTENCE_TRANSFORMERS_SPEC,
        TRANSFORMERS_SPEC,
        HUGGINGFACE_HUB_SPEC,
    ),
}


def runtime_dependency_issues(
    module_name: str,
    *,
    installed_versions: Mapping[str, str] | None = None,
) -> tuple[RequirementCheck, ...]:
    module_name = (module_name or "").strip()
    if not module_name:
        raise ValueError("moduleName is required")
    package_name = package_for_module(module_name)
    return unsatisfied_requirements(
        _runtime_package_specs(module_name, package_name),
        installed_versions,
    )


def runtime_dependency_error_for_module(
    module_name: str,
) -> RuntimeDependencyError | None:
    issues = runtime_dependency_issues(module_name)
    if not issues:
        return None
    error = runtime_dependency_error_from_module(module_name)
    error["message"] = "Missing or incompatible Python runtime dependencies: " + "; ".join(
        issue.issue for issue in issues
    )
    return error


def _runtime_package_specs(module_name: str, package_name: str) -> tuple[str, ...]:
    top_level = module_name.split(".", 1)[0]
    return _RUNTIME_PACKAGE_SPECS.get(
        module_name,
        _RUNTIME_PACKAGE_SPECS.get(top_level, (package_name,)),
    )


def _runtime_pip_install_cmd(package_specs: tuple[str, ...]) -> list[str]:
    return _apply_pip_index_and_extra_args(
        [sys.executable, "-m", "pip", "install", *package_specs],
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
    package_specs = _runtime_package_specs(module_name, package_name)
    package_label = package_specs[0] if len(package_specs) == 1 else package_name
    if getattr(sys, "frozen", False):
        raise RuntimeError("cannot run pip from a frozen executable; install dependencies in the bundled Python runtime")

    _task_available = bool(_task_id and _state is not None)

    if _task_available:
        from .tasks import _append_task_log, _update_task

        _update_task(
            _state, _task_id,
            message=f"正在安装 {package_label}…",
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
                message=f"正在安装 {package_label}…",
                phase="pip",
                progress=min(0.9, 0.05 + len(output_lines) * 0.01),
            )

    code, detail = _run_pip_install(
        _runtime_pip_install_cmd(package_specs),
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
                message=f"安装 {package_label} 失败。",
                phase="failed",
                status="failed",
        )
        raise RuntimeError(detail or output[-4000:] or f"pip install failed ({code})")
    importlib.invalidate_caches()
    return {
        "message": f"Installed {package_name}. Please launch chat again.",
        "moduleName": module_name,
        "packageName": package_label,
        "pipCode": 0,
        "pipOutput": output[-4000:],
    }
