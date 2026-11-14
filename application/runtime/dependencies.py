from __future__ import annotations

import functools
import importlib
import importlib.metadata as importlib_metadata
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
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
    unsatisfied_requirements,
)
from sdk.exception.types import (
    MODULE_PACKAGE_MAP,
    RuntimeDependencyError,
    missing_module_from_text,
    package_for_module,
    runtime_dependency_error_from_text,
    runtime_dependency_error_from_module,
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
_RUNTIME_PACKAGE_SPECS = {
    "huggingface_hub": (HUGGINGFACE_HUB_SPEC,),
    "onnxruntime": MEMORY_RUNTIME_PACKAGE_SPECS,
    "mem0": MEMORY_RUNTIME_PACKAGE_SPECS,
    "perception": PERCEPTION_RUNTIME_PACKAGE_SPECS,
    "sentence_transformers": (
        SENTENCE_TRANSFORMERS_SPEC,
        TRANSFORMERS_SPEC,
        HUGGINGFACE_HUB_SPEC,
    ),
}


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


def perception_dependency_issues(
    python_exe: str | Path,
    *,
    installed_versions: Mapping[str, str] | None = None,
) -> tuple[RequirementCheck, ...]:
    versions = (
        dict(installed_versions)
        if installed_versions is not None
        else installed_versions_for_python(python_exe)
    )
    issues = list(runtime_dependency_issues("perception", installed_versions=versions))
    missing_names = {canonical_distribution_name(issue.name) for issue in issues}
    if (
        "torch" not in missing_names
        and sys.platform != "darwin"
        and not python_has_cuda_torch(python_exe, versions)
        and _machine_expected_pytorch_build().startswith("cu")
    ):
        torch_ver = next(
            (
                v
                for k, v in versions.items()
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
) -> Path:
    raw = str(python_path or "").strip().strip('"')
    project_root = getattr(state, "project_root_dir", "") if state is not None else ""
    app_root = getattr(state, "app_root_dir", "") if state is not None else ""
    if not raw and state is not None:
        api_cfg = getattr(getattr(getattr(state, "config_manager", None), "config", None), "api_config", None)
        raw = str(getattr(api_cfg, "perception_python_path", "") or "").strip().strip('"')
    if not raw:
        raw = os.environ.get("SHINSEKAI_PERCEPTION_PYTHON", "").strip().strip('"')
    resolved_str = default_perception_python_path(
        raw,
        project_root=project_root or None,
        app_root=app_root or None,
    )
    if not resolved_str:
        raise ValueError("未找到可用的 Python 解释器路径。")

    candidate = Path(resolved_str).expanduser()
    if candidate.is_dir():
        if os.name == "nt":
            rel_names = ("python.exe", "python3.exe", "Scripts/python.exe")
        else:
            rel_names = ("bin/python3", "bin/python", "python3", "python")
        found = next((candidate / rel for rel in rel_names if (candidate / rel).is_file()), None)
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


def _install_perception_runtime_dependencies(
    target_py: Path,
    *,
    _task_id: str | None = None,
    _state: Any = None,
) -> dict[str, Any]:
    _task_available = bool(_task_id and _state is not None)
    if _task_available:
        from application.runtime.tasks import _append_task_log, _update_task

    output_lines: list[str] = []
    current_label = "PyTorch / Transformers"

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
        if sys.platform != "darwin":
            torch_unsatisfied = bool(
                unsatisfied_requirements((PERCEPTION_TORCH_SPEC, PERCEPTION_TORCHVISION_SPEC), versions)
            )
            cuda_missing = (
                not torch_unsatisfied
                and not python_has_cuda_torch(target_py, versions)
                and _machine_expected_pytorch_build().startswith("cu")
            )
            if torch_unsatisfied or cuda_missing:
                plan = build_pytorch_install_plan(
                    list(HOST_PYTORCH_REQUIREMENTS),
                    versions,
                    requirement_is_satisfied=lambda line, inst: check_requirement(line, inst).satisfied,
                )
                if plan.install_required:
                    current_label = f"PyTorch ({plan.expected_build or 'runtime'})"
                    _emit_status(current_label, 0.08)
                    torch_tf = _write_temp_lines("shinsekai_perception_torch_", list(plan.requirement_lines))
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

        other_check_specs = (
            PERCEPTION_RUNTIME_PACKAGE_SPECS
            if sys.platform == "darwin"
            else (
                PERCEPTION_TRANSFORMERS_SPEC,
                PERCEPTION_ACCELERATE_SPEC,
                PERCEPTION_HUGGINGFACE_HUB_SPEC,
                PERCEPTION_PILLOW_SPEC,
                PERCEPTION_RAPIDOCR_SPEC,
            )
        )
        missing_other = unsatisfied_requirements(other_check_specs, versions)
        install_specs = tuple(
            HUGGINGFACE_HUB_SPEC
            if issue.requirement == PERCEPTION_HUGGINGFACE_HUB_SPEC
            else issue.requirement
            for issue in missing_other
        )
        if install_specs:
            current_label = missing_other[0].name if len(missing_other) == 1 else "Transformers / RapidOCR"
            _emit_status(current_label, 0.55 if output_lines else 0.08)
            constraint_lines: list[str] = []
            for pkg_key in ("torch", "torchvision", "torchaudio"):
                inst_ver = versions.get(pkg_key, "")
                base_ver = inst_ver.split("+", 1)[0].strip()
                if base_ver:
                    constraint_lines.append(f"{pkg_key}=={base_ver}")
            cmd_other = [str(target_py), "-m", "pip", "install", "--disable-pip-version-check"]
            if constraint_lines:
                constraint_tf = _write_temp_lines("shinsekai_torch_Pin_", constraint_lines)
                cmd_other.extend(["-c", str(constraint_tf)])
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
    finally:
        for tf in (torch_tf, constraint_tf):
            if tf is not None:
                try:
                    tf.unlink(missing_ok=True)
                except OSError:
                    pass

    importlib.invalidate_caches()
    output = "\n".join(output_lines).strip()
    return {
        "message": "感知运行环境依赖已就绪。",
        "moduleName": "perception",
        "packageName": current_label,
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
) -> dict[str, Any]:
    module_name = (module_name or "").strip()
    if not module_name:
        raise ValueError("moduleName is required")
    if module_name == "perception":
        target_py = _resolve_target_python_executable(python_path, _state)
        return _install_perception_runtime_dependencies(
            target_py,
            _task_id=_task_id,
            _state=_state,
        )
    package_name = package_for_module(module_name)
    if not _SAFE_PACKAGE_RE.match(package_name):
        raise ValueError(f"unsafe package name: {package_name}")
    package_specs = _runtime_package_specs(module_name, package_name)
    package_label = package_specs[0] if len(package_specs) == 1 else package_name
    target_exe: str | Path | None = None
    if python_path:
        target_exe = _resolve_target_python_executable(python_path, _state)
    elif getattr(sys, "frozen", False):
        raise RuntimeError("cannot run pip from a frozen executable; install dependencies in the bundled Python runtime")

    _task_available = bool(_task_id and _state is not None)

    if _task_available:
        from application.runtime.tasks import _append_task_log, _update_task

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
