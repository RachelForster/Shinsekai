"""Install plugin-local ``requirements.txt`` using the host or embeddable Python."""

from __future__ import annotations

from collections.abc import Callable

import importlib.metadata as importlib_metadata
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from core.plugins.pip_index_config import (
    strip_inline_requirement_comment as _strip_inline_requirement_comment,
)
from core.plugins.pip_runner import (
    apply_pip_index_and_extra_args as _apply_pip_index_and_extra_args,
    pip_win_creationflags as _pip_win_creationflags,
    run_pip_install as _run_pip_install,
)

try:
    from packaging.requirements import InvalidRequirement, Requirement
except Exception:  # pragma: no cover - fallback for minimal embedded runtimes.
    InvalidRequirement = ValueError  # type: ignore[assignment]
    Requirement = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_TORCH_PROJECT_NAMES = frozenset({"torch", "torchvision", "torchaudio"})
_CUDA_VER_LINE_RE = re.compile(r"CUDA Version:\s*(\d+)\.(\d+)")


def frozen_release_root() -> Path | None:
    """打包运行时返回发行根目录；开发模式返回 ``None``。"""
    if not getattr(sys, "frozen", False):
        return None
    er = os.environ.get("EASYAI_PROJECT_ROOT")
    if er:
        return Path(er).resolve()
    return Path(sys.executable).resolve().parent.parent


def pip_python_executable() -> Path:
    """
    用于 ``python -m pip`` 的解释器路径。

    冻结版：优先 ``<发行根>/runtime/python.exe``（或 ``python3.exe``），便于使用嵌入 Python；
    否则回退 ``sys.executable``（主程序 exe，通常无法运行 pip）。
    """
    if getattr(sys, "frozen", False):
        root = frozen_release_root()
        if root is not None:
            runtime = root / "runtime"
            for name in ("python.exe", "python3.exe"):
                p = runtime / name
                if p.is_file():
                    return p.resolve()
    return Path(sys.executable).resolve()


def plugin_pip_target_directory() -> Path | None:
    """
    冻结版：pip ``--target`` 的可写目录（与 ``webui_qt`` / ``main`` 所设发行根一致）。
    开发模式返回 ``None``（依赖装入当前环境 site-packages，不使用 ``--target``）。
    """
    root = frozen_release_root()
    if root is None:
        return None
    return root / "data" / "plugin_site_packages"


def ensure_plugin_site_packages_on_syspath() -> None:
    """若存在冻结版插件依赖目录，则插入 ``sys.path`` 首位（须在加载插件前调用）。"""
    target = plugin_pip_target_directory()
    if target is None:
        return
    if not target.is_dir():
        return
    s = str(target.resolve())
    if s not in sys.path:
        sys.path.insert(0, s)
        logger.info("Prepended plugin site-packages to sys.path: %s", s)


def ensure_plugins_namespace_on_syspath() -> None:
    """
    将「含有 ``plugins/`` 子目录的一层级目录」置于 ``sys.path`` 首位，使 ``import plugins.xxx`` 可解析。

    源码运行时常已由入口脚本把项目根加入 ``sys.path``；冻结版仅有 ``_internal`` 等路径时，
    必须加入发行根（与 ``main`` / ``SettingsUI`` 同层的目录，内含用户可写的 ``plugins/``）。
    """
    if getattr(sys, "frozen", False):
        root = frozen_release_root()
        if root is None:
            return
        plug = root / "plugins"
        if not plug.is_dir():
            logger.debug("Frozen: no plugins directory at %s, skip release root on sys.path", plug)
            return
        s = str(root.resolve())
        if s not in sys.path:
            sys.path.insert(0, s)
            logger.info("Prepended release root for plugins namespace: %s", s)
        return
    cwd = Path.cwd().resolve()
    if (cwd / "plugins").is_dir():
        s = str(cwd)
        if s not in sys.path:
            sys.path.insert(0, s)
            logger.info("Prepended cwd for plugins namespace: %s", s)


def _nvidia_smi_cuda_driver_version() -> tuple[int, int] | None:
    """Parse ``CUDA Version: major.minor`` from ``nvidia-smi`` stdout; None if unavailable."""
    pop_kw: dict[str, object] = {
        "args": ["nvidia-smi"],
        "capture_output": True,
        "text": True,
        "timeout": 20,
    }
    if sys.platform == "win32":
        flags = _pip_win_creationflags()
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


def _pytorch_wheel_index_url_for_this_machine() -> tuple[str, str]:
    """
    Choose ``pip install --index-url`` for PyTorch official wheels (CUDA vs CPU).

    Only used on Windows/Linux after splitting ``torch`` / ``torchvision`` / ``torchaudio`` lines out
    of a plugin ``requirements.txt``.
    """
    ver = _nvidia_smi_cuda_driver_version()
    if ver is None:
        return "https://download.pytorch.org/whl/cpu", "no_usable_nvidia_smi_cpu"
    major, minor = ver
    if (major, minor) >= (12, 4):
        tag = "cu124"
    elif major >= 12:
        tag = "cu121"
    elif (major, minor) >= (11, 8):
        tag = "cu118"
    else:
        tag = "cu118"
    url = f"https://download.pytorch.org/whl/{tag}"
    return url, f"nvidia_driver_cuda_{major}.{minor}_{tag}"


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


def _partition_torch_requirement_lines(lines: list[str]) -> tuple[list[str], list[str]]:
    torch_only: list[str] = []
    rest: list[str] = []
    for line in lines:
        name = _requirement_line_project_name(line)
        if name is not None and name in _TORCH_PROJECT_NAMES:
            torch_only.append(line.rstrip("\r\n"))
        else:
            rest.append(line.rstrip("\r\n"))
    return torch_only, rest


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
        cmd.extend(
            [
                "--target",
                str(pip_target.resolve()),
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


def _requirement_distribution_version(name: str) -> str | None:
    canonical = _canonical_distribution_name(name)
    paths = list(sys.path)
    target = plugin_pip_target_directory()
    if target is not None and target.is_dir():
        # 打包版插件依赖会装进 data/plugin_site_packages，先查这里再看系统路径。
        target_s = str(target.resolve())
        paths = [target_s, *[path for path in paths if path != target_s]]
    for distribution in importlib_metadata.distributions(path=paths):
        dist_name = distribution.metadata.get("Name")
        if not dist_name:
            continue
        if _canonical_distribution_name(dist_name) == canonical:
            return distribution.version
    return None


def _requirement_line_is_satisfied(line: str) -> bool:
    # 这里尽量按 PEP 508 判断：marker 不匹配就视为无需安装，版本不满足才进入 pip。
    stripped = _strip_inline_requirement_comment(line)
    if not stripped:
        return True
    if Requirement is None:
        name = _requirement_line_project_name(stripped)
        return bool(name and _requirement_distribution_version(name) is not None)
    try:
        requirement = Requirement(stripped)
    except InvalidRequirement:
        name = _requirement_line_project_name(stripped)
        return bool(name and _requirement_distribution_version(name) is not None)
    if requirement.marker and not requirement.marker.evaluate():
        return True
    installed_version = _requirement_distribution_version(requirement.name)
    if installed_version is None:
        return False
    if requirement.specifier:
        return requirement.specifier.contains(installed_version, prereleases=True)
    return True


def _install_lines_after_precheck(lines: list[str]) -> tuple[bool, list[str]]:
    # requirements 里出现 -e、--find-links、direct reference 等全局/本地语义时，不做裁剪。
    # 这些行可能影响后续包解析，强行只装“缺失行”反而会破坏作者的安装意图。
    if not all(_requirement_line_can_be_pruned(line) for line in lines):
        return False, lines
    install_lines: list[str] = []
    for line in lines:
        stripped = _strip_inline_requirement_comment(line)
        if not stripped:
            continue
        if not _requirement_line_is_satisfied(stripped):
            install_lines.append(line.rstrip("\r\n"))
    return True, install_lines


def _finish_install_result(
    result: tuple[str, str],
    pip_target: Path | None,
) -> tuple[str, str]:
    if result[0] == "pip_ok" and pip_target is not None:
        ensure_plugin_site_packages_on_syspath()
    return result


def install_plugin_requirements_txt(
    plugin_root: Path,
    *,
    requirements_file: str = "requirements.txt",
    timeout_sec: float = 900.0,
    on_output_line: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """
    Run ``python -m pip install -r requirements_file`` if it exists under ``plugin_root``.

    冻结版使用 :func:`pip_python_executable`（默认 ``<发行根>/runtime/python.exe``）执行
    ``pip install --target <发行根>/data/plugin_site_packages``；宿主须在启动时调用
    :func:`ensure_plugin_site_packages_on_syspath`。

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
    root = plugin_root.resolve()
    req = root / requirements_file
    if not req.is_file():
        return ("pip_skip_no_requirements", "")

    py = pip_python_executable()
    if getattr(sys, "frozen", False) and py == Path(sys.executable).resolve():
        logger.warning(
            "Frozen app: runtime/python.exe not found under release root; "
            "pip install may fail (use <release>/runtime/python.exe).",
        )

    pip_target = plugin_pip_target_directory()
    base_cmd = _pip_base_install_cmd(py, pip_target)

    started = time.monotonic()

    def remaining_budget() -> float:
        return max(30.0, timeout_sec - (time.monotonic() - started))

    try:
        lines = req.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("Could not read %s: %s", req, exc)
        return ("pip_exception", str(exc))

    # 先在本地分发信息里做预检，普通包只把“缺失或版本不满足”的行交给 pip。
    # 这样已安装依赖不会反复下载，国内用户装插件时能少等很多。
    can_prune, install_lines = _install_lines_after_precheck(lines)
    if can_prune and not install_lines:
        logger.info("Plugin pip: all requirements already satisfied, skipping install.")
        return ("pip_ok", "")

    active_req = req
    active_lines = lines
    precheck_tf: Path | None = None
    if can_prune:
        # pip 仍然只认识 requirements 文件，所以把裁剪后的缺失列表写入临时文件。
        fd, precheck_tf_str = tempfile.mkstemp(
            prefix="easyai_missing_req_", suffix=".txt"
        )
        os.close(fd)
        precheck_tf = Path(precheck_tf_str)
        precheck_tf.write_text("\n".join(install_lines) + "\n", encoding="utf-8")
        active_req = precheck_tf
        active_lines = install_lines

    torch_lines, other_lines = _partition_torch_requirement_lines(active_lines)
    split_torch = bool(torch_lines) and sys.platform != "darwin"

    torch_tf: Path | None = None
    other_tf: Path | None = None
    try:
        if split_torch:
            # torch/torchvision/torchaudio 不走普通 PyPI 镜像。
            # 这里先按本机 CUDA/CPU 选择 PyTorch 官方 wheel index，再安装剩余依赖。
            idx_url, idx_reason = _pytorch_wheel_index_url_for_this_machine()
            logger.info(
                "Plugin pip: PyTorch packages use index %s (%s)",
                idx_url,
                idx_reason,
            )
            fd_t, torch_tf_str = tempfile.mkstemp(
                prefix="easyai_torch_req_", suffix=".txt"
            )
            os.close(fd_t)
            torch_tf = Path(torch_tf_str)
            torch_tf.write_text("\n".join(torch_lines) + "\n", encoding="utf-8")

            cmd_torch = [
                *base_cmd,
                "--index-url",
                idx_url,
                "--extra-index-url",
                "https://pypi.org/simple",
                "-r",
                str(torch_tf),
            ]
            code1, detail1 = _finish_install_result(
                _run_pip_install(
                    _apply_pip_index_and_extra_args(cmd_torch, torch_lines),
                    cwd=root,
                    timeout_sec=remaining_budget(),
                    on_output_line=on_output_line,
                ),
                pip_target,
            )
            if code1 != "pip_ok":
                return (code1, detail1)

            if not _has_non_comment_requirement(other_lines):
                return _finish_install_result(("pip_ok", ""), pip_target)

            fd_o, other_tf_str = tempfile.mkstemp(
                prefix="easyai_other_req_", suffix=".txt"
            )
            os.close(fd_o)
            other_tf = Path(other_tf_str)
            other_tf.write_text("\n".join(other_lines) + "\n", encoding="utf-8")

            cmd_other = _apply_pip_index_and_extra_args(
                [*base_cmd, "-r", str(other_tf)],
                other_lines,
            )
            return _finish_install_result(
                _run_pip_install(
                    cmd_other,
                    cwd=root,
                    timeout_sec=remaining_budget(),
                    on_output_line=on_output_line,
                ),
                pip_target,
            )

        cmd = _apply_pip_index_and_extra_args(
            [*base_cmd, "-r", str(active_req)],
            active_lines,
        )
        return _finish_install_result(
            _run_pip_install(
                cmd,
                cwd=root,
                timeout_sec=timeout_sec,
                on_output_line=on_output_line,
            ),
            pip_target,
        )
    finally:
        for path in (precheck_tf, torch_tf, other_tf):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
