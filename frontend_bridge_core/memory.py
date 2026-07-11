from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence


def _check_mem0_before_call() -> dict[str, Any] | None:
    """Return a dependency error if mem0 is unavailable."""
    import importlib.util as _importlib_util

    spec = _importlib_util.find_spec("mem0")
    if spec is not None:
        return None
    from sdk.exception.types import runtime_dependency_error_from_module

    return runtime_dependency_error_from_module("mem0")


def _get_mem0_status(*, start_loading: bool = True) -> dict[str, Any]:
    """Return mem0 availability status for frontend polling."""
    import importlib.util as _importlib_util

    spec = _importlib_util.find_spec("mem0")
    if spec is None:
        from sdk.exception.types import runtime_dependency_error_from_module

        dep = runtime_dependency_error_from_module("mem0")
        dep["status"] = "missing_dependency"
        return dep

    from ai.memory.runtime import check_mem0_status

    return check_mem0_status(start_loading=start_loading)


def _raise_memory_error(result: dict[str, Any]) -> None:
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result["error"]))


def _list_character_memories(name: str) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from ai.memory.operations import memory_list

    try:
        return memory_list(name)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _memory_tool_search(query: str, character_name: str, limit: int = 10) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from ai.memory.operations import memory_search

    try:
        return memory_search(query, character_name=character_name, limit=limit)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _memory_tool_remember(content: str, character_name: str) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from ai.memory.operations import memory_remember

    try:
        return memory_remember(content, character_name=character_name)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _memory_tool_forget(memory_id: str) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from ai.memory.operations import memory_forget

    try:
        return memory_forget(memory_id)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _add_character_memory(name: str, content: str) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from ai.memory.operations import memory_remember_and_list

    try:
        result = memory_remember_and_list(content, character_name=name)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}
    _raise_memory_error(result)
    return result


def _delete_character_memory(name: str, memory_id: str) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from ai.memory.operations import memory_forget_and_list

    try:
        result = memory_forget_and_list(memory_id, character_name=name)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}
    _raise_memory_error(result)
    return result


def _preview_character_memory_import(
    state: Any,
    name: str,
    paths: Sequence[str | Path],
    *,
    source_root: str | Path,
) -> dict[str, Any]:
    """Thin bridge wrapper around the memory import preview service."""

    from ai.memory.extraction import configured_memory_chunk_tokens
    from ai.memory.imports import preview_memory_import

    return preview_memory_import(
        paths,
        character_name=name,
        source_root=source_root,
        max_chunk_tokens=configured_memory_chunk_tokens(state.config_manager),
    )


def _run_character_memory_import(
    state: Any,
    task_id: str,
    name: str,
    paths: Sequence[str | Path],
    *,
    source_root: str | Path,
) -> dict[str, Any]:
    """Run extraction in a handler-owned background task."""

    from ai.memory.extraction import create_configured_memory_adapter, configured_memory_chunk_tokens
    from ai.memory.imports import execute_memory_import
    from frontend_bridge_core.tasks import (
        TaskCancelled,
        _append_task_log,
        _is_task_cancel_requested,
        _update_task,
    )

    def report(phase: str, progress: float, message: str, log: str | None) -> None:
        _update_task(state, task_id, phase=phase, progress=progress, message=message)
        if log:
            _append_task_log(state, task_id, log)

    def raise_if_cancelled() -> None:
        if _is_task_cancel_requested(state, task_id):
            raise TaskCancelled()

    adapter = create_configured_memory_adapter(state.config_manager)
    return execute_memory_import(
        paths,
        character_name=name,
        source_root=source_root,
        llm_adapter=adapter,
        max_chunk_tokens=configured_memory_chunk_tokens(state.config_manager),
        progress_callback=report,
        cancel_callback=raise_if_cancelled,
    )
