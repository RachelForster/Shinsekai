"""Chat turn admission, batching, and interruption orchestration.

This module owns the policy for accepting a new user turn.  It deliberately
depends on callbacks instead of concrete LLM, TTS, queue, or UI classes so the
same service can be used by the desktop UI, streamed frontend, and headless
runtime.
"""

from __future__ import annotations

from collections import deque
from contextlib import contextmanager, nullcontext
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
    pipeline_complete: threading.Event = field(compare=False, repr=False)

    def is_cancelled(self) -> bool:
        return self.cancelled.is_set()


AdmissionCallback = Callable[[str, list[dict[str, Any]]], None]


@dataclass(frozen=True)
class _Admission:
    text: str
    attachments: list[dict[str, Any]]
    on_admit: tuple[AdmissionCallback, ...] = field(default=(), compare=False, repr=False)
    cancellation_revision: int = field(default=0, compare=False, repr=False)
    utterance_id: str | None = None


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
        revision_sink: Callable[[str, list[dict[str, Any]], int, str | None], None] | None = None,
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
        self._revision_sink = revision_sink
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
        self._current_turn = TurnHandle(
            0,
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        self._deferred: deque[_Admission] = deque()
        self._priority_deferred: deque[_Admission] = deque()
        self._admission_reserved = False
        self._admission_revision: int | None = None
        # A direct sink write is visible to the worker before begin_turn() can
        # mark it active.  Keep deferred ASR finals behind that short window
        # without changing normal manual-submit routing.
        self._delivery_pending: deque[_Admission] = deque()
        self._completing = False
        # Every path that invokes an admission callback or the sink takes this
        # gate.  Reset and close take it first, so they cannot return while a
        # previously accepted admission can still reach a callback or sink.
        self._delivery_lock = threading.RLock()
        self._closed_event = threading.Event()
        self._cancellation_revision = 0
        self._retired_utterances: set[str] = set()
        self._utterance_batch_prefixes: dict[str, _Admission] = {}

        self._batch: list[_Admission] = []
        self._batch_deadline: float | None = None
        self._batch_timer: threading.Timer | None = None
        self._batch_revision = 0
        self._typing = False
        self._closed = False

    def submit(
        self,
        text: str,
        *,
        attachments: list[dict[str, Any]] | None = None,
        interrupt_current: bool | None = None,
        defer_until_idle: bool = False,
        on_admit: AdmissionCallback | None = None,
        utterance_id: str | None = None,
        replace_utterance_id: str | None = None,
    ) -> BatchState:
        """Accept one processed user message.

        When batching is disabled the message is delivered immediately.  In
        batch mode it is buffered and scheduled automatically, so non-Qt input
        sources do not require a UI timer to make progress.
        """
        value = str(text or "")
        attachment_payloads = list(attachments or [])
        if not value and not attachment_payloads:
            return self.batch_state()

        admission_callbacks = (on_admit,) if on_admit is not None else ()
        if replace_utterance_id:
            # Same gate as delivery: even a popped deferred admission cannot
            # escape retirement and appear after the manual replacement.
            with self._delivery_lock:
                with self._lock:
                    self._retired_utterances.add(replace_utterance_id)
                    # A final may have absorbed earlier typed batch fragments.
                    # Transfer those fragments to the manual replacement rather
                    # than discarding unrelated accepted input with the voice.
                    prefix = self._utterance_batch_prefixes.pop(replace_utterance_id, None)
                    if prefix is not None:
                        value = self.options.batch_separator.join(
                            part for part in (prefix.text, value) if part
                        )
                        attachment_payloads = prefix.attachments + attachment_payloads
                        admission_callbacks = prefix.on_admit + admission_callbacks
                    self._deferred = deque(
                        item for item in self._deferred
                        if item.utterance_id != replace_utterance_id
                    )
        if defer_until_idle:
            flushed_batch = False
            with self._lock:
                if self._closed or self._closed_event.is_set():
                    return self._batch_state_locked()
                if self._batch:
                    if utterance_id:
                        self._utterance_batch_prefixes[utterance_id] = self._new_admission_locked(
                            self.options.batch_separator.join(item.text for item in self._batch if item.text),
                            [attachment for item in self._batch for attachment in item.attachments],
                            tuple(callback for item in self._batch for callback in item.on_admit),
                        )
                    texts = [item.text for item in self._batch if item.text]
                    if value:
                        texts.append(value)
                    value = self.options.batch_separator.join(texts)
                    attachment_payloads = [
                        attachment
                        for item in self._batch
                        for attachment in item.attachments
                    ] + attachment_payloads
                    admission_callbacks = tuple(
                        callback
                        for item in self._batch
                        for callback in item.on_admit
                    ) + admission_callbacks
                    self._batch.clear()
                    self._typing = False
                    self._cancel_batch_timer_locked()
                    flushed_batch = True
                admission = self._new_admission_locked(
                    value,
                    attachment_payloads,
                    admission_callbacks,
                    utterance_id=utterance_id,
                )
                state = self._batch_state_locked()
            self._defer_or_deliver(admission)
            if flushed_batch:
                self._publish_state(state)
            return state

        should_interrupt = (
            self.options.interrupt_enabled
            if interrupt_current is None
            else bool(interrupt_current)
        )
        interrupt_claimed = False
        immediate_admission: _Admission | None = None
        state: BatchState | None = None
        with self._lock:
            if self._closed or self._closed_event.is_set():
                return self._batch_state_locked()
            if should_interrupt:
                if self._completing or (
                    self._admission_reserved and not self._active.is_set()
                ):
                    self._priority_deferred.append(
                        self._new_admission_locked(
                            value,
                            attachment_payloads,
                            admission_callbacks,
                        )
                    )
                    return self._batch_state_locked()
                if self._active.is_set():
                    turn = self._current_turn
                    turn.cancelled.set()
                    turn.pipeline_complete.set()
                    self._active.clear()
                    self._reserve_admission_locked()
                    interrupt_claimed = True
            admission = self._new_admission_locked(
                value,
                attachment_payloads,
                admission_callbacks,
            )
            if not self.options.batch_enabled:
                immediate_admission = admission
            else:
                self._batch.append(admission)
                self._typing = False
                self._schedule_flush_locked()
                state = self._batch_state_locked()
        if interrupt_claimed:
            self._run_interrupt_callbacks()

        if immediate_admission is not None:
            try:
                delivered = self._deliver(immediate_admission)
            except Exception:
                if interrupt_claimed:
                    self._release_admission_reservation(immediate_admission)
                raise
            if interrupt_claimed and not delivered:
                self._release_admission_reservation(immediate_admission)
            return self.batch_state()

        assert state is not None
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
        combined_callbacks: tuple[AdmissionCallback, ...] = ()
        admission: _Admission | None = None
        with self._lock:
            if self._closed or self._closed_event.is_set() or (
                expected_revision is not None and expected_revision != self._batch_revision
            ):
                return self._batch_state_locked()
            self._cancel_batch_timer_locked()
            self._typing = False
            if self._batch:
                combined = self.options.batch_separator.join(
                    item.text for item in self._batch if item.text
                )
                combined_attachments = [
                    attachment
                    for item in self._batch
                    for attachment in item.attachments
                ]
                combined_callbacks = tuple(
                    callback
                    for item in self._batch
                    for callback in item.on_admit
                )
                self._batch.clear()
            if combined or combined_attachments:
                admission = self._new_admission_locked(
                    combined,
                    combined_attachments,
                    combined_callbacks,
                )
        # Do not call callbacks or the sink under ``_lock``.  Reset and close
        # acquire the delivery gate before this method can expose the admission.
        if admission is not None:
            self._deliver(admission)
        with self._lock:
            state = self._batch_state_locked()
        self._publish_state(state)
        return state

    def cancel_pending_batch(self) -> BatchState:
        """Discard buffered and delivered-but-not-consumed batch input."""
        with self._delivery_lock:
            with self._lock:
                # A deferred item can be popped between finish_turn's two lock
                # sections.  Tagging it with this generation prevents that
                # stale object from being delivered after the reset returns.
                self._cancellation_revision += 1
                self._retired_utterances.clear()
                self._utterance_batch_prefixes.clear()
                self._cancel_batch_timer_locked()
                self._batch.clear()
                self._deferred.clear()
                self._priority_deferred.clear()
                self._clear_admission_reservation_locked()
                self._clear_delivery_pending_locked()
                self._completing = False
                self._typing = False
                state = self._batch_state_locked()
            # Keep cleanup in the same delivery section as callbacks and sink
            # writes, but never invoke it while holding the state lock.
            if self._clear_buffered_delivery is not None:
                try:
                    self._clear_buffered_delivery()
                except Exception:
                    logger.debug("chat turn buffered-delivery cleanup failed", exc_info=True)
        self._publish_state(state)
        return state

    @contextmanager
    def history_boundary(self):
        """Quiesce input admission and active work throughout history mutation."""
        with self._delivery_lock:
            with self._lock:
                self._current_turn.cancelled.set()
                self._current_turn.pipeline_complete.set()
                self._active.clear()
            self.cancel_pending_batch()
            self._run_interrupt_callbacks()
            yield

    def update_options(self, options: ChatTurnOptions) -> BatchState:
        """Apply a new admission policy without replacing the service.

        Disabling batching flushes already accepted fragments immediately so a
        settings change cannot strand user input.  Updating the timeout while a
        batch is pending reschedules it from the time of the change.
        """
        combined = ""
        combined_attachments: list[dict[str, Any]] = []
        combined_callbacks: tuple[AdmissionCallback, ...] = ()
        admission: _Admission | None = None
        with self._lock:
            if self._closed or self._closed_event.is_set():
                return self._batch_state_locked()
            previous = self.options
            self.options = options
            if previous.batch_enabled and not options.batch_enabled:
                self._cancel_batch_timer_locked()
                self._typing = False
                if self._batch:
                    combined = previous.batch_separator.join(
                        item.text for item in self._batch if item.text
                    )
                    combined_attachments = [
                        attachment
                        for item in self._batch
                        for attachment in item.attachments
                    ]
                    combined_callbacks = tuple(
                        callback
                        for item in self._batch
                        for callback in item.on_admit
                    )
                    self._batch.clear()
            elif options.batch_enabled and self._batch and not self._typing:
                self._schedule_flush_locked()
            if combined or combined_attachments:
                admission = self._new_admission_locked(
                    combined,
                    combined_attachments,
                    combined_callbacks,
                )
        if admission is not None:
            self._deliver(admission)
        with self._lock:
            state = self._batch_state_locked()
        self._publish_state(state)
        return state

    def batch_state(self) -> BatchState:
        with self._lock:
            return self._batch_state_locked()

    def begin_turn(self, *, expected_revision: int | None = None, utterance_id: str | None = None) -> TurnHandle:
        """Create and activate a cancellation identity for a worker turn."""
        # Closed workers must return immediately even while close is waiting
        # for a buffered-delivery cleanup callback.
        gate = nullcontext() if self._closed_event.is_set() else self._delivery_lock
        with gate, self._lock:
            self._turn_counter += 1
            handle = TurnHandle(
                self._turn_counter,
                threading.Event(),
                threading.Event(),
                threading.Event(),
            )
            if self._closed or self._closed_event.is_set() or (
                expected_revision is not None and expected_revision != self._cancellation_revision
            ) or utterance_id in self._retired_utterances:
                # A worker can dequeue its last input concurrently with close.
                # It must observe cancellation rather than revive service state.
                handle.cancelled.set()
                handle.pipeline_complete.set()
                if utterance_id:
                    self._delivery_pending = deque(
                        item for item in self._delivery_pending if item.utterance_id != utterance_id
                    )
                return handle
            self._current_turn = handle
            if utterance_id:
                self._utterance_batch_prefixes.pop(utterance_id, None)
            self._clear_admission_reservation_locked()
            if self._delivery_pending:
                self._delivery_pending.popleft()
            # A newly started turn supersedes any old finish callback that was
            # still publishing reply.finished outside the state lock.
            self._completing = False
            self._active.set()
            return handle

    def current_turn(self) -> TurnHandle:
        with self._lock:
            return self._current_turn

    @contextmanager
    def turn_publication(self, turn: TurnHandle):
        """Serialize a short UI-history write with history replacement."""
        with self._delivery_lock:
            yield not turn.is_cancelled()

    def mark_generation_complete(self, turn: TurnHandle) -> None:
        """Record that the LLM stage is no longer producing downstream work."""
        turn.generation_complete.set()

    def mark_idle(self, turn: TurnHandle | None = None) -> bool:
        """Mark the pipeline idle unless a newer turn has already started."""
        return self.finish_turn(turn)

    def finish_turn(
        self,
        turn: TurnHandle | None = None,
        *,
        before_next: Callable[[], None] | None = None,
    ) -> bool:
        """Complete one pipeline turn, then admit at most one deferred input."""
        deferred: _Admission | None = None
        with self._lock:
            candidate = turn or self._current_turn
            if candidate.id != self._current_turn.id:
                return False
            if not candidate.is_cancelled() and not candidate.generation_complete.is_set():
                return False
            if candidate.pipeline_complete.is_set():
                return False
            was_active = self._active.is_set() or self._admission_reserved
            if not was_active:
                return False
            candidate.pipeline_complete.set()
            self._active.clear()
            # Reserve the admission boundary while reply.finished is published.
            # ASR finals arriving in this window join the deferred FIFO.
            self._reserve_admission_locked()
            self._completing = True
            completion_turn_id = candidate.id
            completion_revision = self._cancellation_revision

        if before_next is not None:
            with self._lock:
                callback_is_current = self._completion_is_current_locked(
                    completion_turn_id,
                    completion_revision,
                )
            if callback_is_current:
                try:
                    before_next()
                except Exception:
                    logger.debug("chat turn completion callback failed", exc_info=True)

        with self._lock:
            if not self._completion_is_current_locked(
                completion_turn_id,
                completion_revision,
            ):
                return True
            self._completing = False
            # A normal input may already be sitting in the worker queue but
            # not have called begin_turn yet.  It owns the next turn, so leave
            # continuous finals deferred until that queued turn fully finishes.
            if self._delivery_pending:
                self._clear_admission_reservation_locked()
            else:
                deferred = self._pop_current_deferred_locked()
                if deferred is None:
                    self._clear_admission_reservation_locked()
                else:
                    self._admission_revision = deferred.cancellation_revision

        if deferred is not None:
            try:
                delivered = self._deliver(deferred)
            except Exception:
                self._release_admission_reservation(deferred)
                raise
            if not delivered:
                self._release_admission_reservation(deferred)
        return True

    def is_active(self) -> bool:
        with self._lock:
            if (
                self._active.is_set()
                or self._admission_reserved
                or self._delivery_pending
                or self._completing
            ):
                return True
        if self._has_pending_work is None:
            return False
        try:
            return bool(self._has_pending_work())
        except Exception:
            logger.debug("chat turn pending-work probe failed", exc_info=True)
            return False

    def interrupt(self, *, reserve_admission: bool = False) -> None:
        """Cancel the current turn and clear all downstream work."""
        with self._lock:
            turn = self._current_turn
            turn.cancelled.set()
            interruption_revision = self._cancellation_revision

        self._run_interrupt_callbacks()
        if reserve_admission:
            with self._lock:
                if (
                    not self._closed
                    and not self._closed_event.is_set()
                    and interruption_revision == self._cancellation_revision
                ):
                    turn.pipeline_complete.set()
                    self._active.clear()
                    self._reserve_admission_locked()
        else:
            self.finish_turn(turn)

    def _run_interrupt_callbacks(self) -> None:
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

    def close(self) -> None:
        """Stop pending timers and reject future batch scheduling."""
        # Publish this first so a delivery waiting for the gate cannot begin
        # ahead of a close request.  The gate then waits for an in-flight sink
        # call before the close is allowed to return.
        self._closed_event.set()
        with self._delivery_lock:
            with self._lock:
                if self._closed:
                    return
                self._closed = True
                self._cancellation_revision += 1
                self._utterance_batch_prefixes.clear()
                self._retired_utterances.clear()
                self._active.clear()
                self._cancel_batch_timer_locked()
                self._batch.clear()
                self._deferred.clear()
                self._priority_deferred.clear()
                self._clear_admission_reservation_locked()
                self._clear_delivery_pending_locked()
                self._completing = False
                self._typing = False
            if self._clear_buffered_delivery is not None:
                try:
                    self._clear_buffered_delivery()
                except Exception:
                    logger.debug("chat turn buffered-delivery cleanup failed", exc_info=True)

    def _new_admission_locked(
        self,
        text: str,
        attachments: list[dict[str, Any]],
        on_admit: tuple[AdmissionCallback, ...],
        *,
        utterance_id: str | None = None,
    ) -> _Admission:
        """Capture the branch-generation that accepted this input."""
        return _Admission(
            text,
            attachments,
            on_admit,
            cancellation_revision=self._cancellation_revision,
            utterance_id=utterance_id,
        )

    def _admission_is_current_locked(self, admission: _Admission) -> bool:
        return (
            not self._closed
            and not self._closed_event.is_set()
            and admission.cancellation_revision == self._cancellation_revision
            and admission.utterance_id not in self._retired_utterances
        )

    def _admission_is_current(self, admission: _Admission) -> bool:
        with self._lock:
            return self._admission_is_current_locked(admission)

    def _completion_is_current_locked(self, turn_id: int, revision: int) -> bool:
        return (
            not self._closed
            and not self._closed_event.is_set()
            and self._completing
            and self._current_turn.id == turn_id
            and self._cancellation_revision == revision
        )

    def _reserve_admission_locked(self) -> None:
        self._admission_reserved = True
        self._admission_revision = self._cancellation_revision

    def _clear_admission_reservation_locked(self) -> None:
        self._admission_reserved = False
        self._admission_revision = None

    def _mark_delivery_pending_locked(self, admission: _Admission) -> None:
        self._delivery_pending.append(admission)

    def _discard_delivery_pending_locked(self, admission: _Admission) -> None:
        for index, pending in enumerate(self._delivery_pending):
            if pending is admission:
                del self._delivery_pending[index]
                return

    def _discard_delivery_pending(self, admission: _Admission) -> None:
        with self._lock:
            self._discard_delivery_pending_locked(admission)

    def _clear_delivery_pending_locked(self) -> None:
        self._delivery_pending.clear()

    def _release_admission_reservation(self, admission: _Admission) -> None:
        """Release only the reservation attached to a failed old admission."""
        with self._lock:
            if (
                self._admission_reserved
                and self._admission_revision == admission.cancellation_revision
            ):
                self._clear_admission_reservation_locked()

    def _pop_current_deferred_locked(self) -> _Admission | None:
        for queue in (self._priority_deferred, self._deferred):
            while queue:
                admission = queue.popleft()
                if self._admission_is_current_locked(admission):
                    return admission
        return None

    def _defer_or_deliver(self, admission: _Admission) -> None:
        with self._lock:
            if not self._admission_is_current_locked(admission):
                return
            if (
                self._active.is_set()
                or self._admission_reserved
                or self._delivery_pending
                or self._completing
            ):
                self._deferred.append(admission)
                return
            self._reserve_admission_locked()
        try:
            delivered = self._deliver(admission)
        except Exception:
            self._release_admission_reservation(admission)
            raise
        if not delivered:
            self._release_admission_reservation(admission)

    def _deliver(self, admission: _Admission) -> bool:
        with self._delivery_lock:
            with self._lock:
                if not self._admission_is_current_locked(admission):
                    return False
                # Set this before callbacks or sink delivery.  A worker may
                # begin immediately after the sink write, while a concurrent
                # continuous final must continue to wait in either case.
                self._mark_delivery_pending_locked(admission)
            # Publish the committed user-turn presentation before exposing the
            # queue item to a worker thread that may immediately start output.
            try:
                for callback in admission.on_admit:
                    if not self._admission_is_current(admission):
                        self._discard_delivery_pending(admission)
                        return False
                    try:
                        callback(admission.text, admission.attachments)
                    except Exception:
                        logger.debug("chat turn message admission callback failed", exc_info=True)
                if not self._admission_is_current(admission):
                    self._discard_delivery_pending(admission)
                    return False
                if self._revision_sink is not None:
                    self._revision_sink(admission.text, admission.attachments, admission.cancellation_revision, admission.utterance_id)
                elif admission.attachments:
                    self._sink(admission.text, attachments=admission.attachments)
                else:
                    self._sink(admission.text)
            except Exception:
                self._discard_delivery_pending(admission)
                raise
            return True

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
                item.text
                or " ".join(
                    f"[{attachment.get('kind', 'file')}: {attachment.get('name', 'attachment')}]"
                    for attachment in item.attachments
                )
                for item in self._batch
            ),
            remaining_seconds=remaining,
            scheduled=deadline is not None,
            typing=self._typing,
        )
