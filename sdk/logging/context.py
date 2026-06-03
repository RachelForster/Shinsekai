"""Context fields shared by application and plugin log records."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator
from uuid import uuid4


LOG_CONTEXT_FIELDS = (
    "session_id",
    "turn_id",
    "request_id",
    "task_id",
    "plugin_id",
)

_context: ContextVar[dict[str, Any]] = ContextVar("shinsekai_log_context", default={})


def get_log_context() -> dict[str, Any]:
    """Return a copy of the current logging context."""
    return dict(_context.get())


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Temporarily attach correlation fields to logs in the current context."""
    merged = get_log_context()
    merged.update({key: value for key, value in fields.items() if value not in (None, "")})
    token = _context.set(merged)
    try:
        yield
    finally:
        _context.reset(token)


def new_log_id(prefix: str = "") -> str:
    """Create a compact correlation identifier."""
    value = uuid4().hex
    return f"{prefix}{value}" if prefix else value
