"""Progress task state for memory model loading."""

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
        "id": "mem0-embedding-model",
        "kind": "model-download",
        "logs": [],
        "message": message,
        "phase": phase,
        "progress": progress,
        "result": None,
        "status": status,
        "title": "mem0 embedding model",
        "updatedAt": now,
    }


def set_mem0_task(**changes: Any) -> None:
    global _mem0_task
    now = int(time.time() * 1000)
    with _lock:
        task = dict(
            _mem0_task
            or _new_mem0_task(
                phase="queued",
                status="queued",
                message="Preparing mem0 embedding model.",
                progress=0,
            )
        )
        task.update(changes)
        task["updatedAt"] = now
        _mem0_task = task
    # DEBUG: log progress updates
    progress = changes.get("progress")
    phase = changes.get("phase")
    if progress is not None or phase:
        print(f"[mem0-task] set  progress={progress}  phase={phase}  "
              f"message={changes.get('message', '')[:80]}")


def current_mem0_task() -> dict[str, Any] | None:
    with _lock:
        return dict(_mem0_task) if _mem0_task is not None else None
