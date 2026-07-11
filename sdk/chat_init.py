"""Shared chat-initialization progress and cancellation primitives.

The chat runtime is a separate process, so initialization work reports plain
dictionary events that can be forwarded over the existing chat event stream.
The embedded ``task`` intentionally follows the frontend ``TaskSnapshot``
shape, allowing launch UIs to reuse the generic progress presentation.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sdk.plugin_host_context import PluginHostContext

logger = logging.getLogger(__name__)

ChatInitEventEmitter = Callable[[dict[str, Any]], None]


class InitChatCancelled(RuntimeError):
    """Raised when chat initialization has been cancelled."""


class InitChatCancellationToken:
    """Thread-safe cooperative cancellation token for initialization hooks."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason = ""
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def cancel(self, reason: str = "Chat initialization was cancelled.") -> None:
        with self._lock:
            if not self._reason:
                self._reason = str(reason or "Chat initialization was cancelled.")
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise InitChatCancelled(self.reason or "Chat initialization was cancelled.")


class ChatInitService:
    """Own a TaskSnapshot-compatible initialization task and emit its updates.

    Numeric progress is clamped to ``0..1`` and is monotonic. Calls with
    ``progress=None`` update phase/message/logs without discarding the last
    known numeric value.
    """

    def __init__(
        self,
        emit: ChatInitEventEmitter | None = None,
        *,
        task_id: str = "",
        title: str = "Starting chat",
        log_limit: int = 120,
    ) -> None:
        now = self._now_ms()
        self._emit = emit
        self._log_limit = max(0, int(log_limit))
        self._lock = threading.RLock()
        self._terminal = False
        self._task: dict[str, Any] = {
            "createdAt": now,
            "error": "",
            "id": str(task_id or f"chat-init-{uuid.uuid4().hex}"),
            "kind": "chat-initialization",
            "logs": [],
            "message": "Preparing chat runtime.",
            "phase": "queued",
            "progress": 0.0,
            "result": None,
            "status": "queued",
            "title": str(title or "Starting chat"),
            "updatedAt": now,
        }

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            task = dict(self._task)
            task["logs"] = list(self._task.get("logs") or [])
            return task

    def start(self, message: str = "Preparing chat runtime.") -> dict[str, Any]:
        return self.report(progress=0.0, phase="preparing", message=message)

    def report(
        self,
        *,
        progress: float | None = None,
        phase: str | None = None,
        message: str | None = None,
        log: str | None = None,
        logs: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Update and emit a running initialization snapshot."""

        with self._lock:
            if self._terminal:
                return self.snapshot()
            if self._task["status"] == "queued":
                self._task["status"] = "running"
            if progress is not None:
                try:
                    raw_progress = float(progress)
                    if not math.isfinite(raw_progress):
                        raise ValueError("progress must be finite")
                    normalized = min(1.0, max(0.0, raw_progress))
                except (TypeError, ValueError):
                    normalized = float(self._task.get("progress") or 0.0)
                previous = float(self._task.get("progress") or 0.0)
                self._task["progress"] = max(previous, normalized)
            if phase is not None:
                self._task["phase"] = str(phase or "running")
            if message is not None:
                self._task["message"] = str(message)
            self._append_logs_locked([log] if log is not None else [])
            self._append_logs_locked(logs or [])
            self._task["updatedAt"] = self._now_ms()
            task = self.snapshot()
        self._emit_task("chat.init.progress", task)
        return task

    def phase_started(
        self,
        phase: str,
        message: str = "",
        *,
        progress: float | None = None,
    ) -> dict[str, Any]:
        return self.report(
            phase=phase,
            message=message or f"Starting {phase}.",
            progress=progress,
        )

    def phase_completed(
        self,
        phase: str,
        message: str = "",
        *,
        progress: float | None = None,
    ) -> dict[str, Any]:
        return self.report(
            phase=phase,
            message=message or f"Completed {phase}.",
            progress=progress,
        )

    def completed(self, message: str = "Chat is ready.", *, result: Any = None) -> dict[str, Any]:
        with self._lock:
            if self._terminal:
                return self.snapshot()
            self._terminal = True
            self._task.update(
                {
                    "error": "",
                    "message": str(message),
                    "phase": "completed",
                    "progress": 1.0,
                    "result": result,
                    "status": "succeeded",
                    "updatedAt": self._now_ms(),
                }
            )
            task = self.snapshot()
        self._emit_task("chat.init.completed", task)
        return task

    def failed(self, error: BaseException | str, *, message: str = "") -> dict[str, Any]:
        detail = str(error or "Chat initialization failed.")
        with self._lock:
            if self._terminal:
                return self.snapshot()
            self._terminal = True
            self._task.update(
                {
                    "error": detail,
                    "message": str(message or detail),
                    "phase": "failed",
                    "status": "failed",
                    "updatedAt": self._now_ms(),
                }
            )
            task = self.snapshot()
        self._emit_task("chat.init.failed", task)
        return task

    def cancelled(self, message: str = "Chat initialization was cancelled.") -> dict[str, Any]:
        with self._lock:
            if self._terminal:
                return self.snapshot()
            self._terminal = True
            self._task.update(
                {
                    "message": str(message),
                    "phase": "cancelled",
                    "status": "cancelled",
                    "updatedAt": self._now_ms(),
                }
            )
            task = self.snapshot()
        self._emit_task("chat.init.cancelled", task)
        return task

    def _append_logs_locked(self, values: Iterable[str | None]) -> None:
        if self._log_limit <= 0:
            return
        current = list(self._task.get("logs") or [])
        for value in values:
            line = str(value or "").strip()
            if not line:
                continue
            # Progress producers commonly resend their entire log tail. Avoid
            # multiplying identical adjacent entries on every poll.
            if current and current[-1] == line:
                continue
            current.append(line)
        self._task["logs"] = current[-self._log_limit :]

    def _emit_task(self, event_type: str, task: dict[str, Any]) -> None:
        if self._emit is None:
            return
        try:
            self._emit({"type": event_type, "task": task})
        except Exception:
            logger.warning("chat initialization progress emitter failed", exc_info=True)


@dataclass(frozen=True)
class InitChatContext:
    """Read-only launch context plus a progress range scoped to one step.

    Hook progress is local to the context: ``0`` maps to ``_progress_start``
    and ``1`` maps to ``_progress_end``. The dispatcher composes nested ranges
    to allocate deterministic weighted intervals to individual hooks.
    """

    service: ChatInitService
    session_id: str = ""
    character_names: tuple[str, ...] = ()
    tts_provider: str = ""
    voice_language: str = ""
    memory_enabled: bool = False
    runtime_mode: str = ""
    headless: bool = False
    host: PluginHostContext | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    cancellation: InitChatCancellationToken = field(default_factory=InitChatCancellationToken)
    _progress_start: float = field(default=0.0, repr=False)
    _progress_end: float = field(default=1.0, repr=False)

    @property
    def cancelled(self) -> bool:
        return self.cancellation.cancelled

    def raise_if_cancelled(self) -> None:
        self.cancellation.raise_if_cancelled()

    def scaled(self, start: float, end: float) -> InitChatContext:
        """Return a child context mapped into a local ``start..end`` range."""

        raw_start = float(start)
        raw_end = float(end)
        if not math.isfinite(raw_start) or not math.isfinite(raw_end):
            raise ValueError("chat init progress range must be finite")
        local_start = min(1.0, max(0.0, raw_start))
        local_end = min(1.0, max(0.0, raw_end))
        if local_end < local_start:
            raise ValueError("chat init progress range end must be >= start")
        span = self._progress_end - self._progress_start
        return replace(
            self,
            _progress_start=self._progress_start + span * local_start,
            _progress_end=self._progress_start + span * local_end,
        )

    def report(
        self,
        progress: float | None = None,
        message: str | None = None,
        *,
        phase: str | None = None,
        log: str | None = None,
        logs: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        self.raise_if_cancelled()
        scaled_progress = None
        if progress is not None:
            raw_progress = float(progress)
            if not math.isfinite(raw_progress):
                raise ValueError("chat init progress must be finite")
            local = min(1.0, max(0.0, raw_progress))
            scaled_progress = self._progress_start + (self._progress_end - self._progress_start) * local
        return self.service.report(
            progress=scaled_progress,
            phase=phase,
            message=message,
            log=log,
            logs=logs,
        )

    def phase_started(self, phase: str, message: str = "") -> dict[str, Any]:
        return self.report(0.0, message or f"Starting {phase}.", phase=phase)

    def phase_completed(self, phase: str, message: str = "") -> dict[str, Any]:
        return self.report(1.0, message or f"Completed {phase}.", phase=phase)
