"""Default redaction rules for diagnostic logs."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from typing import Any


REDACTED = "<redacted>"

_SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|secret|token)",
    re.IGNORECASE,
)
_CONTENT_KEY_RE = re.compile(
    r"(?:arguments_json|body|content|payload|prompt|response|result|speech|text|user_input)",
    re.IGNORECASE,
)
_TEXT_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{8,})\b"),
    re.compile(
        r"(?i)\b(api[ _-]?key|authorization|password|secret|token)\b"
        r"(\s*(?::|=|\bis\b)\s*)([^\s,;]+)"
    ),
)


def _content_logging_enabled() -> bool:
    return (os.environ.get("SHINSEKAI_LOG_CONTENT") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def redact_text(value: str) -> str:
    """Redact common credentials embedded in a text value."""
    text = value
    text = _TEXT_PATTERNS[0].sub("Bearer <redacted>", text)
    text = _TEXT_PATTERNS[1].sub(REDACTED, text)
    text = _TEXT_PATTERNS[2].sub(r"\1\2<redacted>", text)
    return text


def redact_value(value: Any, *, key: str = "") -> Any:
    """Redact sensitive or user-content values while preserving useful shape."""
    if key and _SENSITIVE_KEY_RE.search(key):
        return REDACTED
    if key and _CONTENT_KEY_RE.search(key) and not _content_logging_enabled():
        if isinstance(value, str):
            return f"<redacted chars={len(value)}>"
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {str(k): redact_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [redact_value(item) for item in value]
    return value
