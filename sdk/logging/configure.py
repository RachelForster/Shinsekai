"""Host-owned configuration for the shared logging system."""

from __future__ import annotations

import atexit
import copy
import logging
import logging.handlers
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

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


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return safe or "app"


def _read_version(project_root: Path) -> str:
    candidates = [project_root / "VERSION"]
    try:
        from core.paths import resource_path

        candidates.append(resource_path("VERSION"))
    except Exception:
        pass
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            path = candidate.resolve(strict=False)
        except OSError:
            path = candidate
        if path in seen:
            continue
        seen.add(path)
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
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
        entries = list(log_dir.glob("*.jsonl*"))
    except OSError:
        return
    for path in entries:
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
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

    root_path = Path(project_root or os.environ.get("EASYAI_PROJECT_ROOT") or Path.cwd()).resolve()
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
                base_dir = Path(log_dir).resolve() if log_dir else root_path / "logs" / safe_app_name
                base_dir.mkdir(parents=True, exist_ok=True)
                _cleanup_old_logs(base_dir, retention_days)
                stamp = time.strftime("%Y%m%d-%H%M%S")
                output_path = base_dir / f"{stamp}-{os.getpid()}.jsonl"
                file_handler = logging.handlers.RotatingFileHandler(
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
