"""Helpers for inline bracketed TTS voice tags (e.g. ``[laugh]``, ``[soft whisper]``)."""

from __future__ import annotations

import re

INLINE_VOICE_TAG_RE = re.compile(r"\[[^\[\]\r\n]{1,80}\](?!\()")
_SENTENCE_SPLIT_PUNCT = frozenset("。！？，、；：.!?,;:")


def strip_inline_voice_tags(text: str) -> str:
    """Remove inline bracket voice cues while preserving Markdown ``[label](url)`` links."""
    cleaned = INLINE_VOICE_TAG_RE.sub(" ", str(text or ""))
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def split_tts_sentences_preserving_tags(text: str, max_length: int) -> list[str]:
    """Split speech text into length-bounded chunks without cutting inside ``[...]`` tags."""
    raw = str(text or "")
    pieces: list[str] = []
    buf: list[str] = []
    bracket_depth = 0
    for ch in raw:
        buf.append(ch)
        if ch == "[":
            bracket_depth += 1
        elif ch == "]" and bracket_depth > 0:
            bracket_depth -= 1
        elif bracket_depth == 0 and ch in _SENTENCE_SPLIT_PUNCT:
            piece = "".join(buf).strip()
            if piece:
                pieces.append(piece)
            buf.clear()
    tail = "".join(buf).strip()
    if tail:
        pieces.append(tail)

    sentences: list[str] = []
    current = ""
    limit = int(max_length)
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + len(piece) <= limit:
            current += piece
        else:
            sentences.append(current)
            current = piece
    if current:
        sentences.append(current)
    return sentences


__all__ = [
    "INLINE_VOICE_TAG_RE",
    "split_tts_sentences_preserving_tags",
    "strip_inline_voice_tags",
]
