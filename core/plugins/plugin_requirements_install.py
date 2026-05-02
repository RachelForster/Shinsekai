"""Install plugin-local ``requirements.txt`` using the host or embeddable Python."""

from __future__ import annotations

from collections.abc import Callable
from typing import IO

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_PIP_DETAIL_MAX = 1600


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


def install_plugin_requirements_txt(
    plugin_root: Path,
    *,
    timeout_sec: float = 900.0,
    on_output_line: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """
    Run ``python -m pip install -r requirements.txt`` if ``plugin_root/requirements.txt`` exists.

    冻结版使用 :func:`pip_python_executable`（默认 ``<发行根>/runtime/python.exe``）执行
    ``pip install --target <发行根>/data/plugin_site_packages``；宿主须在启动时调用
    :func:`ensure_plugin_site_packages_on_syspath`。

    Returns ``(code, detail)`` where ``code`` is one of:

    - ``pip_ok`` — successful install (or pip reported nothing to do).
    - ``pip_skip_no_requirements`` — no ``requirements.txt``.
    - ``pip_failed`` — non-zero exit.
    - ``pip_timeout`` — killed after ``timeout_sec``.
    - ``pip_exception`` — could not start subprocess (missing ``runtime/python.exe`` or pip).

    ``detail`` holds a short stderr tail or exception message for failures; empty otherwise.

    If ``on_output_line`` is set, stdout/stderr lines are forwarded (stripped of trailing newline)
    as pip runs, for UI logs.
    """
    root = plugin_root.resolve()
    req = root / "requirements.txt"
    if not req.is_file():
        return ("pip_skip_no_requirements", "")

    py = pip_python_executable()
    if getattr(sys, "frozen", False) and py == Path(sys.executable).resolve():
        logger.warning(
            "Frozen app: runtime/python.exe not found under release root; "
            "pip install may fail (use <release>/runtime/python.exe).",
        )
    cmd: list[str] = [
        str(py),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
    ]
    pip_target = plugin_pip_target_directory()
    if pip_target is not None:
        pip_target.mkdir(parents=True, exist_ok=True)
        cmd.extend(
            [
                "--target",
                str(pip_target.resolve()),
                "--no-warn-script-location",
            ]
        )
    cmd.extend(["-r", str(req)])
    pop_kw: dict[str, object] = {
        "cwd": str(root),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "env": _pip_subprocess_env(),
    }
    if sys.platform == "win32":
        cr = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if cr:
            pop_kw["creationflags"] = cr

    try:
        proc = subprocess.Popen(cmd, **pop_kw)
    except OSError as exc:
        logger.warning("pip install could not run for %s: %s", req, exc)
        return ("pip_exception", str(exc))

    combined_chunks: list[str] = []
    lock = threading.Lock()

    def relay(stream: IO[str] | None) -> None:
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                with lock:
                    combined_chunks.append(line)
                if on_output_line:
                    on_output_line(line.rstrip("\r\n"))
        finally:
            stream.close()

    t_out = threading.Thread(target=relay, args=(proc.stdout,))
    t_err = threading.Thread(target=relay, args=(proc.stderr,))
    t_out.daemon = True
    t_err.daemon = True
    t_out.start()
    t_err.start()

    try:
        proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        t_out.join(timeout=3.0)
        t_err.join(timeout=3.0)
        combined = "".join(combined_chunks)
        tail = combined.strip()[-_PIP_DETAIL_MAX:]
        logger.warning("pip install timed out for %s", req)
        return ("pip_timeout", tail or "pip install timed out")

    t_out.join()
    t_err.join()

    combined = "".join(combined_chunks).strip()
    if proc.returncode == 0:
        logger.info("pip install ok for %s", req)
        return ("pip_ok", "")

    tail = combined[-_PIP_DETAIL_MAX:] if combined else ""
    logger.warning("pip install failed for %s (exit %s)", req, proc.returncode)
    return ("pip_failed", tail or f"exit {proc.returncode}")


def _pip_subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PYTHONUTF8", "1")
    return env
