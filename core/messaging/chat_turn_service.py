"""Chat turn admission, batching, and interruption orchestration.

This module owns the policy for accepting a new user turn.  It deliberately
depends on callbacks instead of concrete LLM, TTS, queue, or UI classes so the
same service can be used by the desktop UI, streamed frontend, and headless
runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
import threading
import time
from typing import Any, Callable, Iterable


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatTurnOptions:
    """Runtime policy for new user turns."""

    interrupt_enabled: bool = True
    batch_enabled: bool = False
    batch_idle_seconds: float = 5.0
    batch_separator: str = "\n---\n"


@dataclass(frozen=True)
class BatchState:
    """Presentation-neutral snapshot of pending batch input."""

    enabled: bool
    pending_count: int
    pending_messages: tuple[str, ...]
    remaining_seconds: int | None
    scheduled: bool
    typing: bool


@dataclass(frozen=True)
class TurnHandle:
    """Cancellation identity captured by each pipeline stage."""

    id: int
    cancelled: threading.Event = field(compare=False, repr=False)
    generation_complete: threading.Event = field(compare=False, repr=False)

    def is_cancelled(self) -> bool:
        return self.cancelled.is_set()


class ChatTurnService:
    """Coordinate user input batching and interruption of the active turn.

    The service never imports Qt or application managers.  Runtime composition
    supplies small callbacks for queue delivery, LLM cancellation, playback,
    and status cleanup.
    """

    def __init__(
        self,
        *,
        sink: Callable[..., None] | None = None,
        options: ChatTurnOptions | None = None,
        on_state_change: Callable[[BatchState], None] | None = None,
        cancel_current: Callable[[], None] | None = None,
        clear_buffered_delivery: Callable[[], None] | None = None,
        clear_pending: Iterable[Callable[[], None]] = (),
        stop_playback: Callable[[], None] | None = None,
        hide_status: Callable[[], None] | None = None,
        has_pending_work: Callable[[], bool] | None = None,
    ) -> None:
        self._sink = sink or (lambda _text: None)
        self.options = options or ChatTurnOptions(interrupt_enabled=False)
        self._on_state_change = on_state_change
        self._cancel_current = cancel_current
        self._clear_buffered_delivery = clear_buffered_delivery
        self._clear_pending = tuple(clear_pending)
        self._stop_playback = stop_playback
        self._hide_status = hide_status
        self._has_pending_work = has_pending_work

        self._lock = threading.RLock()
        self._active = threading.Event()
        self._turn_counter = 0
        self._current_turn = TurnHandle(0, threading.Event(), threading.Event())

        self._batch: list[tuple[str, list[dict[str, Any]]]] = []
        self._batch_deadline: float | None = None
        self._batch_timer: threading.Timer | None = None
        self._batch_revision = 0
        self._typing = False
        self._closed = False

    def submit(self, text: str, *, attachments: list[dict[str, Any]] | None = None) -> BatchState:
        """Accept one processed user message.

        When batching is disabled the message is delivered immediately.  In
        batch mode it is buffered and scheduled automatically, so non-Qt input
        sources do not require a UI timer to make progress.
        """
        value = str(text or "")
        attachment_payloads = list(attachments or [])
        if not value and not attachment_payloads:
            return self.batch_state()

        if self.options.interrupt_enabled and self.is_active():
            self.interrupt()

        if not self.options.batch_enabled:
            self._deliver(value, attachment_payloads)
            return self.batch_state()

        with self._lock:
            if self._closed:
                return self._batch_state_locked()
            self._batch.append((value, attachment_payloads))
            self._typing = False
            self._schedule_flush_locked()
            state = self._batch_state_locked()
        self._publish_state(state)
        return state

    def input_changed(self, *, has_text: bool, composing: bool = False) -> BatchState:
        """Update input activity without exposing UI details to the service."""
        if not self.options.batch_enabled:
            return self.batch_state()
        with self._lock:
            self._typing = bool(has_text or composing) and bool(self._batch)
            if has_text or composing:
                self._cancel_batch_timer_locked()
            elif self._batch:
                self._schedule_flush_locked()
            state = self._batch_state_locked()
        self._publish_state(state)
        return state

    def flush(self) -> BatchState:
        """Deliver all buffered messages as one user turn."""
        return self._flush(expected_revision=None)

    def _flush(self, *, expected_revision: int | None) -> BatchState:
        combined = ""
        combined_attachments: list[dict[str, Any]] = []
        with self._lock:
            if self._closed or (
                expected_revision is not None and expected_revision != self._batch_revision
            ):
                return self._batch_state_locked()
            self._cancel_batch_timer_locked()
            self._typing = False
            if self._batch:
                combined = self.options.batch_separator.join(
                    text for text, _attachments in self._batch if text
                )
                combined_attachments = [
                    attachment
                    for _text, attachments in self._batch
                    for attachment in attachments
                ]
                self._batch.clear()
            # Serialize delivery with cancellation. A history boundary can then
            # invalidate the timer and clear a just-delivered queue item before
            # mutating the active branch.
            if combined or combined_attachments:
                self._deliver(combined, combined_attachments)
            state = self._batch_state_locked()
        self._publish_state(state)
        return state

    def cancel_pending_batch(self) -> BatchState:
        """Discard buffered and delivered-but-not-consumed batch input."""
        with self._lock:
            self._cancel_batch_timer_locked()
            self._batch.clear()
            self._typing = False
            if self._clear_buffered_delivery is not None:
                try:
                    self._clear_buffered_delivery()
                except Exception:
                    logger.debug("chat turn buffered-delivery cleanup failed", exc_info=True)
            state = self._batch_state_locked()
        self._publish_state(state)
        return state

    def update_options(self, options: ChatTurnOptions) -> BatchState:
        """Apply a new admission policy without replacing the service.

        Disabling batching flushes already accepted fragments immediately so a
        settings change cannot strand user input.  Updating the timeout while a
        batch is pending reschedules it from the time of the change.
        """
        combined = ""
        combined_attachments: list[dict[str, Any]] = []
        with self._lock:
            previous = self.options
            self.options = options
            if previous.batch_enabled and not options.batch_enabled:
                self._cancel_batch_timer_locked()
                self._typing = False
                if self._batch:
                    combined = previous.batch_separator.join(
                        text for text, _attachments in self._batch if text
                    )
                    combined_attachments = [
                        attachment
                        for _text, attachments in self._batch
                        for attachment in attachments
                    ]
                    self._batch.clear()
            elif options.batch_enabled and self._batch and not self._typing:
                self._schedule_flush_locked()
            if combined or combined_attachments:
                self._deliver(combined, combined_attachments)
            state = self._batch_state_locked()
        self._publish_state(state)
        return state

    def batch_state(self) -> BatchState:
        with self._lock:
            return self._batch_state_locked()

    def begin_turn(self) -> TurnHandle:
        """Create and activate a cancellation identity for a worker turn."""
        with self._lock:
            self._turn_counter += 1
            handle = TurnHandle(self._turn_counter, threading.Event(), threading.Event())
            self._current_turn = handle
            self._active.set()
            return handle

    def current_turn(self) -> TurnHandle:
        with self._lock:
            return self._current_turn

    def mark_generation_complete(self, turn: TurnHandle) -> None:
        """Record that the LLM stage is no longer producing downstream work."""
        turn.generation_complete.set()

    def mark_idle(self, turn: TurnHandle | None = None) -> None:
        """Mark the pipeline idle unless a newer turn has already started."""
        with self._lock:
            candidate = turn or self._current_turn
            if candidate.id != self._current_turn.id:
                return
            if not candidate.is_cancelled() and not candidate.generation_complete.is_set():
                return
            self._active.clear()

    def is_active(self) -> bool:
        if self._active.is_set():
            return True
        if self._has_pending_work is None:
            return False
        try:
            return bool(self._has_pending_work())
        except Exception:
            logger.debug("chat turn pending-work probe failed", exc_info=True)
            return False

    def interrupt(self) -> None:
        """Cancel the current turn and clear all downstream work."""
        with self._lock:
            turn = self._current_turn
            turn.cancelled.set()

        callbacks = (
            self._cancel_current,
            *self._clear_pending,
            self._stop_playback,
            self._hide_status,
        )
        for callback in callbacks:
            if callback is None:
                continue
            try:
                callback()
            except Exception:
                logger.debug("chat turn interrupt callback failed", exc_info=True)
        self.mark_idle(turn)

    def close(self) -> None:
        """Stop pending timers and reject future batch scheduling."""
        with self._lock:
            self._closed = True
            self._cancel_batch_timer_locked()

    def _deliver(self, text: str, attachments: list[dict[str, Any]]) -> None:
        if attachments:
            self._sink(text, attachments=attachments)
        else:
            self._sink(text)

    def _publish_state(self, state: BatchState) -> None:
        callback = self._on_state_change
        if callback is None:
            return
        try:
            callback(state)
        except Exception:
            logger.debug("chat turn state callback failed", exc_info=True)

    def _schedule_flush_locked(self) -> None:
        self._cancel_batch_timer_locked()
        delay = max(0.01, float(self.options.batch_idle_seconds))
        self._batch_deadline = time.monotonic() + delay
        revision = self._batch_revision
        timer = threading.Timer(delay, self._flush, kwargs={"expected_revision": revision})
        timer.daemon = True
        self._batch_timer = timer
        timer.start()

    def _cancel_batch_timer_locked(self) -> None:
        self._batch_revision += 1
        timer = self._batch_timer
        self._batch_timer = None
        self._batch_deadline = None
        if timer is not None:
            timer.cancel()

    def _batch_state_locked(self) -> BatchState:
        deadline = self._batch_deadline
        remaining = None
        if deadline is not None:
            remaining = max(0, math.ceil(deadline - time.monotonic()))
        return BatchState(
            enabled=self.options.batch_enabled,
            pending_count=len(self._batch),
            pending_messages=tuple(
                text
                or " ".join(
                    f"[{attachment.get('kind', 'file')}: {attachment.get('name', 'attachment')}]"
                    for attachment in attachments
                )
                for text, attachments in self._batch
            ),
            remaining_seconds=remaining,
            scheduled=deadline is not None,
            typing=self._typing,
        )
