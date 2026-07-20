"""Validation helpers for the runtime dialogue output contract."""

from __future__ import annotations

from typing import Any

from core.messaging.stream_parser import LlmResponseStreamParser


def has_valid_dialog_output(content: Any) -> bool:
    """Return whether *content* can produce at least one dialogue message."""
    if not isinstance(content, str) or not content.strip():
        return False
    parser = LlmResponseStreamParser()
    return bool(list(parser.feed(content)))
