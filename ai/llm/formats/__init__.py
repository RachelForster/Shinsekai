"""Unified built-in LLM dialog output formats and registry facade."""

from core.messaging.formats.registry import (
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

from .json import JsonDialogFormat
from .registry import (
    builtin_dialog_format,
    configure_builtin_dialog_formats,
    discover_builtin_dialog_formats,
)
from .renpy import RenpyDslDialogFormat, RenpyDslStreamParser
from .xml import XmlTagsDialogFormat, XmlTagsStreamParser

__all__ = [
    "JsonDialogFormat",
    "RenpyDslDialogFormat",
    "RenpyDslStreamParser",
    "XmlTagsDialogFormat",
    "XmlTagsStreamParser",
    "builtin_dialog_format",
    "configure_builtin_dialog_formats",
    "configure_registered_dialog_formats",
    "detect_dialog_format",
    "discover_builtin_dialog_formats",
    "get_dialog_format",
    "is_builtin_dialog_format",
    "parse_dialog_content",
    "register_dialog_format",
    "registered_dialog_formats",
    "resolve_dialog_format",
    "set_builtin_dialog_formats_registrar",
]
