"""Application-facing helpers for pluggable LLM dialog output formats."""

from __future__ import annotations

from typing import Any

from core.messaging.formats.registry import (
    get_dialog_format,
    registered_dialog_formats,
)
from sdk.adapters.dialog_format import DEFAULT_DIALOG_FORMAT_ID, XML_DIALOG_FORMAT_ID

_BUILTIN_IDS = frozenset({DEFAULT_DIALOG_FORMAT_ID, XML_DIALOG_FORMAT_ID})


def normalize_output_format(
    value: object,
    *,
    default: str = DEFAULT_DIALOG_FORMAT_ID,
) -> str:
    """Return a registered dialog output format id, or `default` when blank/unknown."""
    candidate = str(value or "").strip().lower()
    if not candidate:
        return default
    if candidate in _BUILTIN_IDS or get_dialog_format(candidate) is not None:
        return candidate
    return default


def list_dialog_formats() -> list[dict[str, Any]]:
    """Return UI-consumable descriptors for all registered dialog output formats."""
    return [
        {
            "id": fmt.format_id,
            "label": fmt.label or fmt.format_id,
            "builtin": fmt.format_id in _BUILTIN_IDS,
        }
        for fmt in registered_dialog_formats()
    ]
