from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


_NO_MODULE_PATTERNS = (
    re.compile(r"(?:ModuleNotFoundError|ImportError):\s+No module named ['\"]([^'\"]+)['\"]"),
    re.compile(r"No module named ['\"]([^'\"]+)['\"]"),
)
_SAFE_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?$")

MODULE_PACKAGE_MAP = {
    "PIL": "Pillow",
    "anthropic": "anthropic",
    "cv2": "opencv-python",
    "google": "google-genai",
    "google.genai": "google-genai",
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


def package_for_module(module_name: str) -> str:
    module_name = (module_name or "").strip()
    if module_name in MODULE_PACKAGE_MAP:
        return MODULE_PACKAGE_MAP[module_name]
    top_level = module_name.split(".", 1)[0]
    return MODULE_PACKAGE_MAP.get(top_level, top_level or module_name)


def runtime_dependency_error_from_text(text: str, *, log_path: str | Path | None = None) -> dict[str, Any] | None:
    module_name = missing_module_from_text(text)
    if not module_name:
        return None
    package_name = package_for_module(module_name)
    error = {
        "message": f"Missing Python module: {module_name}",
        "moduleName": module_name,
        "packageName": package_name,
    }
    if log_path:
        error["logPath"] = str(log_path)
    return error


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
