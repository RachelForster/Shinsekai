"""Shared PyTorch wheel selection and reinstall planning.

PyTorch packages need stricter handling than ordinary plugin dependencies:

* the wheel channel (``cpu`` / ``cuXXX``) is part of runtime compatibility;
* ``torch``, ``torchvision`` and ``torchaudio`` must be kept as one stack;
* a broad requirement such as ``torch>=2`` must not accept an installed CPU
  wheel when the current machine should use a CUDA wheel.

This module deliberately owns the policy and the pure planning logic.  The
caller remains responsible for executing pip so its existing progress,
timeout, mirror and error-reporting behavior stays intact.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from core.plugins.pip_index_config import pip_index_urls as _pip_index_urls
from core.plugins.pip_runner import pip_win_creationflags

try:
    from packaging.requirements import InvalidRequirement, Requirement
except Exception:  # pragma: no cover - minimal embedded runtime fallback.
    InvalidRequirement = ValueError  # type: ignore[assignment]
    Requirement = None  # type: ignore[assignment]


PYTORCH_PROJECT_NAMES = ("torch", "torchvision", "torchaudio")
_PYTORCH_PROJECT_NAME_SET = frozenset(PYTORCH_PROJECT_NAMES)
_CUDA_VER_LINE_RE = re.compile(r"CUDA Version:\s*(\d+)\.(\d+)")
_LOCAL_BUILD_RE = re.compile(r"(?:^|[.+-])(cpu|cu\d+)(?:$|[.+-])", re.IGNORECASE)
_OFFICIAL_PYTORCH_WHEEL_BASE = "https://download.pytorch.org/whl"
_CHINA_PYTORCH_WHEEL_BASE = "https://mirrors.aliyun.com/pytorch-wheels"
_CHINA_INDEX_DOMAINS = (
    "pypi.tuna.tsinghua.edu.cn",
    "mirrors.ustc.edu.cn",
    "mirrors.hit.edu.cn",
    "mirrors.aliyun.com",
    "mirror.sjtu.edu.cn",
)
_CHINA_REGION_NAMES = frozenset({"china", "cn", "mainland", "mainland_china"})
_GLOBAL_REGION_NAMES = frozenset(
    {"official", "global", "intl", "international", "overseas", "us"}
)


@dataclass(frozen=True)
class PytorchInstallPlan:
    index_url: str
    index_reason: str
    expected_build: str
    install_required: bool
    force_reinstall: bool
    detail: str


def canonical_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip("-").lower()


def requirement_line_project_name(line: str) -> str | None:
    """Return the normalized project name for a plain requirement line."""
    segment = line.split("#", 1)[0].strip()
    if not segment:
        return None
    lower = segment.lower()
    if lower.startswith(("--", "-r ", "-c ")):
        return None
    if lower.startswith("-e "):
        segment = segment[2:].strip()
    first = segment.split()[0]
    if "://" in first or first.startswith("git+"):
        return None
    match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", segment)
    if not match:
        return None
    return canonical_distribution_name(match.group(1))


def partition_pytorch_requirement_lines(lines: list[str]) -> tuple[list[str], list[str]]:
    pytorch: list[str] = []
    rest: list[str] = []
    for line in lines:
        name = requirement_line_project_name(line)
        target = pytorch if name in _PYTORCH_PROJECT_NAME_SET else rest
        target.append(line.rstrip("\r\n"))
    return pytorch, rest


def nvidia_smi_cuda_driver_version() -> tuple[int, int] | None:
    """Parse the maximum CUDA version reported by ``nvidia-smi``."""
    pop_kw: dict[str, object] = {
        "args": ["nvidia-smi"],
        "capture_output": True,
        "text": True,
        "timeout": 20,
    }
    if sys.platform == "win32":
        flags = pip_win_creationflags()
        if flags:
            pop_kw["creationflags"] = flags
    try:
        proc = subprocess.run(**pop_kw)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    match = _CUDA_VER_LINE_RE.search(proc.stdout)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _explicit_pytorch_region() -> str:
    runtime_source = os.environ.get("SHINSEKAI_RUNTIME_SOURCE", "").strip().lower()
    if runtime_source in _CHINA_REGION_NAMES:
        return "china"
    if runtime_source in _GLOBAL_REGION_NAMES:
        return "global"
    mirror_region = os.environ.get("SHINSEKAI_MIRROR_REGION", "").strip().lower()
    if mirror_region in _CHINA_REGION_NAMES:
        return "china"
    if mirror_region in _GLOBAL_REGION_NAMES:
        return "global"
    return ""


def _configured_index_urls() -> list[str]:
    urls = list(_pip_index_urls())
    if urls:
        return urls
    # ``pip_index_urls`` deliberately returns [] when pip itself was explicitly
    # configured. Inspect those values only to choose a compatible PyTorch
    # mirror; they are never reused as PyTorch wheel URLs.
    for name in (
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "SHINSEKAI_PIP_INDEX_URL",
        "SHINSEKAI_PIP_INDEX_URLS",
    ):
        raw = os.environ.get(name, "")
        for line in raw.splitlines():
            urls.extend(part.strip() for part in line.split(",") if part.strip())
    return urls


def _indexes_prefer_china(index_urls: list[str]) -> bool:
    if not index_urls:
        return False
    primary = index_urls[0].lower()
    return any(domain in primary for domain in _CHINA_INDEX_DOMAINS)


def pytorch_wheel_base_url(index_urls: list[str] | None = None) -> str:
    override = os.environ.get("SHINSEKAI_PYTORCH_WHEEL_BASE", "").strip().rstrip("/")
    if override:
        return override
    region = _explicit_pytorch_region()
    if region == "china":
        return _CHINA_PYTORCH_WHEEL_BASE
    if region == "global":
        return _OFFICIAL_PYTORCH_WHEEL_BASE
    selected_indexes = _configured_index_urls() if index_urls is None else index_urls
    if _indexes_prefer_china(selected_indexes):
        return _CHINA_PYTORCH_WHEEL_BASE
    return _OFFICIAL_PYTORCH_WHEEL_BASE


def pytorch_wheel_index_url_for_cuda_version(
    version: tuple[int, int] | None,
    *,
    base_url: str | None = None,
) -> tuple[str, str]:
    base = (base_url or pytorch_wheel_base_url()).rstrip("/")
    if version is None:
        return f"{base}/cpu", "no_usable_nvidia_smi_cpu"
    major, minor = version
    if (major, minor) >= (12, 8):
        tag = "cu128"
    elif (major, minor) >= (12, 6):
        tag = "cu126"
    elif (major, minor) >= (12, 4):
        tag = "cu124"
    elif major >= 12:
        tag = "cu121"
    else:
        tag = "cu118"
    return f"{base}/{tag}", f"nvidia_driver_cuda_{major}.{minor}_{tag}"


def pytorch_wheel_index_url_for_this_machine() -> tuple[str, str]:
    return pytorch_wheel_index_url_for_cuda_version(nvidia_smi_cuda_driver_version())


def pytorch_index_build(index_url: str) -> str:
    candidate = index_url.rstrip("/").rsplit("/", 1)[-1].lower()
    if candidate == "cpu" or re.fullmatch(r"cu\d+", candidate):
        return candidate
    return ""


def installed_pytorch_project_names(installed_versions: Mapping[str, str]) -> list[str]:
    normalized = {
        canonical_distribution_name(name): version for name, version in installed_versions.items()
    }
    return [name for name in PYTORCH_PROJECT_NAMES if name in normalized]


def _active_requirement(line: str):
    stripped = line.split("#", 1)[0].strip()
    if not stripped:
        return None
    if Requirement is None:
        return stripped
    try:
        requirement = Requirement(stripped)
    except InvalidRequirement:
        return stripped
    if requirement.marker and not requirement.marker.evaluate():
        return None
    return requirement


def _installed_build(version: str) -> str:
    match = _LOCAL_BUILD_RE.search(version or "")
    return match.group(1).lower() if match else ""


def _build_matches(version: str, expected_build: str) -> bool:
    if not expected_build:
        return True
    installed_build = _installed_build(version)
    if expected_build == "cpu":
        # Some CPU-only PyPI wheels have no local ``+cpu`` suffix.
        return installed_build in {"", "cpu"}
    return installed_build == expected_build


def build_pytorch_install_plan(
    requirement_lines: list[str],
    installed_versions: Mapping[str, str],
    *,
    requirement_is_satisfied: Callable[[str, Mapping[str, str]], bool],
    index_url: str | None = None,
    index_reason: str | None = None,
) -> PytorchInstallPlan:
    """Decide whether the requested PyTorch stack can be reused.

    A missing package needs a normal install.  A version or wheel-channel
    mismatch needs ``--force-reinstall`` so pip replaces the complete stack
    instead of accepting a semantically compatible wheel from the wrong
    channel.
    """
    if index_url is None:
        index_url, detected_reason = pytorch_wheel_index_url_for_this_machine()
        if index_reason is None:
            index_reason = detected_reason
    if index_reason is None:
        index_reason = "configured"
    expected_build = pytorch_index_build(index_url)
    normalized_versions = {
        canonical_distribution_name(name): version for name, version in installed_versions.items()
    }

    active_lines: list[str] = []
    requested_names: list[str] = []
    for line in requirement_lines:
        active = _active_requirement(line)
        if active is None:
            continue
        active_lines.append(line)
        name = (
            canonical_distribution_name(active.name)
            if Requirement is not None and hasattr(active, "name")
            else requirement_line_project_name(str(active))
        )
        if name in _PYTORCH_PROJECT_NAME_SET and name not in requested_names:
            requested_names.append(name)

    if not active_lines:
        return PytorchInstallPlan(
            index_url=index_url,
            index_reason=index_reason,
            expected_build=expected_build,
            install_required=False,
            force_reinstall=False,
            detail="no active PyTorch requirements",
        )

    missing = [name for name in requested_names if name not in normalized_versions]
    unsatisfied = [
        line
        for line in active_lines
        if not requirement_is_satisfied(line, normalized_versions)
    ]
    if unsatisfied:
        installed_stack = installed_pytorch_project_names(normalized_versions)
        detail = (
            f"missing packages: {', '.join(missing)}"
            if missing and not installed_stack
            else "installed PyTorch versions do not match current requirements"
        )
        return PytorchInstallPlan(
            index_url=index_url,
            index_reason=index_reason,
            expected_build=expected_build,
            install_required=True,
            force_reinstall=bool(installed_stack),
            detail=detail,
        )

    wrong_build = [
        f"{name}=={normalized_versions[name]}"
        for name in PYTORCH_PROJECT_NAMES
        if name in normalized_versions
        and not _build_matches(normalized_versions[name], expected_build)
    ]
    if wrong_build:
        return PytorchInstallPlan(
            index_url=index_url,
            index_reason=index_reason,
            expected_build=expected_build,
            install_required=True,
            force_reinstall=True,
            detail=(
                f"expected {expected_build or 'selected'} wheels, found "
                + ", ".join(wrong_build)
            ),
        )

    return PytorchInstallPlan(
        index_url=index_url,
        index_reason=index_reason,
        expected_build=expected_build,
        install_required=False,
        force_reinstall=False,
        detail="installed PyTorch stack matches requirements and wheel channel",
    )
