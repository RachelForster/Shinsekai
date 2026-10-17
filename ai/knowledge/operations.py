"""Knowledge operations using an explicitly supplied local store."""

from __future__ import annotations

import logging
from typing import Any, Iterable

from ai.memory.deduplication import find_duplicate_memory, semantic_deduplication_threshold
from core.knowledge.coordination import knowledge_operation_lock as _knowledge_operation_lock
from core.knowledge.catalog import format_knowledge_entry, invalidate_catalog_after_write, pagination_arguments

logger = logging.getLogger(__name__)


def _search_store_entries(store: Any, query: str, knowledge_id: str, limit: int) -> list[Any]:
    result = store.search(
        query, filters={"user_id": knowledge_id}, **pagination_arguments(store.search, limit),
    )
    if isinstance(result, dict):
        rows = result.get("results") or []
    else:
        rows = result if isinstance(result, list) else []
    return list(rows)


def _required_text(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _normalize_identifiers(values: Iterable[str]) -> list[str]:
    return [text for value in values if (text := str(value or "").strip())]


def _add_entry_if_not_duplicate(store: Any, content: str, knowledge_id: str) -> dict[str, Any]:
    """Deduplicate and write atomically under the caller's operation lock."""
    candidates = _search_store_entries(store, content, knowledge_id, 5)
    duplicate = find_duplicate_memory(
        content, candidates, threshold=semantic_deduplication_threshold(),
    )
    result: dict[str, Any] = {
        "ok": True,
        "duplicate": duplicate is not None,
        "knowledge_id": knowledge_id,
        "content": content,
    }
    if duplicate is not None:
        result.update({
            "duplicate_type": duplicate.match_type,
            "similarity": duplicate.similarity,
            "existing_memory_id": duplicate.memory_id,
            "existing_memory": duplicate.memory,
        })
        return result
    with invalidate_catalog_after_write():
        store.add(content, user_id=knowledge_id, infer=False)
    return result


def _search_across_knowledge_bases(
    store: Any, query: str, knowledge_ids: list[str], limit: int,
) -> list[Any]:
    """Merge per-knowledge matches into a single score-ranked result set."""
    candidates: list[Any] = []
    for knowledge_id in knowledge_ids:
        with _knowledge_operation_lock:
            candidates.extend(_search_store_entries(store, query, knowledge_id, max(1, int(limit))))
    candidates.sort(
        key=lambda row: float(row.get("score") or 0) if isinstance(row, dict) else 0,
        reverse=True,
    )
    return candidates[:max(1, int(limit))]


def add_knowledge_entry(store: Any, content: str, knowledge_id: str) -> dict[str, Any]:
    """Store a fact in one knowledge, skipping exact or semantic duplicates."""
    try:
        text = _required_text(content, "content")
        normalized_knowledge_id = _required_text(knowledge_id, "knowledge id")
        with _knowledge_operation_lock:
            return _add_entry_if_not_duplicate(store, text, normalized_knowledge_id)
    except Exception as e:
        logger.exception("add_knowledge_entry 失败")
        return {"error": str(e)}


def search_knowledge(
    store: Any,
    query: str,
    *,
    knowledge_ids: Iterable[str] = (),
    limit: int = 5,
) -> dict[str, Any]:
    """Search selected knowledge bases and rank matches across them."""
    try:
        q = str(query or "").strip()
        if not q:
            return {"error": "query is required"}
        resolved_ids = sorted(set(_normalize_identifiers(knowledge_ids)))
        if not resolved_ids:
            return {"query": q, "knowledge_ids": [], "count": 0, "memories": []}
        rows = _search_across_knowledge_bases(store, q, resolved_ids, limit)
        return {"query": q, "knowledge_ids": resolved_ids, "count": len(rows), "memories": rows}
    except Exception as e:
        logger.exception("search_knowledge 失败")
        return {"error": str(e)}


def search_local_knowledge_entries(store: Any, knowledge_id: str, query: str, *, limit: int = 200) -> dict[str, Any]:
    """Search one local knowledge and format matches for the entry browser."""
    try:
        with _knowledge_operation_lock:
            normalized_knowledge_id, text = str(knowledge_id or "").strip(), str(query or "").strip()
            if not normalized_knowledge_id or not text:
                raise ValueError("knowledge id and query are required")
            rows = _search_store_entries(store, text, normalized_knowledge_id, max(1, min(200, int(limit))))
            entries = [format_knowledge_entry(row, include_text=True) for row in rows if isinstance(row, dict)]
            return {"knowledge_id": normalized_knowledge_id, "query": text, "count": len(entries), "memories": entries}
    except Exception as e:
        logger.exception("search_local_knowledge_entries failed")
        return {"error": str(e)}
