"""Token-aware chunking for normalized plain-dialogue transcripts."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ai.memory.token_estimator import estimate_text_tokens

DEFAULT_DIALOGUE_CHUNK_TOKENS = 8_000
MIN_DIALOGUE_CHUNK_TOKENS = 256


def _split_oversized_unit(text: str, max_tokens: int) -> list[str]:
    remaining = str(text or "").strip()
    if not remaining:
        return []
    pieces: list[str] = []
    while remaining:
        if estimate_text_tokens(remaining) <= max_tokens:
            pieces.append(remaining)
            break

        low = 1
        high = len(remaining)
        best = 1
        while low <= high:
            middle = (low + high) // 2
            candidate = remaining[:middle]
            if estimate_text_tokens(candidate) <= max_tokens:
                best = middle
                low = middle + 1
            else:
                high = middle - 1

        boundary = best
        for marker in ("\n", "。", "！", "？", ". ", "! ", "? ", "，", ", ", " "):
            found = remaining.rfind(marker, 0, best + 1)
            if found >= max(1, best // 2):
                boundary = found + len(marker)
                break
        piece = remaining[:boundary].strip()
        if not piece:
            piece = remaining[:best]
            boundary = best
        pieces.append(piece)
        remaining = remaining[boundary:].strip()
    return pieces


def chunk_dialogue_units(
    units: Sequence[str] | Iterable[str],
    *,
    max_tokens: int = DEFAULT_DIALOGUE_CHUNK_TOKENS,
) -> list[str]:
    """Group complete dialogue units until the token budget is reached.

    Oversized individual turns are split only as a last resort.  No overlap is
    added, which avoids presenting the same fact to the memory extractor twice.
    """

    budget = max(MIN_DIALOGUE_CHUNK_TOKENS, int(max_tokens))
    normalized: list[str] = []
    for unit in units:
        text = str(unit or "").strip()
        if not text:
            continue
        normalized.extend(_split_oversized_unit(text, budget))

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for unit in normalized:
        unit_tokens = estimate_text_tokens(unit)
        separator_tokens = 1 if current else 0
        if current and current_tokens + separator_tokens + unit_tokens > budget:
            chunks.append("\n".join(current))
            current = []
            current_tokens = 0
            separator_tokens = 0
        current.append(unit)
        current_tokens += separator_tokens + unit_tokens
    if current:
        chunks.append("\n".join(current))
    return chunks


def chunk_plain_dialogue(
    dialogue: str,
    *,
    max_tokens: int = DEFAULT_DIALOGUE_CHUNK_TOKENS,
) -> list[str]:
    return chunk_dialogue_units(str(dialogue or "").splitlines(), max_tokens=max_tokens)
