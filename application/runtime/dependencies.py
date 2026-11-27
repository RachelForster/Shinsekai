"""Runtime dependency verification and pip installation."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
import contextlib
import functools
import importlib
import importlib.metadata as importlib_metadata
from pathlib import Path
import sys
from typing import Any

from core.runtime_env.constraints import temporary_core_constraints_file
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
from .dependency_specs import (
    HUGGINGFACE_HUB_SPEC,
    HUGGINGFACE_HUB_VERSION,
    MEMORY_RUNTIME_PACKAGE_SPECS,
    ONNXRUNTIME_SPEC,
    PERCEPTION_ACCELERATE_SPEC,
    PERCEPTION_GGUF_RAPIDOCR_SPEC,
    PERCEPTION_GGUF_RUNTIME_PACKAGE_SPECS,
    PERCEPTION_HUGGINGFACE_HUB_SPEC,
    PERCEPTION_PILLOW_SPEC,
    PERCEPTION_RAPIDOCR_SPEC,
    PERCEPTION_RUNTIME_PACKAGE_SPECS,
    PERCEPTION_TORCHVISION_SPEC,
    PERCEPTION_TORCH_SPEC,
    PERCEPTION_TRANSFORMERS_SPEC,
    SENTENCE_TRANSFORMERS_SPEC,
    TOKENIZERS_SPEC,
    TRANSFORMERS_SPEC,
    _PYTHON_EXE_NAME_RE,
    _SAFE_PACKAGE_RE,
    _all_bundle_requirement_specs,
    _host_pinned_pytorch_map,
    _normalize_python_path_preserving_venv,
    _pytorch_host_pin_conflicts,
    _register_builtin_runtime_dependencies,
    _resolve_perception_target_python,
    _resolve_target_python_executable,
    _write_temp_lines,
    python_has_cuda_torch,
    resolve_runtime_dependency_spec,
    site_packages_dirs_for_python,
    targets_host_python_environment,
)


def installed_versions_for_python(python_exe: str | Path) -> dict[str, str]:
    exe = _normalize_python_path_preserving_venv(Path(python_exe))
    search_paths = [str(p) for p in site_packages_dirs_for_python(exe)]
    same_interpreter = exe == _normalize_python_path_preserving_venv(Path(sys.executable))
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


@functools.lru_cache(maxsize=1)
def _machine_expected_pytorch_build() -> str:
    index_url, _ = pytorch_wheel_index_url_for_this_machine()
    return pytorch_index_build(index_url)


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
                (v for k, v in version_map.items() if canonical_distribution_name(k) == "torch"),
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


def perception_dependency_issues(
    python_exe: str | Path,
    *,
    installed_versions: Mapping[str, str] | None = None,
) -> tuple[RequirementCheck, ...]:
    return runtime_dependency_issues("perception", installed_versions=installed_versions, python_exe=python_exe)


def perception_gguf_dependency_issues(
    python_exe: str | Path,
    *,
    installed_versions: Mapping[str, str] | None = None,
) -> tuple[RequirementCheck, ...]:
    return runtime_dependency_issues("perception_gguf", installed_versions=installed_versions, python_exe=python_exe)


def runtime_dependency_error_for_module(module_name: str) -> RuntimeDependencyError | None:
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
    constraints_path: Path | None = None,
) -> list[str]:
    py = str(python_executable) if python_executable is not None else sys.executable
    cmd = [py, "-m", "pip", "install", *package_specs]
    if constraints_path is not None:
        cmd.extend(["-c", str(constraints_path)])
    return _apply_pip_index_and_extra_args(cmd, primary_flag="-i")


@contextlib.contextmanager
def _core_constraints_context(target_py: str | Path | None) -> Iterator[Path | None]:
    if not targets_host_python_environment(target_py):
        yield None
        return
    with temporary_core_constraints_file() as core_tf:
        yield core_tf


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
            _update_task(_state, _task_id, message=f"正在安装 {label}…", phase="pip", progress=progress)

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
                _state, _task_id, error=err, message=f"安装 {current_label} 失败。", phase="failed", status="failed"
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
                pin_conflicts = _pytorch_host_pin_conflicts(spec.pytorch_specs, strict_pytorch_only=True)
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
                    requirement_is_satisfied=lambda line, inst: check_requirement(line, inst).satisfied,
                )
                if plan.install_required:
                    current_label = f"PyTorch ({plan.expected_build or 'runtime'})"
                    _emit_status(current_label, 0.08)
                    torch_tf = _write_temp_lines(f"shinsekai_{spec.key}_torch_", list(plan.requirement_lines))
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
                        _apply_pip_index_and_extra_args(first_cmd, list(plan.requirement_lines)),
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
                            _apply_pip_index_and_extra_args(deps_cmd, list(plan.requirement_lines)),
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
            spec.install_spec_overrides.get(issue.requirement, issue.requirement) for issue in missing_other
        )
        if install_specs:
            current_label = (
                missing_other[0].name if len(missing_other) == 1 else (spec.secondary_group_label or current_label)
            )
            _emit_status(current_label, 0.55 if output_lines else 0.08)
            cmd_other = [str(target_py), "-m", "pip", "install", "--disable-pip-version-check"]
            if spec.pin_installed_torch:
                constraint_lines: list[str] = []
                for pkg_key in ("torch", "torchvision", "torchaudio"):
                    inst_ver = versions.get(pkg_key, "")
                    base_ver = inst_ver.split("+", 1)[0].strip()
                    if base_ver:
                        constraint_lines.append(f"{pkg_key}=={base_ver}")
                if constraint_lines:
                    constraint_tf = _write_temp_lines("shinsekai_torch_pin_", constraint_lines)
                    cmd_other.extend(["-c", str(constraint_tf)])
            with _core_constraints_context(target_py) as core_tf:
                if core_tf is not None:
                    cmd_other.extend(["-c", str(core_tf)])
                cmd_other.extend(install_specs)
                code3, detail3 = _run_pip_install(
                    _apply_pip_index_and_extra_args(cmd_other, list(install_specs), primary_flag="-i"),
                    cwd=Path.cwd(),
                    detail_max=4000,
                    timeout_sec=900,
                    on_output_line=_on_line,
                )
            if code3 != "pip_ok":
                _fail(detail3, code3)

        importlib.invalidate_caches()
        final_versions = installed_versions_for_python(target_py)
        remaining_issues = _spec_dependency_issues(spec, installed_versions=final_versions, python_exe=target_py)
        if remaining_issues:
            detail_parts = [issue.issue for issue in remaining_issues]
            if sys.platform != "darwin" and (spec.pytorch_specs or spec.pin_installed_torch):
                remaining_reqs = tuple(
                    issue.requirement for issue in remaining_issues if issue.requirement != "torch (CUDA)"
                )
                for conflict in _pytorch_host_pin_conflicts(remaining_reqs, strict_pytorch_only=False):
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
    if spec.pytorch_specs or spec.install_only_unsatisfied or spec.requires_target_python or spec.target_python is not None:
        target_py = _resolve_target_python_executable(python_path, _state, spec=spec)
        return _execute_staged_dependency_spec(cleaned_module, spec, target_py, _task_id=_task_id, _state=_state)

    package_name = package_for_module(cleaned_module)
    if not _SAFE_PACKAGE_RE.match(package_name):
        raise ValueError(f"unsafe package name: {package_name}")
    package_specs = spec.package_specs
    package_label = spec.default_label or (package_specs[0] if len(package_specs) == 1 else package_name)
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

        _update_task(_state, _task_id, message=f"正在安装 {package_label}…", phase="pip", progress=0.05)

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

    with _core_constraints_context(target_exe) as core_tf:
        code, detail = _run_pip_install(
            _runtime_pip_install_cmd(package_specs, python_executable=target_exe, constraints_path=core_tf),
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
        "message": spec.success_message or f"Installed {package_name}. Please launch chat again.",
        "moduleName": cleaned_module,
        "packageName": package_label,
        "pipCode": 0,
        "pipOutput": output[-4000:],
    }
    if target_exe is not None:
        result["pythonPath"] = str(target_exe)
    return result
