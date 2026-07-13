"""Lightweight token estimates for long-term memory prompts.

The estimate intentionally uses the same ``cl100k_base`` encoding as the
existing chat compaction code.  A conservative byte-based fallback keeps file
preview and chunking available when tiktoken has not been installed yet.
"""

from __future__ import annotations

import json
import math
import threading
from typing import Any, Sequence

_ENCODING_NAME = "cl100k_base"
_encoder: Any | None = None
_encoder_loaded = False
_encoder_lock = threading.Lock()


def _load_encoder() -> Any | None:
    global _encoder, _encoder_loaded
    if _encoder_loaded:
        return _encoder
    with _encoder_lock:
        if _encoder_loaded:
            return _encoder
        try:
            import tiktoken

            _encoder = tiktoken.get_encoding(_ENCODING_NAME)
        except Exception:
            _encoder = None
        _encoder_loaded = True
    return _encoder


def estimate_text_tokens(text: str) -> int:
    """Return an approximate token count for arbitrary text.

    UTF-8 bytes divided by three is deliberately a little conservative for
    most English text while remaining close enough for CJK preview estimates.
    """

    value = str(text or "")
    if not value:
        return 0
    encoder = _load_encoder()
    if encoder is not None:
        try:
            return len(encoder.encode(value))
        except Exception:
            pass
    return max(1, math.ceil(len(value.encode("utf-8")) / 3))


def estimate_message_tokens(messages: Sequence[dict[str, Any]]) -> int:
    """Estimate a chat-completions request without depending on an adapter."""

    total = 2
    for message in messages:
        total += 4
        total += estimate_text_tokens(str(message.get("role") or ""))
        content = message.get("content")
        if isinstance(content, str):
            total += estimate_text_tokens(content)
        elif content is not None:
            total += estimate_text_tokens(json.dumps(content, ensure_ascii=False, default=str))
    return total


def _reset_encoder_for_tests() -> None:
    global _encoder, _encoder_loaded
    with _encoder_lock:
        _encoder = None
        _encoder_loaded = False
