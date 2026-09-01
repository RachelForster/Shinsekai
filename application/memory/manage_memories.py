"""Manage memory actions and compose configured import dependencies.

Simple operations preserve the application boundary while import actions own
chunk sizing, adapter selection, progress, and cancellation composition.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence


def check_mem0_status(*, start_loading: bool = True) -> dict[str, Any]:
    from ai.memory.runtime import check_mem0_status as _check_mem0_status

    return _check_mem0_status(start_loading=start_loading)


def list_memories(character_name: str) -> dict[str, Any]:
    from ai.memory.operations import memory_list

    return memory_list(character_name)


def search_memories(
    query: str,
    *,
    character_name: str,
    limit: int = 10,
) -> dict[str, Any]:
    from ai.memory.operations import memory_search

    return memory_search(query, character_name=character_name, limit=limit)


def remember_memory(content: str, *, character_name: str) -> dict[str, Any]:
    from ai.memory.operations import memory_remember

    return memory_remember(content, character_name=character_name)


def forget_memory(memory_id: str) -> dict[str, Any]:
    from ai.memory.operations import memory_forget

    return memory_forget(memory_id)


def remember_and_list(content: str, *, character_name: str) -> dict[str, Any]:
    from ai.memory.operations import memory_remember_and_list

    return memory_remember_and_list(content, character_name=character_name)


def forget_and_list(memory_id: str, *, character_name: str) -> dict[str, Any]:
    from ai.memory.operations import memory_forget_and_list

    return memory_forget_and_list(memory_id, character_name=character_name)


def preview_import(
    paths: Sequence[str | Path],
    *,
    character_name: str,
    source_root: str | Path,
    config_manager: Any,
) -> dict[str, Any]:
    from ai.memory.extraction import configured_memory_chunk_tokens
    from ai.memory.imports import preview_memory_import

    return preview_memory_import(
        paths,
        character_name=character_name,
        source_root=source_root,
        max_chunk_tokens=configured_memory_chunk_tokens(config_manager),
    )


def execute_import(
    paths: Sequence[str | Path],
    *,
    character_name: str,
    source_root: str | Path,
    config_manager: Any,
    progress_callback: Callable[[str, float, str, str | None], None],
    cancel_callback: Callable[[], None],
) -> dict[str, Any]:
    from ai.memory.extraction import (
        configured_memory_chunk_tokens,
        create_configured_memory_adapter,
    )
    from ai.memory.imports import execute_memory_import

    return execute_memory_import(
        paths,
        character_name=character_name,
        source_root=source_root,
        llm_adapter=create_configured_memory_adapter(config_manager),
        max_chunk_tokens=configured_memory_chunk_tokens(config_manager),
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
    )
