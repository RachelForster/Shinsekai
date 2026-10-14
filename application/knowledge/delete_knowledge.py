"""Knowledge deletion use cases and partial-failure coordination."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from ai.knowledge.catalog import invalidate_knowledge_catalog
from ai.knowledge.operations import list_knowledge_entries
from ai.knowledge.runtime import get_mem0
from ai.knowledge.storage import scroll_knowledge_records
from core.knowledge.coordination import knowledge_operation_lock

logger = logging.getLogger(__name__)


@contextmanager
def _invalidate_catalog_after_write() -> Iterator[None]:
    """Invalidate even when deletion fails after partially changing data."""
    try:
        yield
    finally:
        invalidate_knowledge_catalog()


def _collect_knowledge_entry_ids(store: Any, knowledge_id: str) -> list[str]:
    """Collect every entry before deletion so scrolling sees a stable collection."""
    ids: set[str] = set()
    cursor = None
    while True:
        records, next_cursor = scroll_knowledge_records(store, knowledge_id=knowledge_id, cursor=cursor, limit=256)
        ids.update(str(record.id) for record in records)
        if next_cursor is None:
            return sorted(ids)
        cursor = str(next_cursor)


def delete_knowledge_entry(store: Any, memory_id: str) -> dict[str, Any]:
    """Delete one entry using the supplied instance, invalidating the catalog."""
    mid = str(memory_id or "").strip()
    if not mid:
        return {"error": "memory id is required"}
    try:
        with knowledge_operation_lock, _invalidate_catalog_after_write():
            store.delete(mid)
        return {"ok": True, "memory_id": mid}
    except Exception as exc:
        logger.exception("delete_knowledge_entry failed")
        return {"error": str(exc)}


def delete_knowledge_base(knowledge_id: str) -> dict[str, Any]:
    """Delete entries before bindings, preserving progress when a stage fails."""
    from core.knowledge.bindings import delete_knowledge_bindings

    normalized_knowledge_id = str(knowledge_id or "").strip()
    deleted_entries = deleted_bindings = 0
    stage = "validate"
    try:
        if not normalized_knowledge_id:
            raise ValueError("knowledge id is required")
        stage = "initialize"
        store = get_mem0()
        with knowledge_operation_lock, _invalidate_catalog_after_write():
            stage = "collect"
            ids = _collect_knowledge_entry_ids(store, normalized_knowledge_id)
            stage = "entries"
            for memory_id in ids:
                store.delete(memory_id)
                deleted_entries += 1
            stage = "bindings"
            deleted_bindings = delete_knowledge_bindings(normalized_knowledge_id)
        return {"ok": True, "knowledge_id": normalized_knowledge_id, "deletedEntryCount": deleted_entries,
                "deletedBindingCount": deleted_bindings}
    except Exception as exc:
        logger.exception("delete_knowledge_base failed")
        return {"ok": False, "error": str(exc), "knowledge_id": normalized_knowledge_id, "failedStage": stage,
                "deletedEntryCount": deleted_entries, "deletedBindingCount": deleted_bindings}


def delete_knowledge_entry_and_list(memory_id: str, knowledge_id: str) -> dict[str, Any]:
    """Return the selected knowledge's entries after a successful deletion."""
    if not str(knowledge_id or "").strip():
        return {"error": "knowledge id is required"}
    mid = str(memory_id or "").strip()
    if not mid:
        return {"error": "memory id is required"}
    try:
        store = get_mem0()
        result = delete_knowledge_entry(store, mid)
        if result.get("ok") is not True:
            return result
        return list_knowledge_entries(store, knowledge_id)
    except Exception as exc:
        logger.exception("delete_knowledge_entry_and_list failed")
        return {"error": str(exc)}
