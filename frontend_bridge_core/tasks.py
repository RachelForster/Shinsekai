from __future__ import annotations

import time
import uuid
from typing import Any

from .state import BridgeState


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
    return dict(task)


def _update_task(state: BridgeState, task_id: str, **changes: Any) -> dict[str, Any]:
    with state.task_lock:
        task = state.tasks.get(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        task.update(changes)
        task["updatedAt"] = _now_ms()
        return dict(task)


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
    try:
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
    except Exception as exc:
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
