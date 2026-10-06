"""User-facing knowledge operations and local/bridge routing."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterable, Iterator

from ai.memory.deduplication import find_duplicate_memory, semantic_deduplication_threshold
from ai.knowledge.bindings import (
    list_knowledge_ids_for_characters,
    knowledge_operation_lock as _knowledge_operation_lock,
)
from ai.knowledge.catalog import (
    list_knowledge_catalog,
    invalidate_knowledge_catalog,
)
from ai.knowledge.runtime import get_mem0
from ai.knowledge.service import (
    request_knowledge_service,
    knowledge_service_status as knowledge_service_status,
)
from ai.knowledge.storage import (
    format_knowledge_entry,
    list_store_entries,
    search_store_entries,
)

logger = logging.getLogger(__name__)


def _required_text(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _normalize_identifiers(values: Iterable[str]) -> list[str]:
    return [text for value in values if (text := str(value or "").strip())]


@contextmanager
def _invalidate_catalog_after_write() -> Iterator[None]:
    """Invalidate even if a store write fails after partially changing data."""
    try:
        yield
    finally:
        invalidate_knowledge_catalog()


def _add_entry_if_not_duplicate(store: Any, content: str, knowledge_id: str) -> dict[str, Any]:
    """Deduplicate and write atomically under the caller's operation lock."""
    candidates = search_store_entries(store, content, knowledge_id, 5)
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
    with _invalidate_catalog_after_write():
        store.add(content, user_id=knowledge_id, infer=False)
    return result


def _search_across_knowledge_bases(
    store: Any, query: str, knowledge_ids: list[str], limit: int,
) -> list[Any]:
    """Merge per-knowledge matches into a single score-ranked result set."""
    candidates: list[Any] = []
    for knowledge_id in knowledge_ids:
        with _knowledge_operation_lock:
            candidates.extend(search_store_entries(store, query, knowledge_id, max(1, int(limit))))
    candidates.sort(
        key=lambda row: float(row.get("score") or 0) if isinstance(row, dict) else 0,
        reverse=True,
    )
    return candidates[:max(1, int(limit))]



def add_knowledge_entry(content: str, knowledge_id: str) -> dict[str, Any]:
    """Store a fact in one knowledge, skipping exact or semantic duplicates."""
    try:
        text = _required_text(content, "content")
        normalized_knowledge_id = _required_text(knowledge_id, "knowledge id")
        remote = request_knowledge_service("remember", {"content": text, "knowledge_id": normalized_knowledge_id})
        if remote is not None:
            return remote
        store = get_mem0()
        with _knowledge_operation_lock:
            return _add_entry_if_not_duplicate(store, text, normalized_knowledge_id)
    except Exception as e:
        logger.exception("add_knowledge_entry 失败")
        return {"error": str(e)}


def search_knowledge(
    query: str,
    *,
    character_names: Iterable[str] = (),
    knowledge_ids: Iterable[str] = (),
    limit: int = 5,
) -> dict[str, Any]:
    """Search explicit local knowledge IDs or knowledge bound to characters."""
    try:
        q = str(query or "").strip()
        names = _normalize_identifiers(character_names)
        requested_knowledge_ids = _normalize_identifiers(knowledge_ids)
        if not q:
            return {"error": "query is required"}
        if not requested_knowledge_ids:
            service_result = request_knowledge_service("search", {"query": q, "characterNames": names, "limit": limit})
            if service_result is not None:
                return service_result
        resolved_ids = sorted(set(_normalize_identifiers(
            requested_knowledge_ids or list_knowledge_ids_for_characters(names),
        )))
        if not resolved_ids:
            return {"query": q, "knowledge_ids": [], "count": 0, "memories": []}
        rows = _search_across_knowledge_bases(get_mem0(), q, resolved_ids, limit)
        return {"query": q, "knowledge_ids": resolved_ids, "count": len(rows), "memories": rows}
    except Exception as e:
        logger.exception("search_knowledge 失败")
        return {"error": str(e)}


def list_knowledge_bases(
    query: str = "", *, page: int = 1, page_size: int = 20, refresh: bool = False,
) -> dict[str, Any]:
    """List knowledge matching an ID, with paginated counts."""
    try:
        with _knowledge_operation_lock:
            return list_knowledge_catalog(
                get_mem0(), query, page=page, page_size=page_size, refresh=refresh,
            )
    except Exception as e:
        logger.exception("list_knowledge_bases failed")
        return {"error": str(e)}


def list_local_knowledge_entries(knowledge_id: str, *, limit: int = 200) -> dict[str, Any]:
    """Browse one local knowledge through Mem0, returning normalized rows."""
    try:
        with _knowledge_operation_lock:
            normalized_knowledge_id = _required_text(knowledge_id, "knowledge id")
            store = get_mem0()
            bounded_limit = max(1, min(200, int(limit)))
            entries = list_store_entries(store, normalized_knowledge_id, bounded_limit)
            return {"knowledge_id": normalized_knowledge_id, "count": len(entries), "memories": entries}
    except Exception as e:
        logger.exception("list_local_knowledge_entries failed")
        return {"error": str(e)}


def search_local_knowledge_entries(knowledge_id: str, query: str, *, limit: int = 200) -> dict[str, Any]:
    """Search one local knowledge and format matches for the entry browser."""
    try:
        with _knowledge_operation_lock:
            normalized_knowledge_id, text = str(knowledge_id or "").strip(), str(query or "").strip()
            if not normalized_knowledge_id or not text:
                raise ValueError("knowledge id and query are required")
            rows = search_store_entries(get_mem0(), text, normalized_knowledge_id, max(1, min(200, int(limit))))
            entries = [format_knowledge_entry(row, include_text=True) for row in rows if isinstance(row, dict)]
            return {"knowledge_id": normalized_knowledge_id, "query": text, "count": len(entries), "memories": entries}
    except Exception as e:
        logger.exception("search_local_knowledge_entries failed")
        return {"error": str(e)}


def list_knowledge_entries(knowledge_id: str, *, limit: int = 200) -> dict[str, Any]:
    """List one knowledge through the configured bridge or the local store."""
    try:
        normalized_knowledge_id = _required_text(knowledge_id, "knowledge id")
        remote = request_knowledge_service("list", {"knowledge_id": normalized_knowledge_id, "limit": limit})
        if remote is not None:
            return remote
        return list_local_knowledge_entries(normalized_knowledge_id, limit=limit)
    except Exception as e:
        logger.exception("list_knowledge_entries failed")
        return {"error": str(e)}


def delete_knowledge_entry(memory_id: str) -> dict[str, Any]:
    """Delete one entry by its memory ID."""
    try:
        mid = _required_text(memory_id, "memory id")
        remote = request_knowledge_service("forget", {"memory_id": mid})
        if remote is not None:
            return remote
        store = get_mem0()
        with _knowledge_operation_lock, _invalidate_catalog_after_write():
            store.delete(mid)
        return {"ok": True, "memory_id": mid}
    except Exception as e:
        logger.exception("delete_knowledge_entry failed")
        return {"error": str(e)}



def add_knowledge_entry_and_list(content: str, knowledge_id: str) -> dict[str, Any]:
    """Return the selected knowledge's entries after a successful write."""
    result = add_knowledge_entry(content, knowledge_id)
    if result.get("ok") is not True:
        return result
    return list_knowledge_entries(knowledge_id)


def delete_knowledge_entry_and_list(memory_id: str, knowledge_id: str) -> dict[str, Any]:
    """Return the selected knowledge's entries after a successful deletion."""
    if not str(knowledge_id or "").strip():
        return {"error": "knowledge id is required"}
    result = delete_knowledge_entry(memory_id)
    if result.get("ok") is not True:
        return result
    return list_knowledge_entries(knowledge_id)
