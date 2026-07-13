"""Semantic duplicate detection for long-term memories."""

from __future__ import annotations

import logging
import os
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

logger = logging.getLogger(__name__)

DEFAULT_SEMANTIC_DEDUPLICATION_THRESHOLD = 0.92
SEMANTIC_DEDUPLICATION_THRESHOLD_ENV = "SHINSEKAI_MEMORY_DEDUP_THRESHOLD"


@dataclass(frozen=True)
class DuplicateMemoryMatch:
    """An existing memory considered equivalent to a proposed write."""

    memory_id: str
    memory: str
    similarity: float | None
    match_type: str


def semantic_deduplication_threshold() -> float:
    """Return the configured cosine-similarity threshold."""

    raw = str(os.environ.get(SEMANTIC_DEDUPLICATION_THRESHOLD_ENV) or "").strip()
    if not raw:
        return DEFAULT_SEMANTIC_DEDUPLICATION_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "invalid %s=%r; using %.2f",
            SEMANTIC_DEDUPLICATION_THRESHOLD_ENV,
            raw,
            DEFAULT_SEMANTIC_DEDUPLICATION_THRESHOLD,
        )
        return DEFAULT_SEMANTIC_DEDUPLICATION_THRESHOLD
    if not 0.0 <= value <= 1.0:
        logger.warning(
            "out-of-range %s=%r; using %.2f",
            SEMANTIC_DEDUPLICATION_THRESHOLD_ENV,
            raw,
            DEFAULT_SEMANTIC_DEDUPLICATION_THRESHOLD,
        )
        return DEFAULT_SEMANTIC_DEDUPLICATION_THRESHOLD
    return value


def find_duplicate_memory(
    proposed_memory: str,
    search_result: Any,
    *,
    threshold: float | None = None,
) -> DuplicateMemoryMatch | None:
    """Find an exact or high-similarity match in a Mem0 search response."""

    normalized_proposed = _normalize_memory(proposed_memory)
    if not normalized_proposed:
        return None
    effective_threshold = semantic_deduplication_threshold() if threshold is None else threshold
    for row in _result_rows(search_result):
        existing_memory = _memory_text(row)
        if not existing_memory:
            continue
        similarity = _similarity_score(row)
        if _normalize_memory(existing_memory) == normalized_proposed:
            return DuplicateMemoryMatch(
                memory_id=_memory_id(row),
                memory=existing_memory,
                similarity=similarity,
                match_type="exact",
            )
        if similarity is not None and similarity >= effective_threshold:
            return DuplicateMemoryMatch(
                memory_id=_memory_id(row),
                memory=existing_memory,
                similarity=similarity,
                match_type="semantic",
            )
    return None


def _result_rows(search_result: Any) -> Iterable[Any]:
    if isinstance(search_result, dict):
        rows = search_result.get("results")
        return rows if isinstance(rows, list) else []
    return search_result if isinstance(search_result, list) else []


def _memory_text(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("memory") or row.get("content") or row.get("text") or "").strip()
    return str(row or "").strip()


def _memory_id(row: Any) -> str:
    return str(row.get("id") or "") if isinstance(row, dict) else ""


def _similarity_score(row: Any) -> float | None:
    if not isinstance(row, dict):
        return None
    raw = row.get("score", row.get("similarity"))
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return None
    return score if 0.0 <= score <= 1.0 else None


def _normalize_memory(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(normalized.split())
