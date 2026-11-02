"""Knowledge deletion use cases and partial-failure coordination."""

from __future__ import annotations

import logging
from typing import Any

from core.knowledge.catalog import collect_knowledge_entry_ids, invalidate_catalog_after_write
from application.knowledge.manage_knowledge import read_knowledge_entries
from application.knowledge.runtime import get_mem0
from core.knowledge.coordination import knowledge_operation_lock

logger = logging.getLogger(__name__)


def delete_knowledge_entry(store: Any, memory_id: str) -> dict[str, Any]:
    """Delete one entry using the supplied instance, invalidating the catalog."""
    mid = str(memory_id or "").strip()
    if not mid:
        return {"error": "memory id is required"}
    try:
        with knowledge_operation_lock, invalidate_catalog_after_write():
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
        with knowledge_operation_lock, invalidate_catalog_after_write():
            stage = "collect"
            ids = collect_knowledge_entry_ids(
                store.vector_store.client, store.vector_store.collection_name, normalized_knowledge_id,
            )
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
        return read_knowledge_entries(store.get_all, knowledge_id)
    except Exception as exc:
        logger.exception("delete_knowledge_entry_and_list failed")
        return {"error": str(exc)}
