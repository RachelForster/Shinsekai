from __future__ import annotations

from typing import Any


def _check_mem0_before_call() -> dict[str, Any] | None:
    """Return a dependency error if mem0 is unavailable."""
    import importlib.util as _importlib_util

    spec = _importlib_util.find_spec("mem0")
    if spec is not None:
        return None
    from sdk.exception.types import runtime_dependency_error_from_module

    return runtime_dependency_error_from_module("mem0")


def _get_mem0_status() -> dict[str, Any]:
    """Return mem0 availability status for frontend polling."""
    import importlib.util as _importlib_util

    spec = _importlib_util.find_spec("mem0")
    if spec is None:
        from sdk.exception.types import runtime_dependency_error_from_module

        dep = runtime_dependency_error_from_module("mem0")
        dep["status"] = "missing_dependency"
        return dep

    from ai.memory.runtime import check_mem0_status

    return check_mem0_status()


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
