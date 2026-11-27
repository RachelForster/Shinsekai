"""Runtime dependency bundle specifications and target interpreter resolution."""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import sysconfig
import tempfile
from typing import Any

from config.perception import default_perception_python_path
from core.runtime_env.pytorch import HOST_PYTORCH_REQUIREMENTS
from core.runtime_env.requirements import (
    canonical_distribution_name,
    check_requirement,
    requirement_name,
)
from sdk.exception.types import package_for_module

from .dependency_registry import (
    RUNTIME_DEPENDENCY_REGISTRY,
    RuntimeDependencyRegistry,
    RuntimeDependencySpec,
)

_SAFE_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?$")
_PYTHON_EXE_NAME_RE = re.compile(r"^python(?:\d+(?:\.\d+)*)?(?:\.exe)?$", re.IGNORECASE)
HUGGINGFACE_HUB_VERSION = "0.36.2"
HUGGINGFACE_HUB_SPEC = f"huggingface-hub=={HUGGINGFACE_HUB_VERSION}"
ONNXRUNTIME_SPEC = "onnxruntime"
TOKENIZERS_SPEC = "tokenizers>=0.20,<1"
TRANSFORMERS_SPEC = "transformers>=4.51.1,<5"
SENTENCE_TRANSFORMERS_SPEC = "sentence-transformers>=5.2,<6"
MEMORY_RUNTIME_PACKAGE_SPECS = (
    ONNXRUNTIME_SPEC,
    HUGGINGFACE_HUB_SPEC,
)
PERCEPTION_TORCH_SPEC = "torch>=2.1.0"
PERCEPTION_TORCHVISION_SPEC = "torchvision>=0.16.0"
PERCEPTION_TRANSFORMERS_SPEC = "transformers>=4.57.0,<5"
PERCEPTION_ACCELERATE_SPEC = "accelerate>=0.26.0"
PERCEPTION_HUGGINGFACE_HUB_SPEC = "huggingface-hub>=0.34.0,<1.0"
PERCEPTION_PILLOW_SPEC = "Pillow>=10.0.0"
PERCEPTION_RAPIDOCR_SPEC = "rapidocr-onnxruntime>=1.3.0"
PERCEPTION_GGUF_RAPIDOCR_SPEC = (
    f'{PERCEPTION_RAPIDOCR_SPEC}; sys_platform != "win32" or platform_machine != "ARM64"'
)
PERCEPTION_RUNTIME_PACKAGE_SPECS = (
    PERCEPTION_TORCH_SPEC,
    PERCEPTION_TORCHVISION_SPEC,
    PERCEPTION_TRANSFORMERS_SPEC,
    PERCEPTION_ACCELERATE_SPEC,
    PERCEPTION_HUGGINGFACE_HUB_SPEC,
    PERCEPTION_PILLOW_SPEC,
    PERCEPTION_RAPIDOCR_SPEC,
)
PERCEPTION_GGUF_RUNTIME_PACKAGE_SPECS = (
    PERCEPTION_PILLOW_SPEC,
    PERCEPTION_GGUF_RAPIDOCR_SPEC,
)


def _resolve_perception_target_python(state: Any) -> str:
    raw = ""
    project_root = getattr(state, "project_root_dir", "") if state is not None else ""
    app_root = getattr(state, "app_root_dir", "") if state is not None else ""
    if state is not None:
        api_cfg = getattr(
            getattr(getattr(state, "config_manager", None), "config", None),
            "api_config",
            None,
        )
        raw = str(getattr(api_cfg, "perception_python_path", "") or "").strip().strip('"')
    if not raw:
        raw = os.environ.get("SHINSEKAI_PERCEPTION_PYTHON", "").strip().strip('"')
    return default_perception_python_path(
        raw,
        project_root=project_root or None,
        app_root=app_root or None,
    )


def _register_builtin_runtime_dependencies(registry: RuntimeDependencyRegistry) -> None:
    registry.register_builtin(
        RuntimeDependencySpec(
            key="huggingface_hub",
            package_specs=(HUGGINGFACE_HUB_SPEC,),
        )
    )
    registry.register_builtin(
        RuntimeDependencySpec(
            key="onnxruntime",
            package_specs=MEMORY_RUNTIME_PACKAGE_SPECS,
        )
    )
    registry.register_builtin(
        RuntimeDependencySpec(
            key="mem0",
            package_specs=MEMORY_RUNTIME_PACKAGE_SPECS,
        )
    )
    registry.register_builtin(
        RuntimeDependencySpec(
            key="tokenizers",
            package_specs=(TOKENIZERS_SPEC,),
        )
    )
    registry.register_builtin(
        RuntimeDependencySpec(
            key="perception",
            package_specs=PERCEPTION_RUNTIME_PACKAGE_SPECS,
            pytorch_specs=(PERCEPTION_TORCH_SPEC, PERCEPTION_TORCHVISION_SPEC),
            pin_installed_torch=True,
            install_only_unsatisfied=True,
            install_spec_overrides={
                PERCEPTION_HUGGINGFACE_HUB_SPEC: HUGGINGFACE_HUB_SPEC,
            },
            requires_target_python=True,
            target_python=_resolve_perception_target_python,
            default_label="PyTorch / Transformers",
            secondary_group_label="Transformers / RapidOCR",
            success_message="感知运行环境依赖已就绪。",
        )
    )
    registry.register_builtin(
        RuntimeDependencySpec(
            key="perception_gguf",
            package_specs=PERCEPTION_GGUF_RUNTIME_PACKAGE_SPECS,
            install_only_unsatisfied=True,
            install_spec_overrides={
                PERCEPTION_GGUF_RAPIDOCR_SPEC: PERCEPTION_RAPIDOCR_SPEC,
            },
            requires_target_python=True,
            target_python=_resolve_perception_target_python,
            default_label="Pillow / RapidOCR",
            secondary_group_label="Pillow / RapidOCR",
            success_message="GGUF 感知运行环境依赖已就绪。",
        )
    )
    registry.register_builtin(
        RuntimeDependencySpec(
            key="sentence_transformers",
            package_specs=(
                SENTENCE_TRANSFORMERS_SPEC,
                TRANSFORMERS_SPEC,
                HUGGINGFACE_HUB_SPEC,
            ),
        )
    )


_register_builtin_runtime_dependencies(RUNTIME_DEPENDENCY_REGISTRY)


def resolve_runtime_dependency_spec(
    module_name: str,
    *,
    registry: RuntimeDependencyRegistry = RUNTIME_DEPENDENCY_REGISTRY,
) -> RuntimeDependencySpec:
    cleaned = str(module_name or "").strip()
    if not cleaned:
        raise ValueError("moduleName is required")
    registered = registry.get(cleaned)
    if registered is not None:
        return registered
    package_name = package_for_module(cleaned)
    if not _SAFE_PACKAGE_RE.match(package_name):
        raise ValueError(f"unsafe package name: {package_name}")
    return RuntimeDependencySpec(
        key=cleaned,
        package_specs=(package_name,),
    )


def site_packages_dirs_for_python(python_exe: str | Path) -> list[Path]:
    exe = Path(python_exe).expanduser()
    env_root = exe.parent
    if env_root.name.lower() in {"scripts", "bin"}:
        env_root = env_root.parent

    found: list[Path] = []
    win_sp = env_root / "Lib" / "site-packages"
    if win_sp.is_dir():
        found.append(win_sp)
    lib_dir = env_root / "lib"
    if lib_dir.is_dir():
        for child in lib_dir.glob("python*"):
            posix_sp = child / "site-packages"
            if posix_sp.is_dir():
                found.append(posix_sp)
    return found


def _python_env_root(python_exe: Path) -> Path:
    parent = python_exe.parent.resolve(strict=False)
    if parent.name.lower() in {"scripts", "bin"}:
        return parent.parent
    return parent


def _normalize_python_path_preserving_venv(path: Path) -> Path:
    expanded = Path(path).expanduser()
    parent_resolved = expanded.parent.resolve(strict=False)
    env_root = (
        parent_resolved.parent
        if parent_resolved.name.lower() in {"scripts", "bin"}
        else parent_resolved
    )
    if (env_root / "pyvenv.cfg").is_file():
        return parent_resolved / expanded.name
    return expanded.resolve(strict=False)


def _host_site_packages_dirs() -> set[Path]:
    dirs = {
        path.resolve(strict=False)
        for path in site_packages_dirs_for_python(Path(sys.executable))
    }
    sysconfig_paths = sysconfig.get_paths()
    for key in ("purelib", "platlib"):
        raw = sysconfig_paths.get(key)
        if raw:
            dirs.add(Path(raw).resolve(strict=False))
    return dirs


def targets_host_python_environment(target_py: str | Path | None) -> bool:
    """Return True when ``target_py`` targets the host Python interpreter or site-packages."""
    if target_py is None:
        return True
    normalized_target = _normalize_python_path_preserving_venv(Path(target_py))
    normalized_host = _normalize_python_path_preserving_venv(Path(sys.executable))
    target_root = _python_env_root(normalized_target)
    host_roots = {
        Path(sys.prefix).resolve(strict=False),
        _python_env_root(normalized_host),
    }
    if target_root in host_roots:
        return True
    target_sp = {
        path.resolve(strict=False)
        for path in site_packages_dirs_for_python(normalized_target)
    }
    if not target_sp:
        return False
    return bool(target_sp & _host_site_packages_dirs())


def python_has_cuda_torch(
    python_exe: str | Path,
    installed_versions: dict[str, str] | Any = None,
) -> bool:
    if installed_versions is not None:
        torch_ver = next(
            (
                v
                for k, v in installed_versions.items()
                if canonical_distribution_name(k) == "torch"
            ),
            "",
        )
        if "+cu" in torch_ver.lower():
            return True
    for sp in site_packages_dirs_for_python(python_exe):
        torch_lib = sp / "torch" / "lib"
        if not torch_lib.is_dir():
            continue
        if (
            (torch_lib / "torch_cuda.dll").is_file()
            or (torch_lib / "libc10_cuda.so").is_file()
            or any(torch_lib.glob("*cuda*"))
        ):
            return True
    return False


def _all_bundle_requirement_specs(spec: RuntimeDependencySpec) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in (*spec.package_specs, *spec.pytorch_specs):
        item = str(raw or "").strip()
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


def _host_pinned_pytorch_map() -> tuple[dict[str, str], dict[str, str]]:
    pinned_versions: dict[str, str] = {}
    pinned_requirements: dict[str, str] = {}
    for line in HOST_PYTORCH_REQUIREMENTS:
        cleaned = str(line or "").strip()
        if not cleaned:
            continue
        name = canonical_distribution_name(requirement_name(cleaned))
        if not name:
            continue
        pinned_requirements[name] = cleaned
        if "==" in cleaned:
            pinned_ver = cleaned.split("==", 1)[1].split(";", 1)[0].strip()
            if pinned_ver:
                pinned_versions[name] = pinned_ver
    return pinned_versions, pinned_requirements


def _pytorch_host_pin_conflicts(
    requirements_to_check: tuple[str, ...],
    *,
    strict_pytorch_only: bool = False,
) -> list[str]:
    pinned_versions, pinned_requirements = _host_pinned_pytorch_map()
    conflicts: list[str] = []
    for req_text in requirements_to_check:
        cleaned = str(req_text or "").strip()
        if not cleaned:
            continue
        canonical = canonical_distribution_name(requirement_name(cleaned))
        if canonical in pinned_versions:
            check = check_requirement(cleaned, pinned_versions)
            if check.applies and not check.satisfied:
                conflicts.append(
                    f"{cleaned} conflicts with host-pinned {pinned_requirements[canonical]}"
                )
        elif strict_pytorch_only:
            conflicts.append(
                f"{cleaned} is not managed by host-pinned PyTorch stack "
                f"({', '.join(HOST_PYTORCH_REQUIREMENTS)})"
            )
    return conflicts


def _write_temp_lines(prefix: str, lines: list[str]) -> Path:
    fd, temp_path_str = tempfile.mkstemp(prefix=prefix, suffix=".txt")
    path = Path(temp_path_str)
    try:
        os.close(fd)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
    except BaseException:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _resolve_target_python_executable(
    python_path: str | None,
    state: Any,
    *,
    spec: RuntimeDependencySpec | None = None,
) -> Path:
    raw = str(python_path or "").strip().strip('"')
    if not raw and spec is not None and spec.target_python is not None:
        resolved_target = (
            spec.target_python(state)
            if callable(spec.target_python)
            else spec.target_python
        )
        raw = str(resolved_target or "").strip().strip('"')

    if not raw:
        if spec is not None and spec.requires_target_python:
            if spec.key == "perception":
                raise ValueError("未找到可用的 Python 解释器路径。")
            raise ValueError(
                f"Runtime dependency bundle '{spec.key}' requires an explicit pythonPath."
            )
        if getattr(sys, "frozen", False):
            raise RuntimeError(
                "cannot run pip from a frozen executable; install dependencies in the bundled Python runtime"
            )
        return Path(sys.executable)

    candidate = Path(raw).expanduser()
    if candidate.is_dir():
        if os.name == "nt":
            rel_names = ("python.exe", "python3.exe", "Scripts/python.exe")
        else:
            rel_names = ("bin/python3", "bin/python", "python3", "python")
        found = next(
            (candidate / rel for rel in rel_names if (candidate / rel).is_file()),
            None,
        )
        if found is None:
            raise ValueError(f"指定的环境目录中未找到 Python 可执行文件：{candidate}")
        candidate = found

    if not candidate.is_file():
        raise ValueError(f"指定的 Python 路径不存在：{candidate}")
    if not _PYTHON_EXE_NAME_RE.match(candidate.name):
        raise ValueError(f"不支持的非 Python 可执行文件：{candidate.name}")
    resolved = _normalize_python_path_preserving_venv(candidate)
    if getattr(sys, "frozen", False) and resolved == _normalize_python_path_preserving_venv(
        Path(sys.executable)
    ):
        raise RuntimeError(
            "cannot run pip from a frozen executable; install dependencies in the bundled Python runtime"
        )
    return resolved
