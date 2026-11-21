from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence
from typing import Any


def _check_mem0_before_call() -> dict[str, Any] | None:
    """Return a dependency error if the ONNX memory runtime is unavailable."""
    import importlib.util as _importlib_util

    from application.runtime.dependencies import (
        runtime_dependency_error_for_module,
    )
    from sdk.exception.types import runtime_dependency_error_from_module

    dependency_error = runtime_dependency_error_for_module("onnxruntime")
    if dependency_error is not None:
        return dependency_error
    spec = _importlib_util.find_spec("onnxruntime")
    if spec is not None:
        return None

    return runtime_dependency_error_from_module("onnxruntime")


def _get_mem0_status(*, start_loading: bool = True) -> dict[str, Any]:
    """Return mem0 availability status for frontend polling."""
    dependency_error = _check_mem0_before_call()
    if dependency_error is not None:
        dependency_error["status"] = "missing_dependency"
        return dependency_error

    from application.memory.manage_memories import check_mem0_status

    return check_mem0_status(start_loading=start_loading)


def _raise_memory_error(result: dict[str, Any]) -> None:
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result["error"]))


def _list_character_memories(
    name: str,
    *,
    session_id: str = "",
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import list_memories

    extra: dict[str, Any] = {}
    if session_id:
        extra["session_id"] = session_id
    if limit is not None:
        extra["limit"] = limit
    if offset:
        extra["offset"] = offset
    try:
        return list_memories(name, **extra)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _export_character_memories(
    name: str,
    *,
    session_id: str = "",
    memory_ids: list[str] | None = None,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import export_memories_text

    try:
        result = export_memories_text(
            name,
            session_id=session_id,
            memory_ids=memory_ids,
            labels=labels,
        )
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}
    _raise_memory_error(result)
    return result


def _memory_tool_search(
    query: str,
    character_name: str,
    limit: int = 10,
    *,
    session_id: str = "",
    memory_mode: str = "",
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import search_memories

    try:
        return search_memories(
            query,
            character_name=character_name,
            limit=limit,
            session_id=session_id,
            memory_mode=memory_mode,
        )
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _memory_tool_recall(payload: dict[str, Any]) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import recall_turn_memories

    try:
        return recall_turn_memories(payload)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _memory_tool_remember(
    content: str,
    character_name: str,
    *,
    gist_text: str = "",
    slot_key: str = "",
    kind: str = "episodic",
    topic_tags: Sequence[str] = (),
    entities: Sequence[str] = (),
    importance: float = 0.5,
    event_at: float | None = None,
    memory_mode: str = "",
    player_character: str = "",
    source_session_id: str = "",
    source_turn_seq: int | None = None,
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import remember_memory

    try:
        return remember_memory(
            content,
            character_name=character_name,
            gist_text=gist_text,
            slot_key=slot_key,
            kind=kind,
            topic_tags=topic_tags,
            entities=entities,
            importance=importance,
            event_at=event_at,
            memory_mode=memory_mode,
            player_character=player_character,
            source_session_id=source_session_id,
            source_turn_seq=source_turn_seq,
        )
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _memory_tool_rollback(session_id: str, turn_seq: int, *, protected_turn_seqs: Sequence[int] = ()) -> dict[str, Any]:
    from application.memory.manage_memories import rollback_memories

    return rollback_memories(session_id, turn_seq=int(turn_seq), protected_turn_seqs=protected_turn_seqs)


def _memory_tool_forget(
    memory_id: str, *, session_id: str = "", memory_mode: str = "",
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import forget_memory

    try:
        return forget_memory(memory_id, session_id=session_id, memory_mode=memory_mode)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _memory_tool_pin(memory_id: str, pinned: bool, *, session_id: str = "") -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import pin_memory

    try:
        return pin_memory(memory_id, pinned=pinned, session_id=session_id)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _memory_tool_awaken(memory_id: str, *, session_id: str = "") -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import awaken_memory

    try:
        return awaken_memory(memory_id, session_id=session_id)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _memory_asset_search(payload: dict[str, Any]) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import search_media_assets

    try:
        return search_media_assets(payload)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _memory_asset_index(payload: dict[str, Any]) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import index_media_assets

    try:
        return index_media_assets(payload)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}


def _add_character_memory(
    name: str,
    content: str,
    *,
    pinned: bool = False,
    gist_text: str = "",
    slot_key: str = "",
    kind: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import remember_and_list

    extra: dict[str, Any] = {}
    if pinned:
        extra["pinned"] = True
    if gist_text:
        extra["gist_text"] = gist_text
    if slot_key:
        extra["slot_key"] = slot_key
    if kind:
        extra["kind"] = kind
    if session_id:
        extra["session_id"] = session_id

    try:
        result = remember_and_list(content, character_name=name, **extra)
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}
    _raise_memory_error(result)
    return result


def _delete_character_memory(name: str, memory_id: str, *, session_id: str = "") -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import forget_and_list

    try:
        result = (
            forget_and_list(memory_id, character_name=name, session_id=session_id)
            if session_id
            else forget_and_list(memory_id, character_name=name)
        )
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}
    _raise_memory_error(result)
    return result


def _delete_character_memories(
    name: str,
    memory_ids: list[str],
    *,
    session_id: str = "",
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import forget_many_and_list

    try:
        result = (
            forget_many_and_list(memory_ids, character_name=name, session_id=session_id)
            if session_id
            else forget_many_and_list(memory_ids, character_name=name)
        )
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}
    _raise_memory_error(result)
    return result


def _pin_character_memory(
    name: str,
    memory_id: str,
    pinned: bool,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import pin_and_list

    try:
        result = pin_and_list(
            memory_id,
            pinned=pinned,
            character_name=name,
            session_id=session_id,
        )
    except ToolNotReady as exc:
        return {"status": "loading", "message": exc.message}
    _raise_memory_error(result)
    return result


def _awaken_character_memory(
    name: str,
    memory_id: str,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    dep_error = _check_mem0_before_call()
    if dep_error is not None:
        return dep_error

    from sdk.tool_registry import ToolNotReady
    from application.memory.manage_memories import awaken_and_list

    try:
        result = awaken_and_list(
            memory_id,
            character_name=name,
            session_id=session_id,
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

    from application.memory.manage_memories import preview_import

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

    from application.memory.manage_memories import execute_import
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
        progress_callback=report,
        cancel_callback=raise_if_cancelled,
    )
