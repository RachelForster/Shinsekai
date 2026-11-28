"""Runtime registry for built-in and plugin-provided dialog output formats."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable

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
_plugin_orders: dict[str, int] = {}
_builtin_registrar: Callable[[], None] | None = None
_configuring_builtins = False


def _normalize_format_id(format_id: object) -> str:
    return str(format_id or "").strip().lower()


def _format_order(fmt: DialogOutputFormat, *, override: int | None = None) -> int:
    if override is not None:
        return int(override)
    raw = getattr(fmt, "order", 100)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 100


def set_builtin_dialog_formats_registrar(registrar: Callable[[], None] | None) -> None:
    """Bind the callback used to populate built-in formats on demand."""
    global _builtin_registrar
    with _lock:
        _builtin_registrar = registrar


def configure_builtin_dialog_formats() -> None:
    """Register built-in dialog formats via the bound registrar (idempotent)."""
    global _configuring_builtins
    with _lock:
        if _configuring_builtins:
            return
        registrar = _builtin_registrar
        if registrar is None:
            return
        _configuring_builtins = True
        try:
            registrar()
        finally:
            _configuring_builtins = False


def _ensure_builtins() -> None:
    with _lock:
        if not _builtin and not _configuring_builtins and _builtin_registrar is not None:
            configure_builtin_dialog_formats()


def register_dialog_format(
    fmt: DialogOutputFormat,
    *,
    builtin: bool = False,
    replace_existing: bool = True,
) -> None:
    """Register a dialog output format instance."""
    format_id = _normalize_format_id(getattr(fmt, "format_id", ""))
    if not format_id:
        raise ValueError("dialog output format requires a non-empty format_id")
    if not builtin:
        _ensure_builtins()
    with _lock:
        if format_id in _builtin:
            if builtin and not replace_existing:
                return
            raise ValueError(f"duplicate dialog output format: {format_id}")
        if format_id in _plugin:
            raise ValueError(f"duplicate dialog output format: {format_id}")
        target = _builtin if builtin else _plugin
        target[format_id] = fmt


def configure_registered_dialog_formats(
    contributions: Iterable[DialogFormatContribution],
) -> None:
    """Atomically refresh plugin-contributed dialog formats (called by plugin host)."""
    _ensure_builtins()
    registered: dict[str, DialogOutputFormat] = {}
    registered_orders: dict[str, int] = {}
    for contribution in contributions:
        format_id = _normalize_format_id(contribution.format_id)
        if not format_id:
            logger.error("invalid dialog format id: %r", contribution.format_id)
            continue
        if format_id in registered:
            logger.error("duplicate dialog format id: %s", format_id)
            continue
        with _lock:
            existing_builtin = _builtin.get(format_id)
        is_declared_builtin = str(contribution.plugin_id or "").startswith("shinsekai.builtin.")
        if existing_builtin is not None:
            if not is_declared_builtin:
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
        raw_priority = getattr(contribution, "priority", 100)
        order = (
            int(raw_priority)
            if raw_priority is not None and int(raw_priority) != 100
            else _format_order(fmt)
        )
        registered[format_id] = fmt
        registered_orders[format_id] = order
    with _lock:
        _plugin.clear()
        _plugin_orders.clear()
        for key, fmt in registered.items():
            if key not in _builtin:
                _plugin[key] = fmt
                _plugin_orders[key] = registered_orders[key]


def get_dialog_format(format_id: str | None) -> DialogOutputFormat | None:
    """Return registered format or None when absent."""
    _ensure_builtins()
    key = _normalize_format_id(format_id)
    if not key:
        return None
    with _lock:
        return _builtin.get(key) or _plugin.get(key)


def is_builtin_dialog_format(format_id: str | None) -> bool:
    """Return True when `format_id` identifies a built-in dialog format."""
    _ensure_builtins()
    key = _normalize_format_id(format_id)
    if not key:
        return False
    with _lock:
        return key in _builtin


def registered_dialog_formats() -> tuple[DialogOutputFormat, ...]:
    """Return registered dialog formats sorted by `(order, format_id)` (built-ins then plugins)."""
    _ensure_builtins()
    with _lock:
        builtins = sorted(
            _builtin.values(),
            key=lambda fmt: (_format_order(fmt), _normalize_format_id(fmt.format_id)),
        )
        plugins = sorted(
            _plugin.values(),
            key=lambda fmt: (
                _format_order(
                    fmt,
                    override=_plugin_orders.get(_normalize_format_id(fmt.format_id)),
                ),
                _normalize_format_id(fmt.format_id),
            ),
        )
    return tuple([*builtins, *plugins])


def resolve_dialog_format(format_id: str | None) -> DialogOutputFormat:
    """Resolve `format_id` with fallback to `DEFAULT_DIALOG_FORMAT_ID` or first registered."""
    _ensure_builtins()
    key = _normalize_format_id(format_id)
    with _lock:
        if key:
            fmt = _builtin.get(key) or _plugin.get(key)
            if fmt is not None:
                return fmt
            logger.warning(
                "Unknown dialog output format %r; falling back to %s",
                format_id,
                DEFAULT_DIALOG_FORMAT_ID,
            )
        default_fmt = _builtin.get(DEFAULT_DIALOG_FORMAT_ID) or _plugin.get(
            DEFAULT_DIALOG_FORMAT_ID
        )
        if default_fmt is not None:
            return default_fmt
    registered = registered_dialog_formats()
    if registered:
        return registered[0]
    raise LookupError("No dialog output formats are registered")


def detect_dialog_format(raw: str) -> DialogOutputFormat | None:
    """Probe registered formats and return the first matching format."""
    for fmt in registered_dialog_formats():
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


def _reset_for_tests(*, keep_registrar: bool = True) -> None:
    """Test helper: reset registry state and drop plugin formats."""
    global _builtin_registrar
    with _lock:
        _builtin.clear()
        _plugin.clear()
        _plugin_orders.clear()
        if not keep_registrar:
            _builtin_registrar = None
