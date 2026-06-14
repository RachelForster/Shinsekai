"""
Input batcher: accumulates user messages and flushes when the input box
stays empty for *idle_seconds* after the last submit.

Explicit ``Ctrl+Enter`` always commits immediately regardless of the timer.
The countdown is driven externally by a QTimer — this module is pure Python
and stays free of Qt dependencies.
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional

from sdk.logging import get_logger
from sdk.messages import UserInputMessage

logger = get_logger(__name__)


class InputBatcher:
    """Accumulates messages.

    Call :meth:`submit` when the user sends a message.
    Call :meth:`schedule_flush` when the input box becomes empty to start
    the idle countdown.  Call :meth:`on_countdown_tick` every second; when
    it returns ``True`` the buffer should be flushed immediately.
    Call :meth:`on_user_typing` when the user resumes typing to cancel.
    """

    def __init__(
        self,
        sink: Callable[[UserInputMessage], None],
        *,
        idle_seconds: float = 3.0,
        separator: str = "\n",
        enabled_factory: Optional[Callable[[], bool]] = None,
        history_callback: Optional[Callable[[List[str]], None]] = None,
        tick_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._sink = sink
        self._idle_seconds = max(1, int(idle_seconds))
        self._separator = separator
        self._enabled_factory = enabled_factory or (lambda: True)
        self._history_cb = history_callback
        self._tick_cb = tick_callback
        self._buffer: List[str] = []
        self._lock = threading.Lock()
        self._countdown: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(self, text: str) -> None:
        """Buffer a user message.  Resets any pending countdown."""
        if not self._enabled_factory():
            self._sink(UserInputMessage(text=text))
            return

        with self._lock:
            self._buffer.append(text)
            self._countdown = 0

    def schedule_flush(self) -> None:
        """Start the idle countdown (called when input box becomes empty)."""
        with self._lock:
            if not self._buffer:
                return
            self._countdown = self._idle_seconds
            self._notify_tick_locked()

    def on_countdown_tick(self) -> bool:
        """Called once per second by an external QTimer.

        Returns ``True`` when the countdown reached zero and the buffer
        should be flushed immediately.
        """
        with self._lock:
            if self._countdown <= 0 or not self._buffer:
                return False
            self._countdown -= 1
            if self._countdown > 0:
                self._notify_tick_locked()
                return False
            # countdown reached 0 — caller MUST flush
            return True

    def on_user_typing(self) -> str:
        """User is typing — cancel countdown, return indicator text."""
        with self._lock:
            self._countdown = 0
            return "[正在输入…]" if self._buffer else ""

    def flush(self) -> None:
        """Immediately flush all buffered messages."""
        combined: Optional[str] = None
        buffer_copy: List[str] = []
        with self._lock:
            self._countdown = 0
            if self._buffer:
                combined = self._separator.join(self._buffer)
                buffer_copy = list(self._buffer)
                self._buffer.clear()

        if combined:
            if self._history_cb and buffer_copy:
                try:
                    self._history_cb(buffer_copy)
                except Exception:
                    pass
            # Hide countdown indicator
            if self._tick_cb:
                try:
                    self._tick_cb("")
                except Exception:
                    pass
            self._sink(UserInputMessage(text=combined))

    def cancel(self) -> None:
        """Discard all buffered messages."""
        with self._lock:
            self._countdown = 0
            self._buffer.clear()

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._buffer)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _notify_tick_locked(self) -> None:
        if self._tick_cb:
            n = self._countdown
            text = f"[正在输入…{n}]" if n > 0 else ""
            try:
                self._tick_cb(text)
            except Exception:
                pass
