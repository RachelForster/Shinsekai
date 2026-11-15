from __future__ import annotations

from collections.abc import Callable
import threading
import time
import uuid
from typing import Any

from sdk.logging import get_logger, log_context

from application.runtime.state import BridgeState

logger = get_logger(__name__)


class TaskCancelled(Exception):
    pass


def _now_ms() -> int:
    return int(time.time() * 1000)


def _cancel_callbacks_dict(state: Any) -> dict[str, list[Callable[[], None]]]:
    callbacks = getattr(state, "task_cancel_callbacks", None)
    if isinstance(callbacks, dict):
        return callbacks
    created: dict[str, list[Callable[[], None]]] = {}
    setattr(state, "task_cancel_callbacks", created)
    return created


def _task_threads_dict(state: Any) -> dict[str, threading.Thread]:
    threads = getattr(state, "task_threads", None)
    if isinstance(threads, dict):
        return threads
    created: dict[str, threading.Thread] = {}
    setattr(state, "task_threads", created)
    return created


def _invoke_cancel_callbacks(callbacks: list[Callable[[], None]], *, task_id: str = "") -> None:
    for callback in callbacks:
        try:
            callback()
        except Exception:
            logger.exception(
                "Task cancel callback failed",
                extra={"event": "task.cancel_callback_failed", "task_id": task_id},
            )


def register_task_cancel_callback(
    state: Any,
    task_id: str,
    callback: Callable[[], None],
) -> Callable[[], None]:
    """Register an immediate cleanup/termination callback for ``task_id`` and return an unregister fn."""
    already_cancelled = False
    with state.task_lock:
        callbacks_map = _cancel_callbacks_dict(state)
        bucket = callbacks_map.setdefault(task_id, [])
        if callback not in bucket:
            bucket.append(callback)
        task = state.tasks.get(task_id)
        already_cancelled = bool(task and task.get("cancelRequested"))

    if already_cancelled:
        _invoke_cancel_callbacks([callback], task_id=task_id)

    def _unregister() -> None:
        with state.task_lock:
            callbacks_map = _cancel_callbacks_dict(state)
            bucket = callbacks_map.get(task_id)
            if not bucket:
                return
            try:
                bucket.remove(callback)
            except ValueError:
                pass
            if not bucket:
                callbacks_map.pop(task_id, None)

    return _unregister


def shutdown_background_tasks(state: Any, *, wait_timeout: float = 5.0) -> None:
    """Cancel all running background tasks, invoke their process-tree terminators, and join worker threads."""
    if state is None or not hasattr(state, "task_lock"):
        return

    callbacks_to_run: list[tuple[str, list[Callable[[], None]]]] = []
    threads_to_join: list[threading.Thread] = []
    now = _now_ms()
    with state.task_lock:
        for task_id, task in state.tasks.items():
            if _is_running_task(task) and not task.get("cancelRequested"):
                task["cancelRequested"] = True
                task["message"] = "应用正在关闭，正在取消后台任务。"
                task["phase"] = "cancelling"
                task["updatedAt"] = now
        callbacks_map = _cancel_callbacks_dict(state)
        for task_id, bucket in list(callbacks_map.items()):
            if bucket:
                callbacks_to_run.append((task_id, list(bucket)))
        threads_map = _task_threads_dict(state)
        threads_to_join = list(threads_map.values())

    for task_id, callbacks in callbacks_to_run:
        _invoke_cancel_callbacks(callbacks, task_id=task_id)

    current = threading.current_thread()
    deadline = time.monotonic() + max(0.0, float(wait_timeout))
    for worker_thread in threads_to_join:
        if worker_thread is current or not worker_thread.is_alive():
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        worker_thread.join(timeout=remaining)


def _get_task(state: BridgeState, task_id: str) -> dict[str, Any]:
    with state.task_lock:
        task = state.tasks.get(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        return dict(task)


def _create_task(state: BridgeState, *, kind: str, title: str, message: str = "") -> dict[str, Any]:
    task_id = uuid.uuid4().hex
    now = _now_ms()
    task = {
        "createdAt": now,
        "error": "",
        "id": task_id,
        "cancelRequested": False,
        "kind": kind,
        "logs": [],
        "message": message,
        "phase": "queued",
        "progress": 0,
        "result": None,
        "status": "queued",
        "title": title,
        "updatedAt": now,
    }
    with state.task_lock:
        state.tasks[task_id] = task
    logger.info(
        "Background task queued",
        extra={"event": "task.queued", "task_id": task_id, "task_kind": kind},
    )
    return dict(task)


def _update_task(state: BridgeState, task_id: str, **changes: Any) -> dict[str, Any]:
    with state.task_lock:
        task = state.tasks.get(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        task.update(changes)
        task["updatedAt"] = _now_ms()
        return dict(task)


def _request_task_cancel(state: BridgeState, task_id: str) -> dict[str, Any]:
    callbacks: list[Callable[[], None]] = []
    with state.task_lock:
        task = state.tasks.get(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        if not _is_running_task(task):
            return dict(task)
        task["cancelRequested"] = True
        task["message"] = "正在取消任务。"
        task["phase"] = "cancelling"
        task["updatedAt"] = _now_ms()
        snapshot = dict(task)
        callbacks = list(_cancel_callbacks_dict(state).get(task_id, ()))

    if callbacks:
        _invoke_cancel_callbacks(callbacks, task_id=task_id)
    return snapshot


def _is_task_cancel_requested(state: BridgeState, task_id: str) -> bool:
    with state.task_lock:
        task = state.tasks.get(task_id)
        return bool(task and task.get("cancelRequested"))


def _append_task_log(state: BridgeState, task_id: str, line: str, *, limit: int = 120) -> None:
    text = str(line).strip()
    if not text:
        return
    with state.task_lock:
        task = state.tasks.get(task_id)
        if task is None:
            return
        logs = list(task.get("logs") or [])
        logs.append(text)
        task["logs"] = logs[-limit:]
        task["updatedAt"] = _now_ms()


def _run_background_task(state: BridgeState, task_id: str, worker: Any) -> None:
    with log_context(task_id=task_id):
        _run_background_task_with_context(state, task_id, worker)


def _run_background_task_with_context(state: BridgeState, task_id: str, worker: Any) -> None:
    task_kind = str(_get_task(state, task_id).get("kind") or "")
    started = time.perf_counter()
    with state.task_lock:
        _task_threads_dict(state)[task_id] = threading.current_thread()
    try:
        logger.info(
            "Background task started",
            extra={"event": "task.started", "task_id": task_id, "task_kind": task_kind},
        )
        _update_task(state, task_id, phase="running", status="running")
        result = worker()
        _update_task(
            state,
            task_id,
            message="任务完成。",
            phase="completed",
            progress=1,
            result=result,
            status="succeeded",
        )
        logger.info(
            "Background task completed",
            extra={
                "event": "task.completed",
                "task_id": task_id,
                "task_kind": task_kind,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
    except TaskCancelled:
        _update_task(
            state,
            task_id,
            message="任务已取消，已清理下载内容。",
            phase="cancelled",
            progress=None,
            status="cancelled",
        )
        logger.warning(
            "Background task cancelled",
            extra={"event": "task.cancelled", "task_id": task_id, "task_kind": task_kind},
        )
    except Exception as exc:
        logger.exception(
            "Background task failed",
            extra={
                "event": "task.failed",
                "task_id": task_id,
                "task_kind": task_kind,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        _update_task(
            state,
            task_id,
            error=str(exc),
            message=str(exc) or exc.__class__.__name__,
            phase="failed",
            status="failed",
        )
    finally:
        with state.task_lock:
            _task_threads_dict(state).pop(task_id, None)
            _cancel_callbacks_dict(state).pop(task_id, None)


def _is_running_task(task: dict[str, Any]) -> bool:
    return str(task.get("status") or "") in {"queued", "running"}
