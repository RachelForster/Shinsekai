"""Install plugin-local ``requirements.txt`` using the host or embeddable Python."""

from __future__ import annotations

from collections.abc import Callable, Mapping

import importlib.metadata as importlib_metadata
import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from core.paths import (
    app_root,
    managed_child_path,
    managed_project_storage,
    path_is_link_or_reparse_point,
    project_root,
    require_directory_without_links,
    resolve_executable_file,
    resolve_project_path,
    resolve_project_read_path,
    validate_exact_path_text,
)
from core.file_transactions import read_text_without_links, remove_file_without_links
from core.runtime_env.pip_index import (
    strip_inline_requirement_comment as _strip_inline_requirement_comment,
)
from core.runtime_env.pip_runner import (
    apply_pip_index_and_extra_args as _apply_pip_index_and_extra_args,
    run_pip_install as _run_pip_install,
)
from core.runtime_env.pytorch import (
    build_pytorch_install_plan as _build_pytorch_install_plan,
    partition_pytorch_requirement_lines as _partition_torch_requirement_lines,
)

try:
    from packaging.requirements import InvalidRequirement, Requirement
except Exception:  # pragma: no cover - fallback for minimal embedded runtimes.
    InvalidRequirement = ValueError  # type: ignore[assignment]
    Requirement = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

def frozen_release_root() -> Path | None:
    """打包运行时返回发行根目录；开发模式返回 ``None``。"""
    if not getattr(sys, "frozen", False):
        return None
    return app_root()


def pip_python_executable() -> Path:
    """
    用于 ``python -m pip`` 的解释器路径。

    冻结版：优先 ``<发行根>/runtime/python.exe``（或 ``python3.exe``），便于使用嵌入 Python；
    否则回退 ``sys.executable``（主程序 exe，通常无法运行 pip）。
    """
    if getattr(sys, "frozen", False):
        root = frozen_release_root()
        if root is not None:
            runtime_candidates = (
                (
                    Path("runtime/python.exe"),
                    Path("runtime/python3.exe"),
                    Path("runtime/bin/python.exe"),
                    Path("runtime/bin/python3.exe"),
                )
                if os.name == "nt"
                else (
                    Path("runtime/bin/python3"),
                    Path("runtime/bin/python"),
                    Path("runtime/python3"),
                    Path("runtime/python"),
                )
            )
            for relative in runtime_candidates:
                p = root / relative
                if os.path.lexists(p):
                    return resolve_executable_file(
                        p,
                        field="plugin pip Python executable",
                    )
    return resolve_executable_file(
        Path(sys.executable),
        field="host Python executable",
    )


def plugin_pip_target_directory(
    *,
    root: str | Path | None = None,
) -> Path | None:
    """
    冻结版：pip ``--target`` 的项目数据目录（由统一项目根决定）。
    开发模式返回 ``None``（依赖装入当前环境 site-packages，不使用 ``--target``）。
    """
    if not getattr(sys, "frozen", False):
        return None
    if root is None:
        return managed_project_storage("data/plugin_site_packages")
    return managed_project_storage("data/plugin_site_packages", root=root)


def ensure_plugin_site_packages_on_syspath(
    *,
    root: str | Path | None = None,
) -> None:
    """若存在冻结版插件依赖目录，则插入 ``sys.path`` 首位（须在加载插件前调用）。"""
    target = (
        plugin_pip_target_directory()
        if root is None
        else plugin_pip_target_directory(root=root)
    )
    if target is None:
        return
    if not target.is_dir():
        return
    target = require_directory_without_links(
        target,
        field="plugin site-packages directory",
    )
    s = str(target)
    if s not in sys.path:
        sys.path.insert(0, s)
        logger.info("Prepended plugin site-packages to sys.path: %s", s)


def ensure_plugins_namespace_on_syspath(
    *,
    root: str | Path | None = None,
) -> None:
    """
    将「含有 ``plugins/`` 子目录的一层级目录」置于 ``sys.path`` 首位，使 ``import plugins.xxx`` 可解析。

    源码运行时常已由入口脚本把项目根加入 ``sys.path``；冻结版仅有 ``_internal`` 等路径时，
    必须加入权威项目数据根（内含用户可写的 ``plugins/``）。
    """
    active_root = (
        project_root()
        if root is None
        else resolve_project_path(".", root=root)
    )
    plugins_root = managed_project_storage("plugins", root=active_root)
    if plugins_root.is_dir():
        s = str(active_root)
        if s not in sys.path:
            sys.path.insert(0, s)
            logger.info("Prepended project root for plugins namespace: %s", s)


def _requirement_line_project_name(line: str) -> str | None:
    """PEP 508-ish name from a single ``requirements.txt`` line, or None if not a plain package."""
    segment = line.split("#", 1)[0].strip()
    if not segment:
        return None
    lower = segment.lower()
    if lower.startswith(("--", "-r ", "-c ")):
        return None
    if lower.startswith("-e "):
        segment = segment[2:].strip()
        lower = segment.lower()
    first = segment.split()[0]
    if "://" in first or first.startswith("git+"):
        return None
    match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", segment)
    if not match:
        return None
    return match.group(1).lower().replace("_", "-")


def _has_non_comment_requirement(lines: list[str]) -> bool:
    for line in lines:
        s = line.split("#", 1)[0].strip()
        if s and not s.startswith("#"):
            return True
    return False


def _pip_base_install_cmd(py: Path, pip_target: Path | None) -> list[str]:
    cmd: list[str] = [
        str(py),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
    ]
    if pip_target is not None:
        pip_target.mkdir(parents=True, exist_ok=True)
        pip_target = require_directory_without_links(
            pip_target,
            field="plugin pip target directory",
        )
        cmd.extend(
            [
                "--target",
                str(pip_target),
                "--no-warn-script-location",
            ]
        )
    return cmd


def _canonical_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip("-").lower()


def _looks_like_direct_reference(line: str) -> bool:
    candidate = line.strip()
    if not candidate:
        return False
    first = candidate.split(maxsplit=1)[0]
    return (
        first in {".", ".."}
        or first.startswith(("./", "../", "/", "~/", ".\\", "..\\", "\\"))
        or first.startswith("git+")
        or "://" in first
        or " @ " in candidate
    )


def _requirement_line_can_be_pruned(line: str) -> bool:
    stripped = _strip_inline_requirement_comment(line)
    if not stripped:
        return True
    if stripped.startswith("-"):
        return False
    if _looks_like_direct_reference(stripped):
        return False
    return True


def _installed_distribution_versions(
    *,
    root: str | Path | None = None,
) -> dict[str, str]:
    paths = list(sys.path)
    target = (
        plugin_pip_target_directory()
        if root is None
        else plugin_pip_target_directory(root=root)
    )
    if target is not None and target.is_dir():
        # 打包版插件依赖会装进 data/plugin_site_packages，先查这里再看系统路径。
        target_s = str(
            require_directory_without_links(
                target,
                field="plugin site-packages directory",
            )
        )
        paths = [target_s, *[path for path in paths if path != target_s]]
    versions: dict[str, str] = {}
    for distribution in importlib_metadata.distributions(path=paths):
        dist_name = distribution.metadata.get("Name")
        if not dist_name:
            continue
        versions.setdefault(_canonical_distribution_name(dist_name), distribution.version)
    return versions


def _requirement_distribution_version(
    name: str,
    installed_versions: Mapping[str, str] | None = None,
    *,
    root: str | Path | None = None,
) -> str | None:
    canonical = _canonical_distribution_name(name)
    if installed_versions is None:
        installed_versions = (
            _installed_distribution_versions()
            if root is None
            else _installed_distribution_versions(root=root)
        )
    return installed_versions.get(canonical)


def _requirement_line_is_satisfied(
    line: str,
    installed_versions: Mapping[str, str] | None = None,
) -> bool:
    # 这里尽量按 PEP 508 判断：marker 不匹配就视为无需安装，版本不满足才进入 pip。
    stripped = _strip_inline_requirement_comment(line)
    if not stripped:
        return True
    if Requirement is None:
        name = _requirement_line_project_name(stripped)
        return bool(name and _requirement_distribution_version(name, installed_versions) is not None)
    try:
        requirement = Requirement(stripped)
    except InvalidRequirement:
        name = _requirement_line_project_name(stripped)
        return bool(name and _requirement_distribution_version(name, installed_versions) is not None)
    if requirement.marker and not requirement.marker.evaluate():
        return True
    installed_version = _requirement_distribution_version(requirement.name, installed_versions)
    if installed_version is None:
        return False
    if requirement.specifier:
        return requirement.specifier.contains(installed_version, prereleases=True)
    return True


def _install_lines_after_precheck(
    lines: list[str],
    *,
    root: str | Path | None = None,
) -> tuple[bool, list[str]]:
    # requirements 里出现 -e、--find-links、direct reference 等全局/本地语义时，不做裁剪。
    # 这些行可能影响后续包解析，强行只装“缺失行”反而会破坏作者的安装意图。
    if not all(_requirement_line_can_be_pruned(line) for line in lines):
        return False, lines
    installed_versions = (
        _installed_distribution_versions()
        if root is None
        else _installed_distribution_versions(root=root)
    )
    install_lines: list[str] = []
    for line in lines:
        stripped = _strip_inline_requirement_comment(line)
        if not stripped:
            continue
        if not _requirement_line_is_satisfied(stripped, installed_versions):
            install_lines.append(line.rstrip("\r\n"))
    return True, install_lines


def _write_temp_requirements(
    prefix: str,
    lines: list[str],
) -> tuple[Path, os.stat_result]:
    fd, temp_path_str = tempfile.mkstemp(prefix=prefix, suffix=".txt")
    # ``tempfile`` may return a trusted platform alias such as macOS /var.
    # Pin the newly created descriptor's canonical identity before passing the
    # filename to pip or to strict cleanup helpers.
    path = Path(temp_path_str).resolve(strict=True)
    identity = os.fstat(fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if not os.path.samestat(identity, path.lstat()):
            raise PermissionError("temporary requirements file changed identity")
        return path, identity
    except BaseException:
        if fd >= 0:
            os.close(fd)
        try:
            remove_file_without_links(
                path,
                missing_ok=True,
                expected_identity=identity,
            )
        except (OSError, ValueError):
            pass
        raise


def _finish_install_result(
    result: tuple[str, str],
    pip_target: Path | None,
    *,
    root: str | Path | None = None,
) -> tuple[str, str]:
    if result[0] == "pip_ok" and pip_target is not None:
        if root is None:
            ensure_plugin_site_packages_on_syspath()
        else:
            ensure_plugin_site_packages_on_syspath(root=root)
    return result


def install_plugin_requirements_txt(
    plugin_root: Path,
    *,
    requirements_file: str = "requirements.txt",
    timeout_sec: float = 900.0,
    on_output_line: Callable[[str], None] | None = None,
    root: str | Path | None = None,
) -> tuple[str, str]:
    """
    Run ``python -m pip install -r requirements_file`` if it exists under ``plugin_root``.

    冻结版使用 :func:`pip_python_executable`（默认 ``<安装根>/runtime/python.exe``）执行
    普通依赖使用 ``pip install --target <项目数据根>/data/plugin_site_packages``；PyTorch
    二进制栈是例外，会统一安装进 bundled runtime，避免两套 ``torch`` 同时出现在
    ``sys.path``。宿主须在启动时调用 :func:`ensure_plugin_site_packages_on_syspath`。

    On Windows/Linux, if the file lists ``torch``, ``torchvision``, or ``torchaudio``, those lines are
    installed first from PyTorch's wheel index (CUDA channel derived from ``nvidia-smi``, otherwise CPU).
    macOS keeps a single ``pip install -r`` so PyPI/MPS layouts stay unchanged.

    Returns ``(code, detail)`` where ``code`` is one of:

    - ``pip_ok`` — successful install (or pip reported nothing to do).
    - ``pip_skip_no_requirements`` — no ``requirements.txt``.
    - ``pip_failed`` — non-zero exit.
    - ``pip_conflict`` — non-zero exit caused by a dependency resolution conflict.
    - ``pip_timeout`` — killed after ``timeout_sec``.
    - ``pip_exception`` — could not start subprocess (missing ``runtime/python.exe`` or pip).

    ``detail`` holds a short stderr tail or exception message for failures; empty otherwise.

    If ``on_output_line`` is set, stdout/stderr lines are forwarded (stripped of trailing newline)
    as pip runs, for UI logs.
    """
    raw_root = validate_exact_path_text(plugin_root, field="plugin root")
    unresolved_root = Path(raw_root).expanduser()
    if (
        unresolved_root.is_absolute()
        and path_is_link_or_reparse_point(unresolved_root)
    ):
        raise PermissionError("plugin root must not be a symbolic link")
    active_project_root = (
        project_root()
        if root is None
        else resolve_project_path(".", root=root)
    )
    plugin_directory = resolve_project_read_path(
        raw_root,
        root=active_project_root,
    )
    if not plugin_directory.is_dir():
        return ("pip_skip_no_requirements", "")
    req = managed_child_path(
        plugin_directory,
        requirements_file,
        field="requirements filename",
    )
    if not req.is_file():
        return ("pip_skip_no_requirements", "")

    py = pip_python_executable()
    if getattr(sys, "frozen", False) and py == Path(sys.executable).resolve():
        logger.warning(
            "Frozen app: runtime/python.exe not found under release root; "
            "pip install may fail (use <release>/runtime/python.exe).",
        )

    pip_target = (
        plugin_pip_target_directory()
        if root is None
        else plugin_pip_target_directory(root=active_project_root)
    )
    base_cmd = _pip_base_install_cmd(py, pip_target)

    started = time.monotonic()

    def remaining_budget() -> float:
        return max(30.0, timeout_sec - (time.monotonic() - started))

    try:
        lines = read_text_without_links(req).splitlines()
    except OSError as exc:
        logger.warning("Could not read %s: %s", req, exc)
        return ("pip_exception", str(exc))

    # PyTorch 栈始终单独检查。普通包仍只把“缺失或版本不满足”的行交给 pip；
    # PyTorch 还会核对 CPU/CUDA wheel 标签，不能被普通的 ``>=`` 预检提前裁掉。
    torch_lines, source_other_lines = _partition_torch_requirement_lines(lines)
    split_torch = bool(torch_lines) and sys.platform != "darwin"
    precheck_source_lines = source_other_lines if split_torch else lines
    can_prune, install_lines = (
        _install_lines_after_precheck(precheck_source_lines)
        if root is None
        else _install_lines_after_precheck(
            precheck_source_lines,
            root=active_project_root,
        )
    )
    if can_prune and not install_lines and not split_torch:
        logger.info("Plugin pip: all requirements already satisfied, skipping install.")
        return ("pip_ok", "")

    active_req = req
    active_lines = lines
    precheck_tf: Path | None = None
    precheck_identity: os.stat_result | None = None
    torch_tf: Path | None = None
    torch_identity: os.stat_result | None = None
    other_tf: Path | None = None
    other_identity: os.stat_result | None = None
    try:
        if can_prune:
            # pip 仍然只认识 requirements 文件；在 finally 生效后再写临时文件，
            # 确保写入成功后任何后续异常都会清理掉它。
            precheck_tf, precheck_identity = _write_temp_requirements(
                "easyai_missing_req_",
                install_lines,
            )
            active_req = precheck_tf
            active_lines = install_lines

        if split_torch:
            # torch/torchvision/torchaudio 不走普通 PyPI 镜像，也不装进插件
            # --target：整套二进制运行时必须由 bundled/runtime Python 统一持有。
            installed_versions = _installed_distribution_versions()
            plan = _build_pytorch_install_plan(
                torch_lines,
                installed_versions,
                requirement_is_satisfied=_requirement_line_is_satisfied,
            )
            logger.info(
                "Plugin pip: PyTorch plan index=%s (%s), install=%s, "
                "force_reinstall=%s: %s",
                plan.index_url,
                plan.index_reason,
                plan.install_required,
                plan.force_reinstall,
                plan.detail,
            )
            managed_torch_lines = list(plan.requirement_lines)
            if managed_torch_lines:
                torch_tf, torch_identity = _write_temp_requirements(
                    "easyai_torch_req_",
                    managed_torch_lines,
                )
            if plan.install_required:
                if torch_tf is None:
                    return ("pip_exception", "host PyTorch requirements are unavailable")
                # Intentionally omit plugin ``--target`` for the PyTorch stack.
                cmd_torch = [
                    *_pip_base_install_cmd(py, None),
                    "--index-url",
                    plan.index_url,
                    "--extra-index-url",
                    "https://pypi.org/simple",
                ]
                if plan.force_reinstall:
                    # ``--force-reinstall`` also applies to resolved transitive
                    # dependencies unless dependency resolution is disabled.
                    # Replace only the requested PyTorch binary stack first;
                    # the follow-up plain install repairs missing dependencies
                    # without forcing already-satisfied packages to reinstall.
                    cmd_torch.extend(["--upgrade", "--force-reinstall", "--no-deps"])
                cmd_torch.extend(["-r", str(torch_tf)])
                code1, detail1 = _run_pip_install(
                    _apply_pip_index_and_extra_args(cmd_torch, managed_torch_lines),
                    cwd=active_project_root,
                    timeout_sec=remaining_budget(),
                    on_output_line=on_output_line,
                )
                if code1 != "pip_ok":
                    return (code1, detail1)
                if plan.force_reinstall:
                    cmd_torch_deps = [
                        *_pip_base_install_cmd(py, None),
                        "--index-url",
                        plan.index_url,
                        "--extra-index-url",
                        "https://pypi.org/simple",
                        "-r",
                        str(torch_tf),
                    ]
                    code2, detail2 = _run_pip_install(
                        _apply_pip_index_and_extra_args(
                            cmd_torch_deps,
                            managed_torch_lines,
                        ),
                        cwd=active_project_root,
                        timeout_sec=remaining_budget(),
                        on_output_line=on_output_line,
                    )
                    if code2 != "pip_ok":
                        return (code2, detail2)

            other_lines = install_lines if can_prune else source_other_lines
            if not _has_non_comment_requirement(other_lines):
                return _finish_install_result(
                    ("pip_ok", ""),
                    pip_target,
                    root=(active_project_root if root is not None else None),
                )

            other_tf, other_identity = _write_temp_requirements(
                "easyai_other_req_",
                other_lines,
            )

            # Keep PyTorch-enabled plugins in the bundled runtime environment.
            # pip's ``--target`` resolver ignores distributions already
            # installed in the runtime and would otherwise download a second
            # transitive torch for packages such as accelerate. The host stack
            # also acts as a constraint so incompatible transitive requirements
            # fail clearly instead of silently replacing it.
            cmd_other_base = _pip_base_install_cmd(py, None)
            if torch_tf is not None:
                cmd_other_base.extend(["-c", str(torch_tf)])
            cmd_other = _apply_pip_index_and_extra_args(
                [*cmd_other_base, "-r", str(other_tf)],
                other_lines,
            )
            return _finish_install_result(
                _run_pip_install(
                    cmd_other,
                    cwd=plugin_directory,
                    timeout_sec=remaining_budget(),
                    on_output_line=on_output_line,
                ),
                None,
            )

        cmd = _apply_pip_index_and_extra_args(
            [*base_cmd, "-r", str(active_req)],
            active_lines,
        )
        return _finish_install_result(
            _run_pip_install(
                cmd,
                cwd=plugin_directory,
                timeout_sec=timeout_sec,
                on_output_line=on_output_line,
            ),
            pip_target,
            root=(active_project_root if root is not None else None),
        )
    finally:
        for path, identity in (
            (precheck_tf, precheck_identity),
            (torch_tf, torch_identity),
            (other_tf, other_identity),
        ):
            if path is not None and identity is not None:
                try:
                    remove_file_without_links(
                        path,
                        missing_ok=True,
                        expected_identity=identity,
                    )
                except (OSError, ValueError):
                    pass
