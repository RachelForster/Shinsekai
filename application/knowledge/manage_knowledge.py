"""Manage knowledge actions and compose import and deletion workflows."""


from __future__ import annotations

from typing import Any

def check_knowledge_status(*, start_loading: bool = True, retry: bool = False) -> dict[str, Any]:
    from ai.knowledge.runtime import check_mem0_status

    return check_mem0_status(start_loading=start_loading, **({"retry": True} if retry else {}))


def search_knowledge(query: str, *, character_names: list[str], limit: int = 5) -> dict[str, Any]:
    from ai.knowledge.operations import search_knowledge as search_entries_for_characters

    return search_entries_for_characters(query, character_names=character_names, limit=limit)


def list_instances(query: str = "", *, page: int = 1, refresh: bool = False) -> dict[str, Any]:
    from ai.knowledge.operations import list_knowledge_bases
    return list_knowledge_bases(query, page=page, refresh=refresh)


def list_entries(knowledge_id: str) -> dict[str, Any]:
    from ai.knowledge.operations import list_local_knowledge_entries
    return list_local_knowledge_entries(knowledge_id)


def search_entries(knowledge_id: str, query: str, *, limit: int = 200) -> dict[str, Any]:
    from ai.knowledge.operations import search_local_knowledge_entries
    return search_local_knowledge_entries(knowledge_id, query, limit=limit)


def list_knowledge(knowledge_id: str, *, limit: int = 200) -> dict[str, Any]:
    from ai.knowledge.operations import list_knowledge_entries
    return list_knowledge_entries(knowledge_id, limit=limit)


def remember_knowledge(content: str, knowledge_id: str) -> dict[str, Any]:
    from ai.knowledge.operations import add_knowledge_entry
    return add_knowledge_entry(content, knowledge_id)


def forget_knowledge(memory_id: str) -> dict[str, Any]:
    from ai.knowledge.operations import delete_knowledge_entry
    return delete_knowledge_entry(memory_id)


def remember_and_list(content: str, knowledge_id: str) -> dict[str, Any]:
    from ai.knowledge.operations import add_knowledge_entry_and_list
    return add_knowledge_entry_and_list(content, knowledge_id)


def forget_and_list(memory_id: str, knowledge_id: str) -> dict[str, Any]:
    from ai.knowledge.operations import delete_knowledge_entry_and_list
    return delete_knowledge_entry_and_list(memory_id, knowledge_id)


def add_binding(character_name: str, knowledge_id: str) -> dict[str, Any]:
    from ai.knowledge.bindings import bind_character_knowledge
    bind_character_knowledge(character_name, knowledge_id)
    return {"ok": True, "characterName": character_name.strip(), "knowledge_id": knowledge_id.strip()}


def list_binding_names(knowledge_id: str) -> dict[str, Any]:
    from ai.knowledge.bindings import list_knowledge_binding_names
    return list_knowledge_binding_names(knowledge_id)


def batch_bindings(knowledge_id: str, add: list[str], remove: list[str]) -> dict[str, Any]:
    from ai.knowledge.bindings import batch_knowledge_bindings
    return batch_knowledge_bindings(knowledge_id, add, remove)


def remove_binding(character_name: str, knowledge_id: str) -> dict[str, Any]:
    from ai.knowledge.bindings import unbind_character_knowledge
    deleted = unbind_character_knowledge(character_name, knowledge_id)
    return {"ok": True, "characterName": character_name.strip(), "knowledge_id": knowledge_id.strip(), "deleted": deleted}


def list_character_bindings(character_name: str, *, page: int = 1) -> dict[str, Any]:
    from ai.knowledge.bindings import list_character_knowledge_bindings
    return list_character_knowledge_bindings(character_name, page=page)


def rename_character_bindings(old_name: str, new_name: str) -> None:
    from ai.knowledge.bindings import rename_character_bindings as rename_bindings
    rename_bindings(old_name, new_name)


def clear_character_bindings(character_name: str) -> None:
    from ai.knowledge.bindings import delete_character_bindings
    delete_character_bindings(character_name)


def delete_knowledge(knowledge_id: str) -> dict[str, Any]:
    from ai.knowledge.operations import delete_knowledge_base

    return delete_knowledge_base(knowledge_id)
