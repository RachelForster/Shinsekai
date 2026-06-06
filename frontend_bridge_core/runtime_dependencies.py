from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.plugins.pip_index_config import (
    has_explicit_pip_index as _has_explicit_pip_index,
    pip_index_args as _configured_pip_index_args,
)
from sdk.exception.types import (
    MODULE_PACKAGE_MAP,
    missing_module_from_text,
    package_for_module,
    runtime_dependency_error_from_text,
)
_SAFE_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?$")
_URL_CREDENTIAL_RE = re.compile(r"(?P<scheme>https?://)(?P<user>[^:/\s@]+)(?::(?P<password>[^@\s/]+))?@")


def _redact_url_credentials(text: str) -> str:
    return _URL_CREDENTIAL_RE.sub(lambda match: f"{match.group('scheme')}{match.group('user')}:***@", text or "")


def _runtime_pip_install_cmd(package_name: str) -> list[str]:
    extra_args_text = os.environ.get("SHINSEKAI_PIP_INSTALL_ARGS", "")
    extra_args = shlex.split(extra_args_text) if extra_args_text.strip() else []

    cmd = [sys.executable, "-m", "pip", "install", package_name]
    index_args = _configured_pip_index_args(primary_flag="-i")
    if index_args and not _has_explicit_pip_index([package_name, *extra_args]):
        cmd.extend(index_args)
    cmd.extend(extra_args)
    return cmd


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
    cmd = _runtime_pip_install_cmd(package_name)
    completed = subprocess.run(
        cmd,
        cwd=str(Path.cwd()),
        env=env,
        text=True,
        capture_output=True,
        timeout=900,
    )
    output = _redact_url_credentials(
        "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    )
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
