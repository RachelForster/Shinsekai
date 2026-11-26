"""Runtime registry for built-in and plugin-provided dialog output formats."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable

from sdk.adapters.dialog_format import (
    DEFAULT_DIALOG_FORMAT_ID,
    DialogFormatContribution,
    DialogOutputFormat,
)
from sdk.messages import LLMDialogMessage

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_builtin: dict[str, DialogOutputFormat] = {}
_plugin: dict[str, DialogOutputFormat] = {}


def _normalize_format_id(format_id: object) -> str:
    return str(format_id or "").strip().lower()


def configure_builtin_dialog_formats() -> None:
    """Register built-in `json_v1` and `xml_v1` dialog formats (idempotent)."""
    from core.messaging.formats.json_format import JsonDialogFormat
    from core.messaging.formats.xml_tags_format import XmlTagsDialogFormat

    with _lock:
        if "json_v1" not in _builtin:
            register_dialog_format(JsonDialogFormat(), builtin=True)
        if "xml_v1" not in _builtin:
            register_dialog_format(XmlTagsDialogFormat(), builtin=True)


def _ensure_builtins() -> None:
    if not _builtin:
        configure_builtin_dialog_formats()


def register_dialog_format(
    fmt: DialogOutputFormat,
    *,
    builtin: bool = False,
) -> None:
    """Register a dialog output format instance."""
    format_id = _normalize_format_id(getattr(fmt, "format_id", ""))
    if not format_id:
        raise ValueError("dialog output format requires a non-empty format_id")
    with _lock:
        if format_id in _builtin or format_id in _plugin:
            raise ValueError(f"duplicate dialog output format: {format_id}")
        target = _builtin if builtin else _plugin
        target[format_id] = fmt


def configure_registered_dialog_formats(
    contributions: Iterable[DialogFormatContribution],
) -> None:
    """Atomically refresh plugin-contributed dialog formats (called by plugin host)."""
    _ensure_builtins()
    registered: dict[str, DialogOutputFormat] = {}
    for contribution in contributions:
        format_id = _normalize_format_id(contribution.format_id)
        if not format_id:
            logger.error("invalid dialog format id: %r", contribution.format_id)
            continue
        if format_id in registered:
            logger.error("duplicate dialog format id: %s", format_id)
            continue
        with _lock:
            if format_id in _builtin:
                logger.error("dialog format conflicts with builtin: %s", format_id)
                continue
        try:
            fmt = contribution.factory()
            if not isinstance(fmt, DialogOutputFormat):
                raise TypeError("dialog format factory must return a DialogOutputFormat")
            if _normalize_format_id(fmt.format_id) != format_id:
                raise ValueError(
                    f"dialog format mismatch: registered {format_id!r}, "
                    f"instance declares {fmt.format_id!r}"
                )
        except Exception:
            logger.exception(
                "dialog format factory failed for %r",
                contribution.format_id,
            )
            continue
        registered[format_id] = fmt
    with _lock:
        _plugin.clear()
        _plugin.update({k: v for k, v in registered.items() if k not in _builtin})


def get_dialog_format(format_id: str | None) -> DialogOutputFormat | None:
    """Return registered format or None when absent."""
    _ensure_builtins()
    key = _normalize_format_id(format_id)
    if not key:
        return None
    with _lock:
        return _builtin.get(key) or _plugin.get(key)


def resolve_dialog_format(format_id: str | None) -> DialogOutputFormat:
    """Resolve `format_id` with fallback to `DEFAULT_DIALOG_FORMAT_ID` (`json_v1`)."""
    _ensure_builtins()
    key = _normalize_format_id(format_id)
    if not key:
        return _builtin[DEFAULT_DIALOG_FORMAT_ID]
    with _lock:
        fmt = _builtin.get(key) or _plugin.get(key)
    if fmt is not None:
        return fmt
    logger.warning(
        "Unknown dialog output format %r; falling back to %s",
        format_id,
        DEFAULT_DIALOG_FORMAT_ID,
    )
    return _builtin[DEFAULT_DIALOG_FORMAT_ID]


def registered_dialog_formats() -> tuple[DialogOutputFormat, ...]:
    """Return registered dialog formats in deterministic UI order (`xml_v1`, `json_v1`, plugins)."""
    _ensure_builtins()
    with _lock:
        ordered: list[DialogOutputFormat] = []
        for builtin_id in ("xml_v1", "json_v1"):
            if builtin_id in _builtin:
                ordered.append(_builtin[builtin_id])
        for builtin_id in sorted(_builtin):
            if builtin_id not in ("xml_v1", "json_v1"):
                ordered.append(_builtin[builtin_id])
        for plugin_id in sorted(_plugin):
            ordered.append(_plugin[plugin_id])
    return tuple(ordered)


def detect_dialog_format(raw: str) -> DialogOutputFormat | None:
    """Probe registered formats and return the first matching format."""
    _ensure_builtins()
    with _lock:
        candidates = list(_builtin.values()) + [
            _plugin[k] for k in sorted(_plugin)
        ]
    for fmt in candidates:
        try:
            if fmt.can_parse(raw):
                return fmt
        except Exception:
            continue
    return None


def parse_dialog_content(
    raw: str,
    *,
    format_id: str | None = None,
) -> list[LLMDialogMessage]:
    """Parse complete assistant output using `format_id` or automatic format detection."""
    text = str(raw or "")
    if not text.strip():
        return []
    _ensure_builtins()
    if format_id:
        fmt = get_dialog_format(format_id)
        if fmt is not None:
            parsed = fmt.parse_complete(text)
            if parsed:
                return parsed
    detected = detect_dialog_format(text)
    if detected is not None:
        return detected.parse_complete(text)
    return []


def _reset_for_tests() -> None:
    """Test helper: reset registry state and drop plugin formats."""
    with _lock:
        _builtin.clear()
        _plugin.clear()
