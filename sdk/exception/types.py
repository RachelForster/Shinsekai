from __future__ import annotations

import re
from pathlib import Path
from typing import TypedDict


class RuntimeDependencyError(TypedDict, total=False):
    message: str
    moduleName: str
    packageName: str
    logPath: str


_NO_MODULE_PATTERNS = (
    re.compile(r"(?:ModuleNotFoundError|ImportError):\s+No module named ['\"]([^'\"]+)['\"]"),
    re.compile(r"No module named ['\"]([^'\"]+)['\"]"),
)

MODULE_PACKAGE_MAP = {
    "PIL": "Pillow",
    "anthropic": "anthropic",
    "cv2": "opencv-python",
    "google": "google-genai",
    "google.genai": "google-genai",
    "mem0": "mem0ai",
    "numpy": "numpy",
    "openai": "openai",
    "opencc": "opencc-python-reimplemented",
    "pandas": "pandas",
    "pygame": "pygame",
    "PySide6": "PySide6",
    "requests": "requests",
    "socksio": "socksio",
    "tiktoken": "tiktoken",
    "yaml": "PyYAML",
}


def missing_module_from_text(text: str) -> str | None:
    for pattern in _NO_MODULE_PATTERNS:
        match = pattern.search(text or "")
        if match:
            module_name = match.group(1).strip()
            return module_name or None
    return None


def missing_module_from_exception(exc: BaseException) -> str | None:
    if isinstance(exc, ModuleNotFoundError):
        module_name = getattr(exc, "name", None)
        if isinstance(module_name, str) and module_name.strip():
            return module_name.strip()
    return missing_module_from_text(str(exc))


def package_for_module(module_name: str) -> str:
    module_name = (module_name or "").strip()
    if module_name in MODULE_PACKAGE_MAP:
        return MODULE_PACKAGE_MAP[module_name]
    top_level = module_name.split(".", 1)[0]
    return MODULE_PACKAGE_MAP.get(top_level, top_level or module_name)


def runtime_dependency_error_from_text(
    text: str,
    *,
    log_path: str | Path | None = None,
) -> RuntimeDependencyError | None:
    module_name = missing_module_from_text(text)
    if not module_name:
        return None
    return runtime_dependency_error_from_module(module_name, log_path=log_path)


def runtime_dependency_error_from_exception(
    exc: BaseException,
    *,
    log_path: str | Path | None = None,
) -> RuntimeDependencyError | None:
    module_name = missing_module_from_exception(exc)
    if not module_name:
        return None
    return runtime_dependency_error_from_module(module_name, log_path=log_path)


def runtime_dependency_error_from_module(
    module_name: str,
    *,
    log_path: str | Path | None = None,
) -> RuntimeDependencyError:
    module_name = (module_name or "").strip()
    package_name = package_for_module(module_name)
    error: RuntimeDependencyError = {
        "message": f"Missing Python module: {module_name}",
        "moduleName": module_name,
        "packageName": package_name,
    }
    if log_path:
        error["logPath"] = str(log_path)
    return error
