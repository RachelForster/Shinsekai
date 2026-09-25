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
from typing import TYPE_CHECKING, Any, Callable, Iterable

if TYPE_CHECKING:
    from core.messaging.continuous_asr_policy import ContinuousASRPolicy
from uuid import uuid4


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
    defer_until_idle: bool = False
    parts: tuple[_Admission, ...] = field(default=(), compare=False, repr=False)


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
        continuous_policy: ContinuousASRPolicy[_Admission] | None = None,
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
        self.continuous_policy = continuous_policy
        # Delivery and turn lifecycle belong to the host, including the gap
        # between enqueueing an input and the worker starting its turn.
        self._delivery_pending: deque[_Admission] = deque()
        self._admission_reserved = False
        self._batch_interrupt_reserved = False
        self._admission_revision: int | None = None
        self._reserved_admission: _Admission | None = None
        self._completing = False
        self._input_activity: dict[str, bool] = {}
        # Every path that invokes an admission callback or the sink takes this
        # gate.  Reset and close take it first, so they cannot return while a
        # previously accepted admission can still reach a callback or sink.
        self._delivery_lock = threading.RLock()
        self._closed_event = threading.Event()
        self._cancellation_revision = 0

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

        if (defer_until_idle or utterance_id or replace_utterance_id) and self.continuous_policy is None:
            raise ValueError("Continuous ASR input requires an enabled session policy")
        admission_callbacks = (on_admit,) if on_admit is not None else ()
        # Keep retirement and replacement in the same delivery gate. A batch
        # may already have left the deferred queue, or reached the worker queue.
        with self._delivery_lock if replace_utterance_id else nullcontext():
            with self._lock:
                if self._closed or self._closed_event.is_set():
                    return self._batch_state_locked()
                remainder = (self._retire_utterance_locked(replace_utterance_id)
                             if self.continuous_policy is not None else ())
                admission = self._new_admission_locked(
                    value, attachment_payloads, admission_callbacks,
                    utterance_id=utterance_id, defer_until_idle=defer_until_idle,
                )
                if remainder:
                    admission = self._combine_admissions_locked((*remainder, admission))
            return self._submit_admission(
                admission, interrupt_current=interrupt_current,
                input_source="asr" if defer_until_idle else "manual",
            )

    def _submit_admission(
        self, admission: _Admission, *, interrupt_current: bool | None, input_source: str,
    ) -> BatchState:
        should_interrupt = not admission.defer_until_idle and (
            self.options.interrupt_enabled if interrupt_current is None else bool(interrupt_current)
        )
        # Ordinary submissions retain upstream immediate admission and pending
        # presentation interruption, even while a previous completion is running.
        with self._delivery_lock:
            with self._lock:
                if not self._admission_is_current_locked(admission):
                    return self._batch_state_locked()
            interrupt_claimed = False
            if should_interrupt and self._pipeline_has_work():
                if self.continuous_policy is None:
                    self.interrupt()
                else:
                    with self._lock:
                        self._current_turn.cancelled.set()
                        self._current_turn.pipeline_complete.set()
                        self._active.clear()
                        self._reserve_admission_locked(admission)
                        self._batch_interrupt_reserved = self.options.batch_enabled
                    interrupt_claimed = True
            with self._lock:
                if not self._admission_is_current_locked(admission):
                    return self._batch_state_locked()
                policy = self.continuous_policy
                if policy is not None:
                    self._input_activity.pop(input_source, None)
                if self.options.batch_enabled:
                    self._batch.append(admission)
                    self._typing = bool(policy and any(self._input_activity.values()))
                    if not self._typing:
                        self._schedule_flush_locked()
                    state = self._batch_state_locked()
                else:
                    state = None
            if interrupt_claimed:
                self._run_interrupt_callbacks()
            if state is None:
                try:
                    self._route_admission(admission)
                except Exception:
                    if policy is not None:
                        self._release_admission_reservation(admission)
                    raise
                return self.batch_state()
        self._publish_state(state)
        return state

    def input_changed(
        self, *, has_text: bool, composing: bool = False, source: str = "manual",
    ) -> BatchState:
        if not self.options.batch_enabled:
            return self.batch_state()
        with self._lock:
            active = bool(has_text or composing)
            if self.continuous_policy is not None:
                self._input_activity[source] = active
                active = any(self._input_activity.values())
            self._typing = active and bool(self._batch)
            if active:
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
        admission: _Admission | None = None
        with self._lock:
            if self._closed or self._closed_event.is_set() or (
                expected_revision is not None and expected_revision != self._batch_revision
            ):
                return self._batch_state_locked()
            self._cancel_batch_timer_locked()
            self._typing = False
            if self.continuous_policy is not None:
                self._input_activity.clear()
            if self._batch:
                admission = self._combine_admissions_locked(self._batch)
                self._batch.clear()
                if self.continuous_policy is not None and self._batch_interrupt_reserved:
                    self._clear_admission_reservation_locked()
        # Reset and close can revoke this admission before delivery begins.
        if admission is not None:
            self._route_admission(admission)
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
                self._cancel_batch_timer_locked()
                self._batch.clear()
                if self.continuous_policy is not None:
                    self.continuous_policy.invalidate()
                    self._delivery_pending.clear()
                    self._input_activity.clear()
                    self._clear_admission_reservation_locked()
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
        admission: _Admission | None = None
        with self._lock:
            if self._closed or self._closed_event.is_set():
                return self._batch_state_locked()
            previous = self.options
            self.options = options
            if previous.batch_enabled and not options.batch_enabled:
                self._cancel_batch_timer_locked()
                self._typing = False
                if self.continuous_policy is not None:
                    self._input_activity.clear()
                if self._batch:
                    admission = self._combine_admissions_locked(
                        self._batch, separator=previous.batch_separator,
                    )
                    self._batch.clear()
                    if self.continuous_policy is not None and self._batch_interrupt_reserved:
                        self._clear_admission_reservation_locked()
            elif options.batch_enabled and self._batch and not self._typing:
                self._schedule_flush_locked()
        if admission is not None:
            self._route_admission(admission)
        with self._lock:
            state = self._batch_state_locked()
        self._publish_state(state)
        return state

    def batch_state(self) -> BatchState:
        with self._lock:
            return self._batch_state_locked()

    def begin_turn(self, *, expected_revision: int | None = None, utterance_id: str | None = None) -> TurnHandle:
        gate = nullcontext() if self._closed_event.is_set() else self._delivery_lock
        with gate, self._lock:
            self._turn_counter += 1
            handle = TurnHandle(self._turn_counter, threading.Event(), threading.Event(), threading.Event())
            policy = self.continuous_policy
            if self._closed or self._closed_event.is_set() or (
                expected_revision is not None and expected_revision != self._cancellation_revision
            ) or (policy is not None and policy.is_retired(utterance_id)):
                handle.cancelled.set()
                handle.pipeline_complete.set()
                if policy is not None:
                    self._delivery_pending = deque(
                        item for item in self._delivery_pending if item.utterance_id != utterance_id
                    )
                return handle
            self._current_turn = handle
            if policy is not None:
                admitted_id = utterance_id or (
                    self._delivery_pending[0].utterance_id if self._delivery_pending else None
                )
                policy.begin_turn(admitted_id)
                self._clear_admission_reservation_locked()
                if self._delivery_pending:
                    self._delivery_pending.popleft()
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
            yield not self._closed_event.is_set() and not turn.is_cancelled()

    def mark_generation_complete(self, turn: TurnHandle) -> None:
        """Record that the LLM stage is no longer producing downstream work."""
        turn.generation_complete.set()

    def mark_idle(self, turn: TurnHandle | None = None) -> bool:
        """Mark the pipeline idle unless a newer turn has already started."""
        return self.finish_turn(turn)

    def is_active(self) -> bool:
        with self._lock:
            if self.continuous_policy is not None and self._is_waiting_locked():
                return True
        return self._pipeline_has_work()

    def _pipeline_has_work(self) -> bool:
        if self._active.is_set():
            return True
        if self._has_pending_work is None:
            return False
        try:
            return bool(self._has_pending_work())
        except Exception:
            logger.debug("chat turn pending-work probe failed", exc_info=True)
            return False

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
            continuous = self.continuous_policy is not None
            was_active = self._active.is_set() or (continuous and self._admission_reserved)
            if not was_active:
                return False
            candidate.pipeline_complete.set()
            self._active.clear()
            # Reserve the admission boundary while reply.finished is published.
            # ASR finals arriving in this window join the deferred FIFO.
            if continuous:
                self._reserve_admission_locked()
                self._completing = True
            completion_turn_id = candidate.id
            completion_revision = self._cancellation_revision

        if not continuous:
            if before_next is not None:
                before_next()
            return True

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
                    self._reserved_admission = deferred

        while deferred is not None:
            try:
                delivered = self._deliver(deferred)
            except Exception:
                self._release_admission_reservation(deferred)
                raise
            if delivered:
                break
            self._release_admission_reservation(deferred)
            with self._lock:
                if (
                    completion_revision != self._cancellation_revision
                    or self._closed or self._closed_event.is_set()
                    or self._active.is_set() or self._admission_reserved
                    or self._delivery_pending or self._completing
                ):
                    break
                deferred = self._pop_current_deferred_locked()
                if deferred is not None:
                    self._reserve_admission_locked(deferred)
        return True

    def interrupt(self, *, reserve_admission: bool = False) -> None:
        """Cancel the current turn and clear all downstream work."""
        with self._lock:
            turn = self._current_turn
            turn.cancelled.set()
            interruption_revision = self._cancellation_revision

        self._run_interrupt_callbacks()
        if reserve_admission and self.continuous_policy is not None:
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
                self._current_turn.cancelled.set()
                self._current_turn.pipeline_complete.set()
                self._active.clear()
                self._cancel_batch_timer_locked()
                self._batch.clear()
                if self.continuous_policy is not None:
                    self.continuous_policy.invalidate()
                    self._delivery_pending.clear()
                    self._input_activity.clear()
                    self._clear_admission_reservation_locked()
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
        defer_until_idle: bool = False,
    ) -> _Admission:
        """Capture the branch-generation that accepted this input."""
        admission = _Admission(
            text, attachments, on_admit,
            cancellation_revision=self._cancellation_revision,
            utterance_id=utterance_id, defer_until_idle=defer_until_idle,
        )
        if utterance_id and self.continuous_policy is not None:
            self.continuous_policy.track(admission, identity=utterance_id, sources=(utterance_id,))
        return admission

    def _combine_admissions_locked(
        self, admissions: Iterable[_Admission], *, separator: str | None = None,
    ) -> _Admission:
        parts = tuple(part for item in admissions for part in (item.parts or (item,)))
        if len(parts) == 1:
            combined = parts[0]
        else:
            separator = self.options.batch_separator if separator is None else separator
            combined = _Admission(
                separator.join(part.text for part in parts if part.text),
                [attachment for part in parts for attachment in part.attachments],
                tuple(callback for part in parts for callback in part.on_admit),
                cancellation_revision=parts[0].cancellation_revision,
                # A batch identity lets retirement revoke already-dequeued input
                # without changing the worker/queue protocol.
                utterance_id=f"batch:{uuid4().hex}" if any(part.utterance_id for part in parts) else None,
                defer_until_idle=any(part.defer_until_idle for part in parts),
                parts=parts,
            )
        if self.continuous_policy is not None:
            self.continuous_policy.track(
                combined, identity=combined.utterance_id,
                sources=(part.utterance_id for part in parts if part.utterance_id),
            )
        return combined

    def _route_admission(self, admission: _Admission) -> bool:
        if admission.defer_until_idle and self.continuous_policy is not None:
            return self._defer_or_deliver(admission)
        return self._deliver(admission)

    def _admission_is_current_locked(self, admission: _Admission) -> bool:
        return (
            not self._closed
            and not self._closed_event.is_set()
            and admission.cancellation_revision == self._cancellation_revision
            and (self.continuous_policy is None or not self.continuous_policy.is_retired(admission.utterance_id))
        )

    def _admission_is_current(self, admission: _Admission) -> bool:
        with self._lock:
            return self._admission_is_current_locked(admission)

    def _deliver(self, admission: _Admission) -> bool:
        with self._delivery_lock:
            with self._lock:
                if not self._admission_is_current_locked(admission):
                    return False
                # Set this before callbacks or sink delivery.  A worker may
                # begin immediately after the sink write, while a concurrent
                # continuous final must continue to wait in either case.
                if self.continuous_policy is not None:
                    self._delivery_pending.append(admission)
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

    def _discard_delivery_pending(self, admission: _Admission) -> None:
        with self._lock:
            self._delivery_pending = deque(item for item in self._delivery_pending if item is not admission)

    def _completion_is_current_locked(self, turn_id: int, revision: int) -> bool:
        return (
            not self._closed
            and not self._closed_event.is_set()
            and self._completing
            and self._current_turn.id == turn_id
            and self._cancellation_revision == revision
        )

    def _reserve_admission_locked(self, admission: _Admission | None = None) -> None:
        self._admission_reserved = True
        self._admission_revision = self._cancellation_revision
        self._reserved_admission = admission

    def _clear_admission_reservation_locked(self) -> None:
        self._admission_reserved = False
        self._batch_interrupt_reserved = False
        self._admission_revision = None
        self._reserved_admission = None

    def _release_admission_reservation(self, admission: _Admission) -> None:
        """Release only the reservation attached to a failed old admission."""
        with self._lock:
            if (
                self._admission_reserved
                and self._reserved_admission is admission
                and self._admission_revision == admission.cancellation_revision
            ):
                self._clear_admission_reservation_locked()

    def _is_waiting_locked(self) -> bool:
        return bool(self._admission_reserved or self._delivery_pending or self._completing)

    def _pop_current_deferred_locked(self) -> _Admission | None:
        if self.continuous_policy is not None:
            while (admission := self.continuous_policy.pop()) is not None:
                if self._admission_is_current_locked(admission):
                    return admission
        return None

    def _retire_utterance_locked(self, utterance_id: str | None) -> tuple[_Admission, ...]:
        # Called after validating a nonempty replacement, under the delivery
        # gate and state lock. Only the host changes its open batch and queue.
        if not utterance_id or self.continuous_policy is None:
            return ()
        previous = self.continuous_policy.retire(utterance_id)
        if previous is None:
            return ()
        self._batch = [item for item in self._batch if item is not previous]
        self._delivery_pending = deque(item for item in self._delivery_pending if item is not previous)
        if not self._active.is_set() and not self._completing and not self._delivery_pending:
            self._clear_admission_reservation_locked()
        return tuple(part for part in (previous.parts or (previous,)) if part.utterance_id != utterance_id)

    def _defer_or_deliver(self, admission: _Admission) -> bool:
        with self._lock:
            if not self._admission_is_current_locked(admission):
                return False
            if (
                self._active.is_set()
                or self._admission_reserved
                or self._delivery_pending
                or self._completing
            ):
                self.continuous_policy.defer(admission)
                return False
            self._reserve_admission_locked(admission)
        try:
            delivered = self._deliver(admission)
        except Exception:
            self._release_admission_reservation(admission)
            raise
        if not delivered:
            self._release_admission_reservation(admission)
        return delivered

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
