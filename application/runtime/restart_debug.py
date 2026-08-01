from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from sdk.file_transactions import open_text_append_without_links
from core.paths import require_symlink_free_absolute_path, validate_exact_path_text


def _portable_absolute_path(value: str | os.PathLike[str]) -> Path | None:
    raw = os.fspath(value)
    try:
        validate_exact_path_text(raw, field="restart log path")
    except (PermissionError, ValueError):
        return None
    try:
        candidate = Path(raw)
    except (KeyError, RuntimeError):
        return None
    if not candidate.is_absolute():
        return None
    try:
        return require_symlink_free_absolute_path(
            candidate,
            field="restart log path",
        )
    except (OSError, PermissionError, ValueError):
        return None


def _restart_debug_log_path(
    raw_path: str | None = None,
    *,
    temp_dir: str | os.PathLike[str] | None = None,
) -> Path | None:
    """Return an absolute diagnostic path without consulting process cwd."""

    configured = str(
        os.environ.get("SHINSEKAI_RESTART_LOG", "")
        if raw_path is None
        else raw_path
    )
    if configured:
        candidate = _portable_absolute_path(configured)
        if candidate is not None:
            return candidate
    if temp_dir is None:
        try:
            # The platform-selected temp directory is trusted but may be
            # spelled through an OS alias (for example /var on macOS).
            temporary_source: str | os.PathLike[str] = Path(
                tempfile.gettempdir()
            ).resolve(strict=True)
        except OSError:
            temporary_source = tempfile.gettempdir()
    else:
        temporary_source = temp_dir
    temporary = _portable_absolute_path(temporary_source)
    if temporary is not None:
        return temporary / "shinsekai-restart-debug.log"
    return None


def _sanitize_log_field(value: str) -> str:
    return str(value).replace("\0", "\\0").replace("\r", "\\r").replace("\n", "\\n")


def _append_restart_log(path: Path, line: str) -> None:
    with open_text_append_without_links(path, buffering=1) as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def write_restart_debug_log(component: str, message: str) -> None:
    name = _sanitize_log_field(str(component or "runtime").strip() or "runtime")
    safe_message = _sanitize_log_field(message)
    line = f"ts={time.time():.3f} pid={os.getpid()} component={name} {safe_message}\n"
    print(f"[restart-debug] {line}", end="")
    path = _restart_debug_log_path()
    if path is None:
        return
    try:
        _append_restart_log(path, line)
    except OSError:
        pass
