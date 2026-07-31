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
from urllib.parse import urlparse

from sdk.file_transactions import read_text_without_links
from sdk.path_contract import (
    require_symlink_free_absolute_path,
    resolve_project_read_path,
    validate_exact_path_text,
)
from sdk.process_launch import (
    LaunchDirectorySnapshot,
    LaunchFileSnapshot,
    capture_launch_directory,
    capture_launch_file,
    isolated_python_environment,
    popen_with_stable_paths,
    require_launch_snapshots,
)
from core.runtime_env.pip_index import (
    has_explicit_pip_index as _has_explicit_pip_index,
    pip_index_args as _pip_index_args,
    requirements_lines_define_index as _requirements_lines_define_index,
    strip_inline_requirement_comment as _strip_inline_requirement_comment,
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
_PIP_INPUT_FILE_FLAGS = frozenset(
    {"-r", "--requirement", "-c", "--constraint"}
)
_PIP_INPUT_FILE_PREFIXES = ("--requirement=", "--constraint=")
_MAX_PIP_INPUT_FILES = 256
_PIP_ENVIRONMENT_FILE_PATHS = (
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "PIP_CERT",
    "PIP_CLIENT_CERT",
    "PIP_CONFIG_FILE",
    "PIP_REQUIREMENT",
    "PIP_CONSTRAINT",
)
_PIP_ENVIRONMENT_OUTPUT_PATHS = (
    "PIP_CACHE_DIR",
    "PIP_SRC",
    "PIP_TARGET",
    "PIP_PREFIX",
    "PIP_ROOT",
    "PIP_BUILD_TRACKER",
    "PIP_LOG",
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
    env = isolated_python_environment()
    env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _capture_environment_file_alias(
    value: str,
    *,
    field: str,
) -> LaunchFileSnapshot:
    raw = validate_exact_path_text(value, field=field)
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise ValueError(
            f"{field} must be absolute and must not depend on the pip working directory"
        )
    canonical = candidate.resolve(strict=True)
    snapshot = capture_launch_file(canonical, field=field)
    verification = candidate.resolve(strict=True)
    if verification != snapshot.path:
        raise PermissionError(f"{field} alias changed while it was resolved")
    return snapshot


def _capture_pip_environment_paths(
    env: dict[str, str],
) -> tuple[
    tuple[LaunchFileSnapshot, ...],
    tuple[LaunchDirectorySnapshot, ...],
]:
    files: list[LaunchFileSnapshot] = []
    directories: list[LaunchDirectorySnapshot] = []
    for name in _PIP_ENVIRONMENT_FILE_PATHS:
        if name not in env:
            continue
        value = env[name]
        if name == "PIP_CONFIG_FILE" and os.path.normcase(value) == os.path.normcase(
            os.devnull
        ):
            env[name] = os.devnull
            continue
        snapshot = _capture_environment_file_alias(
            value,
            field=f"{name} environment file",
        )
        env[name] = os.fspath(snapshot.path)
        files.append(snapshot)

    if "SSL_CERT_DIR" in env:
        raw = validate_exact_path_text(
            env["SSL_CERT_DIR"],
            field="SSL_CERT_DIR environment directory",
        )
        candidate = Path(raw)
        if not candidate.is_absolute():
            raise ValueError(
                "SSL_CERT_DIR must be absolute and must not depend on the pip working directory"
            )
        canonical = candidate.resolve(strict=True)
        snapshot = capture_launch_directory(
            canonical,
            field="SSL_CERT_DIR environment directory",
        )
        if candidate.resolve(strict=True) != snapshot.path:
            raise PermissionError(
                "SSL_CERT_DIR environment directory alias changed while it was resolved"
            )
        env["SSL_CERT_DIR"] = os.fspath(snapshot.path)
        directories.append(snapshot)

    for name in _PIP_ENVIRONMENT_OUTPUT_PATHS:
        if name not in env:
            continue
        path = require_symlink_free_absolute_path(
            env[name],
            field=f"{name} environment path",
            include_leaf=False,
        )
        env[name] = os.fspath(path)
    return tuple(files), tuple(directories)


def extra_pip_install_args() -> list[str]:
    raw = os.environ.get("SHINSEKAI_PIP_INSTALL_ARGS", "").strip()
    if not raw:
        return []
    try:
        return shlex.split(raw)
    except ValueError as exc:
        logger.warning("Ignoring invalid SHINSEKAI_PIP_INSTALL_ARGS: %s", exc)
        return []


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


def _pip_input_file_references(tokens: list[str]) -> list[str]:
    references: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _PIP_INPUT_FILE_FLAGS:
            if index + 1 < len(tokens):
                references.append(tokens[index + 1])
                index += 2
                continue
        matched_prefix = next(
            (
                prefix
                for prefix in _PIP_INPUT_FILE_PREFIXES
                if token.startswith(prefix)
            ),
            None,
        )
        if matched_prefix is not None:
            references.append(token[len(matched_prefix) :])
        elif token.startswith(("-r", "-c")) and token not in {"-r", "-c"}:
            references.append(token[2:])
        index += 1
    return [reference for reference in references if reference]


def _capture_pip_input_files(
    command: list[str],
    *,
    cwd: Path,
) -> tuple[LaunchFileSnapshot, ...]:
    snapshots: list[LaunchFileSnapshot] = []
    seen: set[str] = set()

    def capture(raw: str, base: Path) -> None:
        parsed = urlparse(raw)
        if parsed.scheme.lower() in {"http", "https"}:
            # pip itself owns the identity and transport semantics of remote
            # requirements.  Only local path inputs can be bound to a host
            # filesystem snapshot here.
            return
        if parsed.scheme:
            raise ValueError(
                f"unsupported pip requirements input URI scheme: {parsed.scheme}"
            )
        path = resolve_project_read_path(raw, root=base)
        key = os.path.normcase(os.path.normpath(os.fspath(path)))
        if key in seen:
            return
        if len(snapshots) >= _MAX_PIP_INPUT_FILES:
            raise ValueError("pip requirements include too many nested input files")
        snapshot = capture_launch_file(
            path,
            field="pip requirements input",
        )
        seen.add(key)
        snapshots.append(snapshot)
        text = read_text_without_links(
            snapshot.path,
            expected_identity=snapshot.identity,
            expected_parent_identity=snapshot.parent.identity,
        )
        for raw_line in text.splitlines():
            line = _strip_inline_requirement_comment(raw_line)
            if not line:
                continue
            try:
                tokens = shlex.split(line)
            except ValueError:
                continue
            for nested in _pip_input_file_references(tokens):
                capture(nested, snapshot.path.parent)

    for reference in _pip_input_file_references(command[1:]):
        capture(reference, cwd)
    return tuple(snapshots)


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
    detail_max: int = _PIP_DETAIL_MAX,
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
    try:
        if not cmd:
            raise ValueError("pip command is empty")
        executable_snapshot = capture_launch_file(
            cmd[0],
            field="pip Python executable",
            executable=True,
        )
        working_directory_snapshot = capture_launch_directory(
            cwd,
            field="pip working directory",
        )
        safe_cmd = [str(executable_snapshot.path), *cmd[1:]]
        input_file_snapshots = _capture_pip_input_files(
            safe_cmd,
            cwd=working_directory_snapshot.path,
        )
        child_env = pip_subprocess_env()
        environment_file_snapshots, environment_directory_snapshots = (
            _capture_pip_environment_paths(child_env)
        )
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("pip install path validation failed: %s", exc)
        return ("pip_exception", str(exc))

    pop_kw: dict[str, object] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "env": child_env,
    }
    flags = pip_win_creationflags()
    if sys.platform == "win32" and flags:
        pop_kw["creationflags"] = flags
    try:
        proc = popen_with_stable_paths(
            safe_cmd,
            cwd=working_directory_snapshot,
            executable=executable_snapshot,
            required_directories=environment_directory_snapshots,
            required_files=(
                *input_file_snapshots,
                *environment_file_snapshots,
            ),
            popen_factory=subprocess.Popen,
            **pop_kw,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        logger.warning("pip install could not run (cmd=%s): %s", safe_cmd[:8], exc)
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
        try:
            require_launch_snapshots(
                directories=(
                    working_directory_snapshot,
                    *environment_directory_snapshots,
                ),
                files=(
                    executable_snapshot,
                    *input_file_snapshots,
                    *environment_file_snapshots,
                ),
            )
        except (OSError, PermissionError, ValueError) as exc:
            logger.warning("pip install paths changed during timeout handling: %s", exc)
            return ("pip_exception", str(exc))
        combined = "".join(combined_chunks)
        tail = combined.strip()[-max(1, detail_max):]
        logger.warning("pip install timed out (timeout_sec=%s)", timeout_sec)
        return ("pip_timeout", tail or "pip install timed out")

    t_out.join()
    t_err.join()
    try:
        require_launch_snapshots(
            directories=(
                working_directory_snapshot,
                *environment_directory_snapshots,
            ),
            files=(
                executable_snapshot,
                *input_file_snapshots,
                *environment_file_snapshots,
            ),
        )
    except (OSError, PermissionError, ValueError) as exc:
        logger.warning("pip install paths changed while pip was running: %s", exc)
        return ("pip_exception", str(exc))
    combined = "".join(combined_chunks).strip()
    if proc.returncode == 0:
        logger.info("pip install ok")
        return ("pip_ok", "")
    tail = combined[-max(1, detail_max):] if combined else ""
    logger.warning("pip install failed (exit %s)", proc.returncode)
    return classify_pip_result(("pip_failed", tail or f"exit {proc.returncode}"))
