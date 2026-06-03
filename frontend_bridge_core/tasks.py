from __future__ import annotations

import time
import uuid
from typing import Any

from sdk.logging import get_logger, log_context

from .state import BridgeState

logger = get_logger(__name__)


class TaskCancelled(Exception):
    pass


def _now_ms() -> int:
    return int(time.time() * 1000)


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
        return dict(task)


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


def _is_running_task(task: dict[str, Any]) -> bool:
    return str(task.get("status") or "") in {"queued", "running"}
