"""Format-agnostic runtime registry for LLM dialog output formats."""

from core.messaging.formats.registry import (
    configure_builtin_dialog_formats,
    configure_registered_dialog_formats,
    detect_dialog_format,
    get_dialog_format,
    is_builtin_dialog_format,
    parse_dialog_content,
    register_dialog_format,
    registered_dialog_formats,
    resolve_dialog_format,
    set_builtin_dialog_formats_registrar,
)

__all__ = [
    "configure_builtin_dialog_formats",
    "configure_registered_dialog_formats",
    "detect_dialog_format",
    "get_dialog_format",
    "is_builtin_dialog_format",
    "parse_dialog_content",
    "register_dialog_format",
    "registered_dialog_formats",
    "resolve_dialog_format",
    "set_builtin_dialog_formats_registrar",
]
