"""Shared pip subprocess helpers for plugin and runtime dependency installs."""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import IO

from core.plugins.pip_index_config import (
    has_explicit_pip_index as _has_explicit_pip_index,
    pip_index_args as _pip_index_args,
    requirements_lines_define_index as _requirements_lines_define_index,
)

logger = logging.getLogger(__name__)

_PIP_DETAIL_MAX = 1600
_PIP_CONFLICT_RE = re.compile(
    r"\b(conflict(?:ing)? dependencies|resolutionimpossible|cannot install|dependency conflict)\b",
    re.IGNORECASE,
)
_URL_CREDENTIAL_RE = re.compile(
    r"(?P<scheme>https?://)(?P<user>[^:/\s@]+)(?::(?P<password>[^@\s/]+))?@"
)


def redact_url_credentials(text: str) -> str:
    def _mask(match: re.Match[str]) -> str:
        if match.group("password") is None:
            # 只有用户名的形式（https://<token>@host）里用户名往往就是凭据本体。
            return f"{match.group('scheme')}***@"
        return f"{match.group('scheme')}{match.group('user')}:***@"

    return _URL_CREDENTIAL_RE.sub(_mask, text or "")


def pip_win_creationflags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def pip_subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def extra_pip_install_args() -> list[str]:
    raw = os.environ.get("SHINSEKAI_PIP_INSTALL_ARGS", "").strip()
    if not raw:
        return []
    return shlex.split(raw)


def apply_pip_index_and_extra_args(
    cmd: list[str],
    requirement_lines: list[str] | None = None,
    *,
    primary_flag: str = "--index-url",
) -> list[str]:
    final_cmd = list(cmd)
    extra_args = extra_pip_install_args()
    index_args = _pip_index_args(primary_flag=primary_flag)
    if (
        index_args
        and not _has_explicit_pip_index(final_cmd)
        and not _requirements_lines_define_index(requirement_lines or [])
        and not _has_explicit_pip_index(extra_args)
    ):
        final_cmd.extend(index_args)
    final_cmd.extend(extra_args)
    return final_cmd


def classify_pip_result(result: tuple[str, str]) -> tuple[str, str]:
    # 依赖求解冲突单独分类，前端可以提示“版本冲突”，而不是笼统显示 pip failed。
    code, detail = result
    if code == "pip_failed" and _PIP_CONFLICT_RE.search(detail or ""):
        return ("pip_conflict", detail)
    return result


def run_pip_install(
    cmd: list[str],
    *,
    cwd: Path,
    timeout_sec: float,
    on_output_line: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    """
    Run one pip subprocess and return ``(code, detail)``.

    ``code`` is one of ``pip_ok`` / ``pip_failed`` / ``pip_conflict`` /
    ``pip_timeout`` / ``pip_exception``; ``detail`` holds a short, already
    credential-redacted output tail for failures (empty on success). Lines
    forwarded to ``on_output_line`` are redacted the same way.
    """
    pop_kw: dict[str, object] = {
        "cwd": str(cwd),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "env": pip_subprocess_env(),
    }
    flags = pip_win_creationflags()
    if sys.platform == "win32" and flags:
        pop_kw["creationflags"] = flags
    try:
        proc = subprocess.Popen(cmd, **pop_kw)
    except OSError as exc:
        logger.warning("pip install could not run (cmd=%s): %s", cmd[:8], exc)
        return ("pip_exception", str(exc))

    combined_chunks: list[str] = []
    lock = threading.Lock()

    def relay(stream: IO[str] | None) -> None:
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                # 私有源 URL 可能带账号密码，先脱敏再进 UI 日志与错误详情。
                line = redact_url_credentials(line)
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
        logger.warning("pip install timed out (timeout_sec=%s)", timeout_sec)
        return ("pip_timeout", tail or "pip install timed out")

    t_out.join()
    t_err.join()
    combined = "".join(combined_chunks).strip()
    if proc.returncode == 0:
        logger.info("pip install ok")
        return ("pip_ok", "")
    tail = combined[-_PIP_DETAIL_MAX:] if combined else ""
    logger.warning("pip install failed (exit %s)", proc.returncode)
    return classify_pip_result(("pip_failed", tail or f"exit {proc.returncode}"))
