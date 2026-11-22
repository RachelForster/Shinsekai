from __future__ import annotations

from collections.abc import Mapping
import functools
import importlib
import importlib.metadata as importlib_metadata
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

from config.perception import default_perception_python_path
from core.runtime_env.pip_runner import (
    apply_pip_index_and_extra_args as _apply_pip_index_and_extra_args,
    run_pip_install as _run_pip_install,
)
from core.runtime_env.pytorch import (
    HOST_PYTORCH_REQUIREMENTS,
    build_pytorch_install_plan,
    pytorch_index_build,
    pytorch_wheel_index_url_for_this_machine,
)
from core.runtime_env.requirements import (
    RequirementCheck,
    canonical_distribution_name,
    check_requirement,
    requirement_name,
    unsatisfied_requirements,
)
from sdk.exception.types import (
    MODULE_PACKAGE_MAP,
    RuntimeDependencyError,
    missing_module_from_text,
    package_for_module,
    runtime_dependency_error_from_module,
    runtime_dependency_error_from_text,
)

from .dependency_registry import (
    RUNTIME_DEPENDENCY_REGISTRY,
    RuntimeDependencyRegistry,
    RuntimeDependencySpec,
    register_runtime_dependency,
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
PERCEPTION_RUNTIME_PACKAGE_SPECS = (
    PERCEPTION_TORCH_SPEC,
    PERCEPTION_TORCHVISION_SPEC,
    PERCEPTION_TRANSFORMERS_SPEC,
    PERCEPTION_ACCELERATE_SPEC,
    PERCEPTION_HUGGINGFACE_HUB_SPEC,
    PERCEPTION_PILLOW_SPEC,
    PERCEPTION_RAPIDOCR_SPEC,
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


def installed_versions_for_python(python_exe: str | Path) -> dict[str, str]:
    exe = Path(python_exe).expanduser()
    search_paths = [str(p) for p in site_packages_dirs_for_python(exe)]
    try:
        same_interpreter = exe.resolve() == Path(sys.executable).resolve()
    except OSError:
        same_interpreter = False
    if same_interpreter:
        for entry in sys.path:
            if entry and entry not in search_paths:
                search_paths.append(entry)
    if not search_paths:
        return {}
    versions: dict[str, str] = {}
    for dist in importlib_metadata.distributions(path=search_paths):
        name = dist.metadata.get("Name")
        if not name:
            continue
        versions.setdefault(canonical_distribution_name(name), dist.version)
    return versions


def python_has_cuda_torch(
    python_exe: str | Path,
    installed_versions: Mapping[str, str] | None = None,
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


@functools.lru_cache(maxsize=1)
def _machine_expected_pytorch_build() -> str:
    index_url, _ = pytorch_wheel_index_url_for_this_machine()
    return pytorch_index_build(index_url)


def _all_bundle_requirement_specs(spec: RuntimeDependencySpec) -> tuple[str, ...]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in (*spec.package_specs, *spec.pytorch_specs):
        item = str(raw or "").strip()
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return tuple(ordered)


def _spec_dependency_issues(
    spec: RuntimeDependencySpec,
    *,
    installed_versions: Mapping[str, str] | None = None,
    python_exe: str | Path | None = None,
) -> tuple[RequirementCheck, ...]:
    versions: Mapping[str, str] | None = installed_versions
    if versions is None and python_exe is not None:
        versions = installed_versions_for_python(python_exe)
    issues = list(unsatisfied_requirements(_all_bundle_requirement_specs(spec), versions))
    if spec.pytorch_specs and python_exe is not None and sys.platform != "darwin":
        version_map = dict(versions) if versions is not None else {}
        missing_names = {canonical_distribution_name(issue.name) for issue in issues}
        if (
            "torch" not in missing_names
            and not python_has_cuda_torch(python_exe, version_map)
            and _machine_expected_pytorch_build().startswith("cu")
        ):
            torch_ver = next(
                (
                    v
                    for k, v in version_map.items()
                    if canonical_distribution_name(k) == "torch"
                ),
                None,
            )
            issues.insert(
                0,
                RequirementCheck(
                    requirement="torch (CUDA)",
                    name="torch",
                    installed_version=torch_ver,
                    applies=True,
                    satisfied=False,
                ),
            )
    return tuple(issues)


def runtime_dependency_issues(
    module_name: str,
    *,
    installed_versions: Mapping[str, str] | None = None,
    python_exe: str | Path | None = None,
    registry: RuntimeDependencyRegistry = RUNTIME_DEPENDENCY_REGISTRY,
) -> tuple[RequirementCheck, ...]:
    spec = resolve_runtime_dependency_spec(module_name, registry=registry)
    return _spec_dependency_issues(
        spec,
        installed_versions=installed_versions,
        python_exe=python_exe,
    )


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


def perception_dependency_issues(
    python_exe: str | Path,
    *,
    installed_versions: Mapping[str, str] | None = None,
) -> tuple[RequirementCheck, ...]:
    return runtime_dependency_issues(
        "perception",
        installed_versions=installed_versions,
        python_exe=python_exe,
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


def _runtime_pip_install_cmd(
    package_specs: tuple[str, ...],
    *,
    python_executable: str | Path | None = None,
) -> list[str]:
    py = str(python_executable) if python_executable is not None else sys.executable
    return _apply_pip_index_and_extra_args(
        [py, "-m", "pip", "install", *package_specs],
        primary_flag="-i",
    )


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
    resolved = candidate.resolve()
    if getattr(sys, "frozen", False) and resolved == Path(sys.executable).resolve():
        raise RuntimeError(
            "cannot run pip from a frozen executable; install dependencies in the bundled Python runtime"
        )
    return resolved


def _execute_staged_dependency_spec(
    module_name: str,
    spec: RuntimeDependencySpec,
    target_py: Path,
    *,
    _task_id: str | None = None,
    _state: Any = None,
) -> dict[str, Any]:
    _task_available = bool(_task_id and _state is not None)
    if _task_available:
        from application.runtime.tasks import _append_task_log, _update_task

    output_lines: list[str] = []
    current_label = spec.default_label or spec.key

    def _emit_status(label: str, progress: float) -> None:
        if _task_available:
            _update_task(
                _state,
                _task_id,
                message=f"正在安装 {label}…",
                phase="pip",
                progress=progress,
            )

    def _on_line(line: str) -> None:
        output_lines.append(line)
        if _task_available:
            _append_task_log(_state, _task_id, line)
            _update_task(
                _state,
                _task_id,
                message=f"正在安装 {current_label}…",
                phase="pip",
                progress=min(0.92, 0.06 + len(output_lines) * 0.008),
            )

    def _fail(detail: str, code: str) -> None:
        output = "\n".join(output_lines).strip()
        err = detail or output[-4000:] or f"pip install failed ({code})"
        if _task_available:
            _update_task(
                _state,
                _task_id,
                error=err,
                message=f"安装 {current_label} 失败。",
                phase="failed",
                status="failed",
            )
        raise RuntimeError(err)

    versions = installed_versions_for_python(target_py)
    torch_tf: Path | None = None
    constraint_tf: Path | None = None
    try:
        if spec.pytorch_specs and sys.platform != "darwin":
            unsatisfied_torch = unsatisfied_requirements(spec.pytorch_specs, versions)
            torch_unsatisfied = bool(unsatisfied_torch)
            cuda_missing = (
                not torch_unsatisfied
                and not python_has_cuda_torch(target_py, versions)
                and _machine_expected_pytorch_build().startswith("cu")
            )
            if torch_unsatisfied or cuda_missing:
                pin_conflicts = _pytorch_host_pin_conflicts(
                    spec.pytorch_specs,
                    strict_pytorch_only=True,
                )
                if pin_conflicts:
                    conflict_parts = [issue.issue for issue in unsatisfied_torch]
                    conflict_parts.extend(pin_conflicts)
                    _fail(
                        f"Cannot satisfy PyTorch requirements for runtime bundle '{spec.key}': "
                        + "; ".join(conflict_parts),
                        "pytorch_version_conflict",
                    )
                plan = build_pytorch_install_plan(
                    list(HOST_PYTORCH_REQUIREMENTS),
                    versions,
                    requirement_is_satisfied=lambda line, inst: check_requirement(
                        line, inst
                    ).satisfied,
                )
                if plan.install_required:
                    current_label = f"PyTorch ({plan.expected_build or 'runtime'})"
                    _emit_status(current_label, 0.08)
                    torch_tf = _write_temp_lines(
                        f"shinsekai_{spec.key}_torch_",
                        list(plan.requirement_lines),
                    )
                    base_torch_cmd = [
                        str(target_py),
                        "-m",
                        "pip",
                        "install",
                        "--disable-pip-version-check",
                        "--index-url",
                        plan.index_url,
                        "--extra-index-url",
                        "https://pypi.org/simple",
                    ]
                    first_cmd = list(base_torch_cmd)
                    if plan.force_reinstall:
                        first_cmd.extend(["--upgrade", "--force-reinstall", "--no-deps"])
                    first_cmd.extend(["-r", str(torch_tf)])
                    code1, detail1 = _run_pip_install(
                        _apply_pip_index_and_extra_args(
                            first_cmd, list(plan.requirement_lines)
                        ),
                        cwd=Path.cwd(),
                        detail_max=4000,
                        timeout_sec=1200,
                        on_output_line=_on_line,
                    )
                    if code1 != "pip_ok":
                        _fail(detail1, code1)
                    if plan.force_reinstall:
                        deps_cmd = [*base_torch_cmd, "-r", str(torch_tf)]
                        code2, detail2 = _run_pip_install(
                            _apply_pip_index_and_extra_args(
                                deps_cmd, list(plan.requirement_lines)
                            ),
                            cwd=Path.cwd(),
                            detail_max=4000,
                            timeout_sec=900,
                            on_output_line=_on_line,
                        )
                        if code2 != "pip_ok":
                            _fail(detail2, code2)
                    versions = installed_versions_for_python(target_py)

        all_specs = _all_bundle_requirement_specs(spec)
        pytorch_spec_set = set(spec.pytorch_specs)
        other_check_specs = (
            all_specs
            if sys.platform == "darwin" or not pytorch_spec_set
            else tuple(item for item in all_specs if item not in pytorch_spec_set)
        )
        missing_other = unsatisfied_requirements(other_check_specs, versions)
        install_specs = tuple(
            spec.install_spec_overrides.get(issue.requirement, issue.requirement)
            for issue in missing_other
        )
        if install_specs:
            current_label = (
                missing_other[0].name
                if len(missing_other) == 1
                else (spec.secondary_group_label or current_label)
            )
            _emit_status(current_label, 0.55 if output_lines else 0.08)
            cmd_other = [
                str(target_py),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
            ]
            if spec.pin_installed_torch:
                constraint_lines: list[str] = []
                for pkg_key in ("torch", "torchvision", "torchaudio"):
                    inst_ver = versions.get(pkg_key, "")
                    base_ver = inst_ver.split("+", 1)[0].strip()
                    if base_ver:
                        constraint_lines.append(f"{pkg_key}=={base_ver}")
                if constraint_lines:
                    constraint_tf = _write_temp_lines(
                        "shinsekai_torch_pin_", constraint_lines
                    )
                    cmd_other.extend(["-c", str(constraint_tf)])
            cmd_other.extend(install_specs)
            code3, detail3 = _run_pip_install(
                _apply_pip_index_and_extra_args(
                    cmd_other, list(install_specs), primary_flag="-i"
                ),
                cwd=Path.cwd(),
                detail_max=4000,
                timeout_sec=900,
                on_output_line=_on_line,
            )
            if code3 != "pip_ok":
                _fail(detail3, code3)

        importlib.invalidate_caches()
        final_versions = installed_versions_for_python(target_py)
        remaining_issues = _spec_dependency_issues(
            spec,
            installed_versions=final_versions,
            python_exe=target_py,
        )
        if remaining_issues:
            detail_parts = [issue.issue for issue in remaining_issues]
            if sys.platform != "darwin" and (spec.pytorch_specs or spec.pin_installed_torch):
                remaining_reqs = tuple(
                    issue.requirement
                    for issue in remaining_issues
                    if issue.requirement != "torch (CUDA)"
                )
                for conflict in _pytorch_host_pin_conflicts(
                    remaining_reqs,
                    strict_pytorch_only=False,
                ):
                    if conflict not in detail_parts:
                        detail_parts.append(conflict)
            _fail(
                f"Target interpreter {target_py} does not satisfy runtime bundle "
                f"'{spec.key}': " + "; ".join(detail_parts),
                "bundle_verification_failed",
            )
    finally:
        for tf in (torch_tf, constraint_tf):
            if tf is not None:
                try:
                    tf.unlink(missing_ok=True)
                except OSError:
                    pass

    output = "\n".join(output_lines).strip()
    return {
        "message": spec.success_message or f"Installed {current_label}.",
        "moduleName": module_name,
        "packageName": spec.default_label or current_label,
        "pipCode": 0,
        "pipOutput": output[-4000:],
        "pythonPath": str(target_py),
    }


def install_runtime_dependency(
    module_name: str,
    *,
    python_path: str | None = None,
    _task_id: str | None = None,
    _state: Any = None,
    registry: RuntimeDependencyRegistry = RUNTIME_DEPENDENCY_REGISTRY,
) -> dict[str, Any]:
    cleaned_module = str(module_name or "").strip()
    if not cleaned_module:
        raise ValueError("moduleName is required")

    spec = resolve_runtime_dependency_spec(cleaned_module, registry=registry)
    if (
        spec.pytorch_specs
        or spec.install_only_unsatisfied
        or spec.requires_target_python
        or spec.target_python is not None
    ):
        target_py = _resolve_target_python_executable(python_path, _state, spec=spec)
        return _execute_staged_dependency_spec(
            cleaned_module,
            spec,
            target_py,
            _task_id=_task_id,
            _state=_state,
        )

    package_name = package_for_module(cleaned_module)
    if not _SAFE_PACKAGE_RE.match(package_name):
        raise ValueError(f"unsafe package name: {package_name}")
    package_specs = spec.package_specs
    package_label = (
        spec.default_label
        or (package_specs[0] if len(package_specs) == 1 else package_name)
    )
    target_exe: str | Path | None = None
    if python_path:
        target_exe = _resolve_target_python_executable(python_path, _state, spec=spec)
    elif getattr(sys, "frozen", False):
        raise RuntimeError(
            "cannot run pip from a frozen executable; install dependencies in the bundled Python runtime"
        )

    _task_available = bool(_task_id and _state is not None)
    if _task_available:
        from application.runtime.tasks import _append_task_log, _update_task

        _update_task(
            _state,
            _task_id,
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
                _state,
                _task_id,
                message=f"正在安装 {package_label}…",
                phase="pip",
                progress=min(0.9, 0.05 + len(output_lines) * 0.01),
            )

    code, detail = _run_pip_install(
        _runtime_pip_install_cmd(package_specs, python_executable=target_exe),
        cwd=Path.cwd(),
        detail_max=4000,
        timeout_sec=900,
        on_output_line=_on_line,
    )
    output = "\n".join(output_lines).strip()
    if code != "pip_ok":
        if _task_available:
            _update_task(
                _state,
                _task_id,
                error=detail or output[-4000:],
                message=f"安装 {package_label} 失败。",
                phase="failed",
                status="failed",
            )
        raise RuntimeError(detail or output[-4000:] or f"pip install failed ({code})")
    importlib.invalidate_caches()
    result: dict[str, Any] = {
        "message": spec.success_message
        or f"Installed {package_name}. Please launch chat again.",
        "moduleName": cleaned_module,
        "packageName": package_label,
        "pipCode": 0,
        "pipOutput": output[-4000:],
    }
    if target_exe is not None:
        result["pythonPath"] = str(target_exe)
    return result
