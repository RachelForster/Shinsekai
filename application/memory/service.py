"""Application-facing memory operations.

Transport adapters call this module instead of depending on concrete AI
implementations directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence


def _runtime_kwargs(
    root: str | Path | None,
    config_manager: Any | None,
) -> dict[str, Any]:
    if root is None and config_manager is None:
        return {}
    return {"root": root, "config_manager": config_manager}


def check_mem0_status(
    *,
    start_loading: bool = True,
    root: str | Path | None = None,
    config_manager: Any | None = None,
) -> dict[str, Any]:
    from ai.memory.runtime import check_mem0_status as _check_mem0_status

    return _check_mem0_status(
        start_loading=start_loading,
        **_runtime_kwargs(root, config_manager),
    )


def list_memories(
    character_name: str,
    *,
    root: str | Path | None = None,
    config_manager: Any | None = None,
) -> dict[str, Any]:
    from ai.memory.operations import memory_list

    return memory_list(
        character_name,
        **_runtime_kwargs(root, config_manager),
    )


def search_memories(
    query: str,
    *,
    character_name: str,
    limit: int = 10,
    root: str | Path | None = None,
    config_manager: Any | None = None,
) -> dict[str, Any]:
    from ai.memory.operations import memory_search

    return memory_search(
        query,
        character_name=character_name,
        limit=limit,
        **_runtime_kwargs(root, config_manager),
    )


def remember_memory(
    content: str,
    *,
    character_name: str,
    root: str | Path | None = None,
    config_manager: Any | None = None,
) -> dict[str, Any]:
    from ai.memory.operations import memory_remember

    return memory_remember(
        content,
        character_name=character_name,
        **_runtime_kwargs(root, config_manager),
    )


def forget_memory(
    memory_id: str,
    *,
    root: str | Path | None = None,
    config_manager: Any | None = None,
) -> dict[str, Any]:
    from ai.memory.operations import memory_forget

    return memory_forget(
        memory_id,
        **_runtime_kwargs(root, config_manager),
    )


def remember_and_list(
    content: str,
    *,
    character_name: str,
    root: str | Path | None = None,
    config_manager: Any | None = None,
) -> dict[str, Any]:
    from ai.memory.operations import memory_remember_and_list

    return memory_remember_and_list(
        content,
        character_name=character_name,
        **_runtime_kwargs(root, config_manager),
    )


def forget_and_list(
    memory_id: str,
    *,
    character_name: str,
    root: str | Path | None = None,
    config_manager: Any | None = None,
) -> dict[str, Any]:
    from ai.memory.operations import memory_forget_and_list

    return memory_forget_and_list(
        memory_id,
        character_name=character_name,
        **_runtime_kwargs(root, config_manager),
    )


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
    root: str | Path | None = None,
    progress_callback: Callable[[str, float, str, str | None], None],
    cancel_callback: Callable[[], None],
) -> dict[str, Any]:
    from ai.memory.extraction import (
        configured_memory_chunk_tokens,
        create_configured_memory_adapter,
    )
    from ai.memory.imports import execute_memory_import

    def remember(memory: str, active_character_name: str | None) -> dict[str, Any]:
        from ai.memory.operations import memory_remember

        return memory_remember(
            memory,
            character_name=active_character_name,
            root=root,
            config_manager=config_manager,
        )

    return execute_memory_import(
        paths,
        character_name=character_name,
        source_root=source_root,
        llm_adapter=create_configured_memory_adapter(config_manager),
        max_chunk_tokens=configured_memory_chunk_tokens(config_manager),
        remember_func=remember,
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
    )
