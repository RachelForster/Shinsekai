"""Pluggable LLM dialog output formats (`json_v1`, `xml_v1`, and plugin formats)."""

from core.messaging.formats.json_format import JsonDialogFormat
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
)
from core.messaging.formats.xml_tags_format import XmlTagsDialogFormat, XmlTagsStreamParser

__all__ = [
    "JsonDialogFormat",
    "XmlTagsDialogFormat",
    "XmlTagsStreamParser",
    "configure_builtin_dialog_formats",
    "configure_registered_dialog_formats",
    "detect_dialog_format",
    "get_dialog_format",
    "is_builtin_dialog_format",
    "parse_dialog_content",
    "register_dialog_format",
    "registered_dialog_formats",
    "resolve_dialog_format",
]
