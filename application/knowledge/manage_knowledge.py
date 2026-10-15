"""Manage knowledge actions and compose import and deletion workflows."""


from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from application.knowledge.runtime import get_mem0


def check_knowledge_status(*, start_loading: bool = True, retry: bool = False) -> dict[str, Any]:
    from application.knowledge.runtime import check_mem0_status

    return check_mem0_status(start_loading=start_loading, **({"retry": True} if retry else {}))


def _with_store(operation: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Acquire the instance at the application boundary and preserve error results."""
    try:
        return operation(get_mem0(), *args, **kwargs)
    except Exception as exc:
        return {"error": str(exc)}


def preview_import(
    paths: Sequence[str | Path],
    *,
    knowledge_id: str,
    source_root: str | Path,
    config_manager: Any,
) -> dict[str, Any]:
    from ai.memory.extraction import configured_memory_chunk_tokens
    from application.knowledge.import_knowledge import preview_knowledge_import

    return preview_knowledge_import(
        paths,
        knowledge_id=knowledge_id,
        source_root=source_root,
        max_chunk_tokens=configured_memory_chunk_tokens(config_manager),
    )


def execute_import(
    paths: Sequence[str | Path],
    *,
    knowledge_id: str,
    source_root: str | Path,
    config_manager: Any,
    progress_callback: Callable[[str, float, str, str | None], None],
    cancel_callback: Callable[[], None],
) -> dict[str, Any]:
    from ai.memory.extraction import (
        configured_memory_chunk_tokens,
        create_configured_memory_adapter,
    )
    from application.knowledge.import_knowledge import execute_knowledge_import

    return execute_knowledge_import(
        paths,
        knowledge_id=knowledge_id,
        source_root=source_root,
        llm_adapter=create_configured_memory_adapter(config_manager),
        max_chunk_tokens=configured_memory_chunk_tokens(config_manager),
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
    )


def list_instances(query: str = "", *, page: int = 1, refresh: bool = False) -> dict[str, Any]:
    from ai.knowledge.operations import list_knowledge_bases
    return _with_store(list_knowledge_bases, query, page=page, refresh=refresh)


def list_entries(knowledge_id: str, *, limit: int = 200) -> dict[str, Any]:
    from ai.knowledge.operations import list_knowledge_entries
    if not str(knowledge_id or "").strip():
        return {"error": "knowledge id is required"}
    return _with_store(list_knowledge_entries, knowledge_id, limit=limit)


def search_entries(knowledge_id: str, query: str, *, limit: int = 200) -> dict[str, Any]:
    from ai.knowledge.operations import search_local_knowledge_entries
    if not str(knowledge_id or "").strip() or not str(query or "").strip():
        return {"error": "knowledge id and query are required"}
    return _with_store(search_local_knowledge_entries, knowledge_id, query, limit=limit)


def remember_knowledge(content: str, knowledge_id: str) -> dict[str, Any]:
    from ai.knowledge.operations import add_knowledge_entry
    if not str(content or "").strip():
        return {"error": "content is required"}
    if not str(knowledge_id or "").strip():
        return {"error": "knowledge id is required"}
    return _with_store(add_knowledge_entry, content, knowledge_id)


def forget_knowledge(memory_id: str) -> dict[str, Any]:
    """Acquire the instance for the standalone deletion endpoint."""
    from application.knowledge.delete_knowledge import delete_knowledge_entry

    if not str(memory_id or "").strip():
        return {"error": "memory id is required"}
    return _with_store(delete_knowledge_entry, memory_id)


def remember_and_list(content: str, knowledge_id: str) -> dict[str, Any]:
    from ai.knowledge.operations import add_knowledge_entry, list_knowledge_entries

    if not str(content or "").strip():
        return {"error": "content is required"}
    if not str(knowledge_id or "").strip():
        return {"error": "knowledge id is required"}
    try:
        store = get_mem0()
        result = add_knowledge_entry(store, content, knowledge_id)
        if result.get("ok") is not True:
            return result
        return list_knowledge_entries(store, knowledge_id)
    except Exception as exc:
        return {"error": str(exc)}


def add_binding(character_name: str, knowledge_id: str) -> dict[str, Any]:
    from core.knowledge.bindings import bind_character_knowledge
    bind_character_knowledge(character_name, knowledge_id)
    return {"ok": True, "characterName": character_name.strip(), "knowledge_id": knowledge_id.strip()}


def list_binding_names(knowledge_id: str) -> dict[str, Any]:
    from core.knowledge.bindings import list_knowledge_binding_names
    return list_knowledge_binding_names(knowledge_id)


def batch_bindings(knowledge_id: str, add: list[str], remove: list[str]) -> dict[str, Any]:
    from core.knowledge.bindings import batch_knowledge_bindings
    return batch_knowledge_bindings(knowledge_id, add, remove)


def remove_binding(character_name: str, knowledge_id: str) -> dict[str, Any]:
    from core.knowledge.bindings import unbind_character_knowledge
    deleted = unbind_character_knowledge(character_name, knowledge_id)
    return {"ok": True, "characterName": character_name.strip(), "knowledge_id": knowledge_id.strip(), "deleted": deleted}


def list_character_bindings(character_name: str, *, page: int = 1) -> dict[str, Any]:
    from core.knowledge.bindings import list_character_knowledge_bindings
    return list_character_knowledge_bindings(character_name, page=page)


def rename_character_bindings(old_name: str, new_name: str) -> None:
    from core.knowledge.bindings import rename_character_bindings as rename_bindings
    rename_bindings(old_name, new_name)


def clear_character_bindings(character_name: str) -> None:
    from core.knowledge.bindings import delete_character_bindings
    delete_character_bindings(character_name)
