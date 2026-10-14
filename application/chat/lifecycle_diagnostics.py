"""Optional structured diagnostics observe lifecycle without controlling cleanup."""

from __future__ import annotations

from collections.abc import Callable
import logging
import threading
import time

from sdk.chat_process import ChatProcessContext, ChatProcessEvent
from sdk.chat_session import ChatSessionContext

logger = logging.getLogger(__name__)


class LifecycleDiagnostics:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._started: dict[str, float] = {}

    def __call__(self, context: ChatProcessContext | ChatSessionContext) -> None:
        now = self.clock()
        with self._lock:
            if (
                isinstance(context, ChatProcessContext)
                and context.event is ChatProcessEvent.STARTING
            ):
                self._started[context.launch_id] = now
            started = self._started.get(context.launch_id)
            if isinstance(context, ChatProcessContext) and context.event in {
                ChatProcessEvent.STOPPED,
                ChatProcessEvent.FAILED,
            }:
                self._started.pop(context.launch_id, None)
        logger.info(
            "Chat lifecycle transition",
            extra={
                "event": context.event.value,
                "session_id": context.session_id,
                "launch_id": context.launch_id,
                "pid": getattr(context, "pid", None),
                "exit_code": getattr(context, "exit_code", None),
                "duration_ms": (
                    round((now - started) * 1000, 2) if started is not None else None
                ),
                "error_type": (
                    type(context.error).__name__ if context.error is not None else ""
                ),
            },
        )
