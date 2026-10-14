"""Progress task state for knowledge model loading."""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_mem0_task: dict[str, Any] | None = None


def _new_mem0_task(*, phase: str, status: str, message: str, progress: float | None) -> dict[str, Any]:
    now = int(time.time() * 1000)
    return {
        "createdAt": now,
        "error": "",
        "id": "knowledge-embedding-model",
        "kind": "model-download",
        "logs": [],
        "message": message,
        "phase": phase,
        "progress": progress,
        "result": None,
        "status": status,
        "title": "Knowledge embedding model",
        "updatedAt": now,
    }


def set_mem0_task(*, reset: bool = False, **changes: Any) -> None:
    global _mem0_task
    now = int(time.time() * 1000)
    with _lock:
        task = dict(
            (None if reset else _mem0_task)
            or _new_mem0_task(
                phase="queued",
                status="queued",
                message="Preparing Knowledge embedding model.",
                progress=0,
            )
        )
        task.update(changes)
        task["updatedAt"] = now
        _mem0_task = task


def current_mem0_task() -> dict[str, Any] | None:
    with _lock:
        return dict(_mem0_task) if _mem0_task is not None else None
