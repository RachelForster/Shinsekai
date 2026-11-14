"""Zero-dependency multilingual (CJK + Kana + Latin) tokenizer for SQLite FTS5."""

from __future__ import annotations

import re
import unicodedata

# Contiguous ASCII/Latin alphanumeric words or contiguous CJK/Kana/Hangul runs.
_LATIN_WORD_RE = re.compile(r"[a-z0-9_]+")
_CJK_KANA_RUN_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]+"
)


def _extract_tokens(text: str, *, include_cjk_unigrams: bool) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    if not normalized.strip():
        return []

    tokens: list[str] = []
    seen: set[str] = set()

    def _push(tok: str) -> None:
        if tok and tok not in seen:
            seen.add(tok)
            tokens.append(tok)

    for match in _LATIN_WORD_RE.finditer(normalized):
        _push(match.group(0))

    for match in _CJK_KANA_RUN_RE.finditer(normalized):
        run = match.group(0)
        length = len(run)
        if length == 1:
            _push(run)
            continue
        for idx in range(length - 1):
            _push(run[idx : idx + 2])
        if include_cjk_unigrams:
            for ch in run:
                _push(ch)

    return tokens


def tokenize_for_fts(text: str) -> str:
    """Convert multilingual text into space-delimited tokens for FTS5 indexing."""
    return " ".join(_extract_tokens(text, include_cjk_unigrams=True))


def build_fts_match_query(query: str, *, max_terms: int = 24) -> str:
    """Build a syntax-safe FTS5 MATCH expression from arbitrary user text."""
    # Prefer bigrams + Latin words for multi-char CJK queries so common single
    # characters (e.g. "的", "了", "我") do not flood candidate recall.
    terms = _extract_tokens(query, include_cjk_unigrams=False)
    if not terms:
        terms = _extract_tokens(query, include_cjk_unigrams=True)
    if not terms:
        return ""
    bounded = terms[: max(1, int(max_terms))]
    escaped = ['"' + term.replace('"', '""') + '"' for term in bounded]
    return " OR ".join(escaped)
