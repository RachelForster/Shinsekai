from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from sdk.path_references import state_project_root


def _memory_runtime_kwargs(state: Any | None) -> dict[str, Any]:
    if state is None:
        return {}
    return {
        "root": state_project_root(state),
        "config_manager": getattr(state, "config_manager", None),
    }


def _check_mem0_before_call() -> dict[str, Any] | None:
    """Return a dependency error if the complete mem0 runtime is unavailable."""
    import importlib.util as _importlib_util

    from application.runtime.dependencies import (
        runtime_dependency_error_for_module,
    )
    from sdk.exception.types import runtime_dependency_error_from_module

    dependency_error = runtime_dependency_error_for_module("mem0")
    if dependency_error is not None:
        return dependency_error
    spec = _importlib_util.find_spec("mem0")
    if spec is not None:
        return None

    return runtime_dependency_error_from_module("mem0")


def _get_mem0_status(
    state: Any | None = None,
    *,
    start_loading: bool = True,
) -> dict[str, Any]:
    """Return mem0 availability status for frontend polling."""
    dependency_error = _check_mem0_before_call()
    if dependency_error is not None:
        dependency_error["status"] = "missing_dependency"
        return dependency_error

    from application.memory.service import check_mem0_status

    return check_mem0_status(
        start_loading=start_loading,
        **_memory_runtime_kwargs(state),
    )


def _raise_memory_error(result: dict[str, Any]) -> None:
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result["error"]))


def _list_character_memories(
    name: str,
    *,
    state: Any | None = None,
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.service import list_memories

    try:
        return list_memories(name, **_memory_runtime_kwargs(state))
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _memory_tool_search(
    query: str,
    character_name: str,
    limit: int = 10,
    *,
    state: Any | None = None,
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.service import search_memories

    try:
        return search_memories(
            query,
            character_name=character_name,
            limit=limit,
            **_memory_runtime_kwargs(state),
        )
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _memory_tool_remember(
    content: str,
    character_name: str,
    *,
    state: Any | None = None,
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.service import remember_memory

    try:
        return remember_memory(
            content,
            character_name=character_name,
            **_memory_runtime_kwargs(state),
        )
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _memory_tool_forget(
    memory_id: str,
    *,
    state: Any | None = None,
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.service import forget_memory

    try:
        return forget_memory(memory_id, **_memory_runtime_kwargs(state))
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _add_character_memory(
    name: str,
    content: str,
    *,
    state: Any | None = None,
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.service import remember_and_list

    try:
        result = remember_and_list(
            content,
            character_name=name,
            **_memory_runtime_kwargs(state),
        )
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}
    _raise_memory_error(result)
    return result


def _delete_character_memory(
    name: str,
    memory_id: str,
    *,
    state: Any | None = None,
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.service import forget_and_list

    try:
        result = forget_and_list(
            memory_id,
            character_name=name,
            **_memory_runtime_kwargs(state),
        )
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

    from application.memory.service import preview_import

    return preview_import(
        paths,
        character_name=name,
        source_root=source_root,
        config_manager=state.config_manager,
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

    from application.memory.service import execute_import
    from application.runtime.tasks import (
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

    return execute_import(
        paths,
        character_name=name,
        source_root=source_root,
        config_manager=state.config_manager,
        root=state_project_root(state),
        progress_callback=report,
        cancel_callback=raise_if_cancelled,
    )
