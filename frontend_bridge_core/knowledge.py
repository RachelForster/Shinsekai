from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence


def _check_mem0_before_call() -> dict[str, Any] | None:
    """Check the same complete dependency group used by the memory bridge."""
    import importlib.util

    from application.runtime.dependencies import runtime_dependency_error_for_module
    from sdk.exception.types import runtime_dependency_error_from_module

    error = runtime_dependency_error_for_module("mem0")
    if error is not None:
        return error
    try:
        available = importlib.util.find_spec("mem0") is not None
    except (ImportError, AttributeError, ValueError):
        available = False
    return None if available else runtime_dependency_error_from_module("mem0")


def _get_knowledge_status(*, start_loading: bool = True, retry: bool = False) -> dict[str, Any]:
    """Return Knowledge availability status for frontend polling."""
    error = _check_mem0_before_call()
    if error is not None:
        return {**error, "status": "missing_dependency"}
    from application.knowledge.manage_knowledge import check_knowledge_status

    return check_knowledge_status(start_loading=start_loading, **({"retry": True} if retry else {}))


def _preview_knowledge_import(
    state: Any,
    knowledge_id: str,
    paths: Sequence[str | Path],
    *,
    source_root: str | Path,
) -> dict[str, Any]:
    if not str(knowledge_id or "").strip():
        raise ValueError("knowledge id is required")
    from application.knowledge.manage_knowledge import preview_import

    return preview_import(
        paths,
        knowledge_id=knowledge_id,
        source_root=source_root,
        config_manager=state.config_manager,
    )


def _run_knowledge_import(
    state: Any,
    task_id: str,
    knowledge_id: str,
    paths: Sequence[str | Path],
    *,
    source_root: str | Path,
) -> dict[str, Any]:
    error = _check_mem0_before_call()
    if error is not None:
        # Task workers treat returned dictionaries as success; fail before LLM calls.
        raise RuntimeError(str(error["message"]))
    from application.runtime.tasks import TaskCancelled, _append_task_log, _is_task_cancel_requested, _update_task
    from application.knowledge.manage_knowledge import execute_import

    def report(phase: str, progress: float, message: str, log: str | None) -> None:
        _update_task(state, task_id, phase=phase, progress=progress, message=message)
        if log:
            _append_task_log(state, task_id, log)

    def raise_if_cancelled() -> None:
        if _is_task_cancel_requested(state, task_id):
            raise TaskCancelled()

    return execute_import(
        paths,
        knowledge_id=knowledge_id,
        source_root=source_root,
        config_manager=state.config_manager,
        progress_callback=report,
        cancel_callback=raise_if_cancelled,
    )


def _knowledge_search(query: str, character_names: list[str], limit: int = 5) -> dict[str, Any]:
    return _knowledge_operation("search", query=query, character_names=character_names, limit=limit)


def _knowledge_operation(operation: str, **kwargs: Any) -> dict[str, Any]:
    from application.knowledge import manage_knowledge

    operations = {
        "search": manage_knowledge.search_knowledge,
        "list": manage_knowledge.list_knowledge,
        "remember": manage_knowledge.remember_knowledge,
        "forget": manage_knowledge.forget_knowledge,
        "delete": manage_knowledge.delete_knowledge,
        "remember-and-list": manage_knowledge.remember_and_list,
        "forget-and-list": manage_knowledge.forget_and_list,
    }
    if operation not in operations:
        raise ValueError("unknown knowledge operation")
    status = _get_knowledge_status(start_loading=True)
    if status.get("status") != "ready":
        return status
    return operations[operation](**kwargs)


def _knowledge_browse(operation: str, **kwargs: Any) -> dict[str, Any]:
    from application.knowledge import manage_knowledge

    operations = {
        "instances": manage_knowledge.list_instances,
        "entries": manage_knowledge.list_entries,
        "entries/search": manage_knowledge.search_entries,
    }
    if operation not in operations:
        raise ValueError("unknown knowledge operation")
    status = _get_knowledge_status(start_loading=True, **({"retry": True} if kwargs.get("refresh") else {}))
    if status.get("status") != "ready":
        return status
    return operations[operation](**kwargs)


def _knowledge_binding_operation(operation: str, **kwargs: Any) -> dict[str, Any]:
    """Binding management uses SQLite and must not initialize Mem0."""
    from application.knowledge import manage_knowledge
    operations = {
        "list": manage_knowledge.list_character_bindings,
        "add": manage_knowledge.add_binding,
        "remove": manage_knowledge.remove_binding,
        "knowledge": manage_knowledge.list_binding_names,
        "batch": manage_knowledge.batch_bindings,
    }
    if operation not in operations:
        raise ValueError("unknown knowledge binding operation")
    return operations[operation](**kwargs)
