"""Host-owned configuration for the shared logging system."""

from __future__ import annotations

import atexit
import copy
import logging
import logging.handlers
import os
import queue
import re
import stat
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from sdk.file_transactions import (
    open_text_append_without_links,
    read_text_without_links,
    remove_file_without_links,
    require_directory_identity,
    rename_path_without_overwrite,
    snapshot_directory_entries_without_links,
)
from sdk.path_contract import (
    managed_child_path,
    managed_project_storage,
    path_is_link_or_reparse_point,
    project_root as configured_project_root,
    require_directory_without_links,
    require_symlink_free_absolute_path,
    resolve_project_output_path,
    resolve_project_path,
    safe_path_component,
    truncate_utf8_bytes,
)
from sdk.logging.context import get_log_context, new_log_id
from sdk.logging.environment import runtime_environment
from sdk.logging.formatters import ConsoleFormatter, JsonLineFormatter
from sdk.logging.redaction import redact_value


_lock = threading.Lock()
_listener: logging.handlers.QueueListener | None = None
_queue_handler: logging.Handler | None = None
_atexit_registered = False


class _ContextFilter(logging.Filter):
    def __init__(self, app_name: str, version: str, session_id: str) -> None:
        super().__init__()
        self.app_name = app_name
        self.version = version
        self.session_id = session_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.app = self.app_name
        record.version = self.version
        record.session_id = self.session_id
        for key, value in get_log_context().items():
            setattr(record, key, value)
        if record.args:
            record.args = redact_value(record.args)
        return True


class _PreservingQueueHandler(logging.handlers.QueueHandler):
    """Queue handler that keeps exception details for the listener formatter."""

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        return copy.copy(record)


class _PathSafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Rotate only exact regular files under the shared path contract."""

    def _open(self):
        return open_text_append_without_links(
            self.baseFilename,
            encoding=self.encoding or "utf-8",
        )

    @staticmethod
    def _regular_file_identity(path: str) -> os.stat_result:
        candidate = Path(path)
        metadata = candidate.lstat()
        if path_is_link_or_reparse_point(candidate) or not stat.S_ISREG(
            metadata.st_mode
        ):
            raise PermissionError(f"log rotation source is not a regular file: {candidate}")
        return metadata

    def doRollover(self) -> None:  # noqa: N802 - stdlib API name
        if self.stream:
            self.stream.close()
            self.stream = None

        if self.backupCount > 0:
            for index in range(self.backupCount - 1, 0, -1):
                source = self.rotation_filename(f"{self.baseFilename}.{index}")
                destination = self.rotation_filename(
                    f"{self.baseFilename}.{index + 1}"
                )
                if not os.path.lexists(source):
                    continue
                source_identity = self._regular_file_identity(source)
                if os.path.lexists(destination):
                    destination_identity = self._regular_file_identity(
                        destination
                    )
                    remove_file_without_links(
                        destination,
                        expected_identity=destination_identity,
                    )
                rename_path_without_overwrite(
                    source,
                    destination,
                    expected_identity=source_identity,
                )

            destination = self.rotation_filename(f"{self.baseFilename}.1")
            if os.path.lexists(self.baseFilename):
                source_identity = self._regular_file_identity(self.baseFilename)
                if os.path.lexists(destination):
                    destination_identity = self._regular_file_identity(
                        destination
                    )
                    remove_file_without_links(
                        destination,
                        expected_identity=destination_identity,
                    )
                rename_path_without_overwrite(
                    self.baseFilename,
                    destination,
                    expected_identity=source_identity,
                )

        if not self.delay:
            self.stream = self._open()


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(" .-")
    safe = truncate_utf8_bytes(safe or "app", 255)
    try:
        return safe_path_component(safe, field="logging application name")
    except ValueError:
        # The sanitizer's alphabet has already removed separators and control
        # characters and the byte limit is already enforced, so the remaining
        # failure is a Windows device alias.
        return safe_path_component(
            truncate_utf8_bytes(f"app-{safe}", 255),
            field="logging application name",
        )


def _read_version(project_root: Path) -> str:
    del project_root  # Version metadata belongs to the immutable distribution.
    try:
        from sdk.path_contract import resource_path

        candidate = resource_path("VERSION")
    except Exception:
        return "unknown"
    try:
        return read_text_without_links(candidate).strip() or "unknown"
    except (OSError, PermissionError, ValueError):
        return "unknown"


def _parse_level(value: str | int | None) -> int:
    if isinstance(value, int):
        return value
    raw = str(value or os.environ.get("SHINSEKAI_LOG_LEVEL") or "INFO").upper()
    parsed = getattr(logging, raw, logging.INFO)
    return parsed if isinstance(parsed, int) else logging.INFO


def _cleanup_old_logs(log_dir: Path, retention_days: int) -> None:
    if retention_days <= 0:
        return
    cutoff = time.time() - retention_days * 86400
    try:
        log_dir, log_dir_identity, directory_entries = (
            snapshot_directory_entries_without_links(
                log_dir,
                field="log directory",
            )
        )
        entries = [
            (path, metadata)
            for path, metadata in directory_entries
            if path.match("*.jsonl*")
        ]
        require_directory_identity(
            log_dir,
            log_dir_identity,
            field="log directory",
        )
    except OSError:
        return
    for path, metadata in entries:
        try:
            require_directory_identity(
                log_dir,
                log_dir_identity,
                field="log directory",
            )
            if (
                not path_is_link_or_reparse_point(path)
                and stat.S_ISREG(metadata.st_mode)
                and metadata.st_mtime < cutoff
            ):
                remove_file_without_links(
                    path,
                    expected_identity=metadata,
                    expected_parent_identity=log_dir_identity,
                )
        except (OSError, ValueError):
            continue


def _install_exception_hooks() -> None:
    def _sys_hook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        logging.getLogger("shinsekai.uncaught").critical(
            "Uncaught exception",
            exc_info=(exc_type, exc, tb),
            extra={"event": "process.uncaught_exception"},
        )

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        logging.getLogger("shinsekai.uncaught").critical(
            "Uncaught thread exception",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            extra={
                "event": "thread.uncaught_exception",
                "failed_thread": getattr(args.thread, "name", ""),
            },
        )

    sys.excepthook = _sys_hook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_hook


def configure_logging(
    app_name: str,
    *,
    project_root: str | Path | None = None,
    log_dir: str | Path | None = None,
    level: str | int | None = None,
    console: bool = True,
    file: bool = True,
    replace_handlers: bool = True,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    retention_days: int = 14,
    install_exception_hooks: bool = True,
) -> Path | None:
    """Configure root logging for one Shinsekai host process.

    Plugins should use :func:`sdk.logging.get_logger` and must not call this
    function. Application entry points own configuration.
    """
    global _listener, _queue_handler, _atexit_registered

    root_path = (
        resolve_project_path(".", root=project_root)
        if project_root is not None
        else configured_project_root()
    )
    version = _read_version(root_path)
    safe_app_name = _safe_name(app_name)
    resolved_level = _parse_level(level)
    session_id = new_log_id("session_")
    output_path: Path | None = None

    with _lock:
        if _listener is not None:
            return getattr(_listener, "_shinsekai_log_path", None)

        handlers: list[logging.Handler] = []
        if console:
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setLevel(resolved_level)
            console_handler.setFormatter(ConsoleFormatter())
            handlers.append(console_handler)

        if file:
            try:
                if log_dir is not None:
                    configured_log_dir = Path(log_dir).expanduser()
                    if configured_log_dir.is_absolute():
                        require_symlink_free_absolute_path(
                            configured_log_dir,
                            field="log directory",
                        )
                    base_dir = resolve_project_output_path(
                        log_dir,
                        root=root_path,
                    )
                else:
                    base_dir = managed_project_storage(
                        Path("logs") / safe_app_name,
                        root=root_path,
                    )
                base_dir.mkdir(parents=True, exist_ok=True)
                base_dir = require_directory_without_links(
                    base_dir,
                    field="log directory",
                )
                _cleanup_old_logs(base_dir, retention_days)
                stamp = time.strftime("%Y%m%d-%H%M%S")
                output_path = managed_child_path(
                    base_dir,
                    f"{stamp}-{os.getpid()}-{uuid.uuid4().hex}.jsonl",
                    field="log filename",
                )
                file_handler = _PathSafeRotatingFileHandler(
                    output_path,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding="utf-8",
                )
                file_handler.setLevel(resolved_level)
                file_handler.setFormatter(JsonLineFormatter())
                handlers.append(file_handler)
            except OSError:
                output_path = None

        if not handlers:
            handlers.append(logging.NullHandler())

        record_queue: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
        queue_handler = _PreservingQueueHandler(record_queue)
        queue_handler.setLevel(resolved_level)
        queue_handler.addFilter(_ContextFilter(safe_app_name, version, session_id))
        queue_handler._shinsekai_handler = True  # type: ignore[attr-defined]

        root_logger = logging.getLogger()
        if replace_handlers:
            for handler in list(root_logger.handlers):
                root_logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass
        root_logger.addHandler(queue_handler)
        root_logger.setLevel(resolved_level)

        listener = logging.handlers.QueueListener(
            record_queue,
            *handlers,
            respect_handler_level=True,
        )
        listener._shinsekai_log_path = output_path  # type: ignore[attr-defined]
        listener.start()
        _queue_handler = queue_handler
        _listener = listener

        if install_exception_hooks:
            _install_exception_hooks()
        if not _atexit_registered:
            atexit.register(shutdown_logging)
            _atexit_registered = True

    logging.getLogger("shinsekai.logging").info(
        "Logging configured",
        extra={
            "event": "logging.configured",
            "log_path": str(output_path) if output_path else "",
        },
    )
    logging.getLogger("shinsekai.runtime").info(
        "Runtime environment",
        extra={
            "event": "runtime.environment",
            **runtime_environment(root_path, level=resolved_level, log_path=output_path),
        },
    )
    return output_path


def shutdown_logging() -> None:
    """Flush and stop the process logging listener."""
    global _listener, _queue_handler
    with _lock:
        listener = _listener
        queue_handler = _queue_handler
        _listener = None
        _queue_handler = None
    if listener is not None:
        listener.stop()
        for handler in listener.handlers:
            handler.close()
    if queue_handler is not None:
        root_logger = logging.getLogger()
        root_logger.removeHandler(queue_handler)
        queue_handler.close()
