"""Lenient matching for model-emitted effect labels.

Effect labels come from configuration and are usually short narrative phrases
such as ``被查验者为“狼”``. Models tend to paraphrase them (different quotes,
``为``/``是``, extra context), so exact matching alone drops real effects.
Matching stays deliberately conservative: exact normalized matches first, then
long containment, then character-level similarity with a high cutoff.
"""

from __future__ import annotations

from collections.abc import Sequence
import difflib
import unicodedata

_SIMILARITY_CUTOFF = 0.6
_CONTAINMENT_RATIO = 0.5


def normalize_effect_label(text: str) -> str:
    """Fold width/case and drop punctuation, quotes and whitespace."""
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(
        char
        for char in normalized
        if unicodedata.category(char)[0] in {"L", "N"}
    )


def match_effect_label(
    query: str,
    candidates: Sequence[str],
) -> str | None:
    """Return the candidate label the model most likely meant, if any."""
    normalized_query = normalize_effect_label(query)
    if not normalized_query:
        return None

    normalized: list[tuple[str, str]] = []
    for candidate in candidates:
        label = str(candidate or "")
        key = normalize_effect_label(label)
        if label and key:
            normalized.append((label, key))
    if not normalized:
        return None

    exact = [label for label, key in normalized if key == normalized_query]
    if exact:
        return min(exact, key=len)

    # The model added surrounding context to a configured phrase.
    contained = [
        (label, key)
        for label, key in normalized
        if len(key) >= 2
        and key in normalized_query
        and len(key) / len(normalized_query) >= _CONTAINMENT_RATIO
    ]
    if contained:
        return max(contained, key=lambda item: len(item[1]))[0]

    if len(normalized_query) == 1:
        # A lone character is only safe when exactly one label contains it.
        matches = [(label, key) for label, key in normalized if normalized_query in key]
        return matches[0][0] if len(matches) == 1 else None

    best_label = ""
    best_ratio = 0.0
    for label, key in normalized:
        if len(key) < 2:
            continue
        ratio = difflib.SequenceMatcher(None, normalized_query, key).ratio()
        if ratio > best_ratio:
            best_label = label
            best_ratio = ratio
    return best_label if best_ratio >= _SIMILARITY_CUTOFF else None


__all__ = ["match_effect_label", "normalize_effect_label"]
