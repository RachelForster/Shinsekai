"""Streaming ASR lifecycle controller."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sdk.adapters.asr import ASRAdapter, TranscriptionCallback


_log = logging.getLogger(__name__)

EventEmitter = Callable[[dict[str, Any]], None]
AdapterFactory = Callable[[TranscriptionCallback], ASRAdapter]


@dataclass(frozen=True)
class ASRSubmissionResult:
    """Whether a final transcript was accepted and admitted immediately."""

    accepted: bool
    admitted: bool


class StreamingASRController:
    """Run the configured ASR adapter for the non-Qt streaming chat runtime.

    The lifecycle mirrors ``MicButton``: the adapter remains loaded while it is
    paused for a chat turn, a final transcript is submitted immediately, and
    listening resumes shortly after the reply finishes. Partial-only adapters
    are finalized after a short period of unchanged text so they cannot strand
    a recognized turn. Ordinary mode preserves the loaded adapter across turns.
    """

    def __init__(
        self,
        *,
        adapter_factory: AdapterFactory,
        emit_event: EventEmitter,
        submit_final: Callable[[str], bool | None | ASRSubmissionResult],
        submit_utterance: Callable[[str, str], bool | None | ASRSubmissionResult] | None = None,
        on_loading_changed: Callable[[bool], None] | None = None,
        on_error: Callable[[str, BaseException], None] | None = None,
        resume_delay_seconds: float = 0.5,
        silence_submit_seconds: float = 3.5,
        continuous_listening: bool = False,
    ) -> None:
        self._adapter_factory = adapter_factory
        self._emit_event = emit_event
        self._submit_final = submit_final
        self._submit_utterance = submit_utterance
        self._on_loading_changed = on_loading_changed
        self._on_error = on_error
        self._resume_delay_seconds = max(0.0, float(resume_delay_seconds))
        self._silence_submit_seconds = max(0.0, float(silence_submit_seconds))
        self._continuous_listening = bool(continuous_listening)

        self._lock = threading.RLock()
        # Serialize callbacks with close(). Once close() returns, no callback
        # that already passed the state guard can still publish or submit.
        self._callback_lock = threading.RLock()
        self._adapter: ASRAdapter | None = None
        self._enabled = False
        self._active = False
        self._started = False
        self._activating = False
        self._loading = False
        self._turn_paused = False
        self._closed = False
        self._generation = 0
        self._clear_on_activation = False
        self._resume_timer: threading.Timer | None = None
        self._silence_timer: threading.Timer | None = None
        self._silence_generation = 0
        self._original_text = ""
        self._current_text = ""
        self._hold_to_talk = False
        self._finishing_hold = False
        self._hold_adapter_warm = False
        self._utterance_id = uuid4().hex
        self._input_epoch = 0
        self._boundary_depth = 0
        self._fallback_stop: tuple[threading.Event, int] | None = None

    @contextmanager
    def input_boundary(self) -> Iterator[None]:
        """Invalidate old capture callbacks for the entire history mutation.

        Recreate capture to fence delayed callbacks from the old adapter. Never
        hold the callback lock while stopping an adapter (stop may join it).
        """
        with self._callback_lock:
            with self._lock:
                self._boundary_depth += 1
                self._input_epoch += 1
                self._generation += 1
                self._active = False
                self._cancel_resume_timer_locked()
                self._cancel_silence_timer_locked()
                self._original_text = self._current_text = ""
                self._utterance_id = uuid4().hex
                adapter = self._adapter
                self._adapter = None
                self._started = False
                self._clear_on_activation = False
            self._emit_transcript("asr.partial", "", self._utterance_id)
        self._stop_adapter(adapter)
        try:
            yield
        finally:
            with self._lock:
                self._boundary_depth -= 1
            self._emit_state()
            self._activate_async()

    @property
    def continuous_listening(self) -> bool:
        return self._continuous_listening

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled and not self._closed

    @contextmanager
    def manual_submission(self, utterance_id: str):
        """Serialize manual replacement with final/fallback callbacks.

        The caller commits only after input plugins accept the manual message.
        Retiring an active utterance recreates capture, fencing even corrected
        late finals; replacing an older deferred draft leaves new capture alone.
        """
        retired_adapter = None
        restart = False
        def commit():
            nonlocal retired_adapter, restart
            with self._lock:
                if self._closed or not self._continuous_listening or utterance_id != self._utterance_id:
                    return
                self._input_epoch += 1
                self._generation += 1
                self._cancel_silence_timer_locked()
                self._original_text = self._current_text = ""
                self._utterance_id = uuid4().hex
                self._active = False
                retired_adapter = self._adapter
                self._adapter = None
                self._started = False
                restart = True
            self._emit_transcript("asr.partial", "", self._utterance_id)

        try:
            with self._callback_lock:
                yield commit
        finally:
            if restart:
                self._stop_adapter(retired_adapter)
                self._activate_async()

    def user_resume(self) -> None:
        """Enable ASR, loading the selected adapter lazily on first use."""
        if self._hold_to_talk or self._finishing_hold:
            self.user_pause()
        with self._lock:
            if self._closed:
                return
            self._enabled = True
            self._turn_paused = False
            self._clear_on_activation = True
            self._hold_adapter_warm = False
            self._cancel_resume_timer_locked()
            self._cancel_silence_timer_locked()
        self._emit_state()
        self._activate_async()

    def user_pause(self) -> None:
        """Disable ASR and release capture until the user enables it again."""
        with self._callback_lock:
            with self._lock:
                if self._closed:
                    return
                self._enabled = False
                self._active = False
                self._turn_paused = False
                self._clear_on_activation = False
                self._hold_to_talk = False
                self._hold_adapter_warm = False
                self._cancel_resume_timer_locked()
                self._cancel_silence_timer_locked()
                adapter = self._adapter if self._started else None
                self._started = False
        self._stop_adapter(adapter)
        self._emit_state()

    def begin_hold(self) -> None:
        """Collect a single utterance until an explicit release, without auto-send."""
        with self._lock:
            if self._closed or self._hold_to_talk or self._finishing_hold:
                return
            reuse_warm_adapter = (
                self._hold_adapter_warm
                and self._adapter is not None
                and self._started
            )
        if not reuse_warm_adapter:
            self.user_pause()
        with self._lock:
            if self._closed:
                return
            self._hold_to_talk = True
            self._hold_adapter_warm = False
            self._enabled = True
            self._original_text = self._current_text = ""
            self._clear_on_activation = False
        self._emit_event_safe({"continuous": False, "type": "asr.partial", "text": ""})
        self._activate_async()

    def finish_hold(self, *, cancel: bool = False) -> None:
        """Drain the decoder before submitting once; cancellation never submits."""
        with self._lock:
            if not self._hold_to_talk or self._finishing_hold:
                return
            self._finishing_hold = True
            adapter = self._adapter if self._started else None
            if cancel or adapter is None:
                self._enabled = False
            self._cancel_silence_timer_locked()
        failed = False
        kept_warm = False
        try:
            if adapter is not None:
                kept_warm = bool(adapter.finish_hold(cancel=cancel))
        except Exception:
            failed = True
            self._stop_adapter(adapter)
            raise
        finally:
            with self._callback_lock:
                with self._lock:
                    text = self._current_text.strip()
                    submit = (
                        bool(text)
                        and adapter is not None
                        and self._hold_to_talk
                        and not (cancel or failed or self._closed)
                    )
                    self._hold_to_talk = False
                    self._finishing_hold = False
                    self._enabled = self._active = False
                    self._started = kept_warm and not failed and not self._closed
                    self._hold_adapter_warm = self._started
                    self._turn_paused = False
                if submit:
                    try:
                        if self._submit_final(text) is False:
                            raise RuntimeError(
                                "Voice input could not be sent; the transcript was kept in the input box."
                            )
                    except Exception:
                        self._emit_event_safe({"continuous": False, "type": "asr.partial", "text": text})
                        self._emit_state()
                        raise
                    self._emit_event_safe({"continuous": False, "type": "asr.final", "text": text})
                    self._emit_state()
                elif cancel:
                    self._emit_event_safe({"continuous": False, "type": "asr.partial", "text": ""})
                    self._emit_state()
                else:
                    self._emit_state()

    def pause_for_turn(self) -> bool:
        """Temporarily pause an enabled adapter while a chat turn is processed."""
        if self._hold_to_talk:
            self.finish_hold(cancel=True)
            return True
        with self._lock:
            if self._closed or not self._enabled:
                return False
            if self._continuous_listening:
                return False
            self._turn_paused = True
            self._active = False
            self._cancel_resume_timer_locked()
            self._cancel_silence_timer_locked()
            adapter = self._adapter if self._started else None
        self._pause_adapter(adapter)
        self._emit_state()
        return True

    def reply_finished(self) -> None:
        """Resume a turn-paused adapter after the same delay used by the Qt UI."""
        with self._lock:
            if self._closed or not self._enabled:
                return
            if self._continuous_listening:
                publish_running_state = True
            elif not self._turn_paused:
                return
            else:
                publish_running_state = False
            if publish_running_state:
                timer = None
            else:
                self._cancel_resume_timer_locked()
                timer = threading.Timer(
                    self._resume_delay_seconds, self._resume_after_delay
                )
                timer.daemon = True
                self._resume_timer = timer
        if publish_running_state:
            self._emit_state()
        elif timer is not None:
            timer.start()

    def close(self) -> None:
        """Stop the adapter and discard any in-flight lazy initialization."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._enabled = False
            self._active = False
            self._turn_paused = False
            self._generation += 1
            self._cancel_resume_timer_locked()
            self._cancel_silence_timer_locked()
            adapter = self._adapter
            self._adapter = None
            self._started = False
            self._hold_adapter_warm = False
            fallback_stop = self._fallback_stop
        # A callback may have left _lock just before _closed was set. Wait for
        # that callback to finish before the caller publishes session.closed.
        with self._callback_lock:
            pass
        self._stop_adapter(adapter)
        if fallback_stop is not None and fallback_stop[1] != threading.get_ident():
            # A fallback may already own teardown of the detached adapter.
            # Do not report a closed session while its capture is still alive.
            fallback_stop[0].wait()

    def _resume_after_delay(self) -> None:
        with self._lock:
            self._resume_timer = None
            if self._closed or not self._enabled or not self._turn_paused:
                return
            self._turn_paused = False
            self._clear_on_activation = True
        self._activate_async()

    def _activate_async(self) -> None:
        with self._lock:
            if (
                self._closed
                or not self._enabled
                or self._turn_paused
                or self._active
                or self._activating
                or self._boundary_depth
                or self._fallback_stop is not None
            ):
                return
            self._activating = True
            self._generation += 1
            generation = self._generation
        self._emit_state()
        threading.Thread(
            target=self._activate_worker,
            args=(generation,),
            daemon=True,
            name="shinsekai-streaming-asr",
        ).start()

    def _activate_worker(self, generation: int) -> None:
        adapter: ASRAdapter | None
        with self._lock:
            adapter = self._adapter
            should_load = adapter is None
            if should_load:
                self._loading = True
            input_epoch = self._input_epoch
        if should_load:
            self._notify_loading(True)
            try:
                adapter = self._adapter_factory(
                    lambda text, is_partial: self._handle_transcription(
                        text, is_partial, input_epoch=input_epoch
                    )
                )
            except BaseException as exc:
                with self._lock:
                    if generation == self._generation:
                        self._activating = False
                        self._loading = False
                        self._enabled = False
                self._notify_loading(False)
                self._report_error("load", exc)
                self._emit_state()
                return
            with self._lock:
                self._loading = False
                stale = self._closed or generation != self._generation
                if not stale:
                    self._adapter = adapter
            self._notify_loading(False)
            if stale:
                with self._lock:
                    self._activating = False
                    retry_activation = (
                        not self._closed
                        and self._enabled
                        and not self._turn_paused
                        and not self._active
                        and not self._boundary_depth
                    )
                self._stop_adapter(adapter, report=False)
                if retry_activation:
                    self._activate_async()
                return

        if adapter is None:
            return

        with self._lock:
            should_activate = (
                not self._closed
                and generation == self._generation
                and self._enabled
                and not self._turn_paused
                and not self._boundary_depth
            )
            started = self._started
        if not should_activate:
            with self._lock:
                if generation == self._generation:
                    self._activating = False
                retry_activation = (
                    not self._closed
                    and self._enabled
                    and not self._turn_paused
                    and not self._active
                    and not self._boundary_depth
                )
            if retry_activation:
                self._activate_async()
            return

        try:
            if started:
                adapter.resume()
            else:
                adapter.start()
            status = adapter.get_status()
            normalized_status = str(status or "").strip().lower()
            if normalized_status in {"error", "failed", "idle", "paused", "stopped"}:
                raise RuntimeError(
                    f"ASR adapter did not enter a running state (status={status!r})"
                )
        except BaseException as exc:
            with self._lock:
                if generation == self._generation:
                    self._activating = False
                    self._active = False
                    self._enabled = False
                    self._started = False
            self._stop_adapter(adapter, report=False)
            self._report_error("start", exc)
            self._emit_state()
            return

        with self._callback_lock:
            with self._lock:
                stale_activation = generation != self._generation or self._closed
                should_remain_active = (
                    not stale_activation
                    and self._enabled
                    and not self._turn_paused
                    and not self._boundary_depth
                )
                self._started = not stale_activation
                self._activating = False
                self._active = should_remain_active
                clear_transcript = should_remain_active and self._clear_on_activation
                if clear_transcript:
                    self._clear_on_activation = False
                    self._original_text = ""
                    self._current_text = ""
                    self._utterance_id = uuid4().hex
            if should_remain_active:
                # Publish reset before accepting any callback from live capture.
                if clear_transcript:
                    self._emit_transcript("asr.partial", "", self._utterance_id)
                self._emit_state()
                return

        if stale_activation:
            self._stop_adapter(adapter, report=False)
            self._activate_async()
            return

        if not should_remain_active:
            with self._lock:
                closed = self._closed
                enabled = self._enabled
            if closed or not enabled:
                with self._lock:
                    self._started = False
                self._stop_adapter(adapter)
            else:
                self._pause_adapter(adapter)
            self._emit_state()
            return

    def _handle_transcription(
        self, text: str, is_partial: bool, *, input_epoch: int | None = None
    ) -> None:
        with self._callback_lock:
            with self._lock:
                if input_epoch is not None and input_epoch != self._input_epoch:
                    return
                if self._closed or not self._enabled or not self._active or self._turn_paused or self._boundary_depth:
                    return
                acknowledge = getattr(self._adapter, "acknowledge_capture", None)
                if callable(acknowledge):
                    acknowledge()
            self._process_transcription(text, is_partial)

    def _process_transcription(self, text: str, is_partial: bool) -> None:
        raw_text = str(text or "")
        with self._lock:
            if self._closed or not self._enabled or not self._active or self._turn_paused or self._boundary_depth:
                return
            adapter = self._adapter
            language = str(getattr(adapter, "language", "") or "").strip().lower()
            if self._hold_to_talk:
                piece = raw_text.strip() if language.startswith("en") else raw_text.replace(" ", "").strip()
                if not piece:
                    return
                separator = " " if language.startswith("en") else "，"
                self._current_text = f"{self._original_text}{separator if self._original_text else ''}{piece}"
                if not is_partial:
                    self._original_text = self._current_text
                # Endpoint detection is only a segment boundary in hold mode.
                self._emit_event_safe({"continuous": False, "type": "asr.partial", "text": self._current_text})
                return
            utterance_id = self._utterance_id
            if is_partial:
                if not raw_text:
                    return
                previous = self._current_text
                self._current_text = f"{self._original_text}{raw_text}"
                displayed = self._current_text
                # Some realtime engines keep reporting the same hypothesis while
                # the microphone is silent. Treat only transcript changes as
                # speech activity so those duplicate callbacks cannot postpone
                # the silence fallback forever.
                if displayed != previous or self._silence_timer is None:
                    self._schedule_silence_submit_locked()
            else:
                self._cancel_silence_timer_locked()
                final_piece = (
                    raw_text.strip()
                    if language.startswith("en")
                    else raw_text.replace(" ", "").strip()
                )
                if not final_piece:
                    if not self._continuous_listening:
                        return
                    # Noise-only finals end draft activity too. Otherwise the
                    # shared stacked timer stays paused after a rejected partial.
                    self._original_text = self._current_text = ""
                    self._utterance_id = uuid4().hex
                    displayed = ""
                    active_adapter = None
                else:
                    separator = " " if language.startswith("en") else "，"
                    built = f"{self._original_text}{separator if self._original_text else ''}{final_piece}"
                    current = self._current_text.strip()
                    if current and (
                        current == built.strip() or current.endswith(final_piece)
                    ):
                        self._original_text = self._current_text
                    else:
                        self._current_text = built
                        self._original_text = built
                    displayed = self._current_text.strip()
                    if self._continuous_listening:
                        self._original_text = ""
                        self._current_text = ""
                        self._utterance_id = uuid4().hex
                        active_adapter = None
                    else:
                        self._turn_paused = True
                        self._active = False
                        active_adapter = adapter

        if is_partial or not displayed:
            self._emit_transcript("asr.partial", displayed, utterance_id)
            return

        if self._continuous_listening:
            # A final heard during a reply remains a draft until the turn
            # service actually admits it. This keeps the input visible and
            # avoids presenting a user turn that can still be rejected.
            with self._lock:
                if self._closed or not self._enabled:
                    return
            # Publish before admission: finish_turn may admit on another thread
            # immediately after submit returns. A later partial would resurrect
            # the draft after its final has already consumed it.
            self._emit_transcript("asr.partial", displayed, utterance_id)
            try:
                result = self._submit_transcript(displayed, utterance_id)
            except BaseException as exc:
                self._report_error("submit", exc)
                result = ASRSubmissionResult(accepted=False, admitted=False)
            if not isinstance(result, ASRSubmissionResult) and result is not False:
                # Backward-compatible callback contract used by embedders:
                # a truthy/None result means admission completed inline.
                self._emit_transcript("asr.final", displayed, utterance_id)
            return

        with self._lock:
            if self._closed or not self._enabled or not self._turn_paused:
                return
        self._pause_adapter(active_adapter)
        try:
            accepted = self._submit_transcript(displayed, utterance_id)
            if isinstance(accepted, ASRSubmissionResult):
                accepted = accepted.accepted
        except BaseException as exc:
            self._report_error("submit", exc)
            accepted = False
        if accepted is False:
            with self._lock:
                if not self._closed and self._enabled:
                    self._turn_paused = False
                    self._clear_on_activation = True
            self._activate_async()
            return
        self._emit_event_safe({"type": "asr.final", "text": displayed})
        self._emit_state()

    def _submit_transcript(self, text: str, utterance_id: str) -> bool | None | ASRSubmissionResult:
        if self._submit_utterance is not None:
            return self._submit_utterance(text, utterance_id)
        return self._submit_final(text)

    def _emit_transcript(self, event_type: str, text: str, utterance_id: str) -> None:
        self._emit_event_safe({"type": event_type, "text": text, "utteranceId": utterance_id})

    def _pause_adapter(self, adapter: ASRAdapter | None) -> None:
        if adapter is None:
            return
        try:
            adapter.pause()
        except Exception as exc:
            self._report_error("pause", exc)

    def _stop_adapter(self, adapter: ASRAdapter | None, *, report: bool = True) -> None:
        if adapter is None:
            return
        try:
            adapter.stop()
        except Exception as exc:
            if report:
                self._report_error("stop", exc)
            else:
                _log.debug("Failed to stop streaming ASR adapter", exc_info=True)

    def _emit_state(self) -> None:
        with self._lock:
            enabled = self._enabled and not self._closed
            running = enabled and self._active and not self._turn_paused
            loading = (
                enabled
                and not self._turn_paused
                and (
                    self._loading
                    or (self._activating and not self._started)
                )
            )
        self._emit_event_safe(
            {
                "type": "asr.state",
                "enabled": enabled,
                "loading": loading,
                "running": running,
            }
        )

    def _emit_event_safe(self, event: dict[str, Any]) -> None:
        if event.get("type", "").startswith("asr."):
            if self._continuous_listening:
                event = {"continuous": not (self._hold_to_talk or self._finishing_hold), **event}
            else:
                event = {key: value for key, value in event.items() if key not in ("utteranceId", "continuous")}
        with self._callback_lock:
            with self._lock:
                if self._closed:
                    return
            try:
                self._emit_event(event)
            except Exception as exc:
                self._report_error("event", exc)

    def _notify_loading(self, loading: bool) -> None:
        callback = self._on_loading_changed
        if callback is None:
            return
        try:
            callback(loading)
        except Exception as exc:
            self._report_error("loading", exc)

    def _report_error(self, operation: str, exc: BaseException) -> None:
        _log.error(
            "Streaming ASR %s failed: %s",
            operation,
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        callback = self._on_error
        with self._lock:
            closed = self._closed
        if callback is not None and not closed:
            try:
                callback(operation, exc)
            except Exception:
                _log.debug("Streaming ASR error callback failed", exc_info=True)

    def _cancel_resume_timer_locked(self) -> None:
        timer = self._resume_timer
        self._resume_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_silence_submit_locked(self) -> None:
        self._cancel_silence_timer_locked()
        if self._silence_submit_seconds <= 0:
            return
        generation = self._silence_generation
        timer = threading.Timer(
            self._silence_submit_seconds,
            self._submit_after_silence,
            args=(generation,),
        )
        timer.daemon = True
        self._silence_timer = timer
        timer.start()

    def _submit_after_silence(self, generation: int) -> None:
        with self._lock:
            supports_reset = callable(getattr(self._adapter, "reset_capture", None))
        if not self._continuous_listening and not supports_reset:
            with self._callback_lock:
                with self._lock:
                    if generation != self._silence_generation:
                        return
                    self._silence_timer = None
                    if self._closed or not self._enabled or not self._active or self._turn_paused:
                        return
                    displayed = self._current_text.strip()
                if displayed:
                    self._process_transcription(displayed, False)
            return
        retired_adapter = None
        stop_done = threading.Event()
        fallback_started = False
        try:
            with self._callback_lock:
                with self._lock:
                    if generation != self._silence_generation:
                        return
                    self._silence_timer = None
                    if (
                        self._closed
                        or not self._enabled
                        or not self._active
                        or self._turn_paused
                        or self._boundary_depth
                    ):
                        return
                    displayed = self._current_text.strip()
                    adapter = self._adapter
                    input_epoch = self._input_epoch
                    if not displayed:
                        return
                    # Submission can immediately reject or finish its reply.
                    # Gate resume before either can restart the old capture.
                    self._fallback_stop = (stop_done, threading.get_ident())
                    fallback_started = True
                _log.info(
                    "Streaming ASR finalized transcript after %.1fs of unchanged text",
                    self._silence_submit_seconds,
                )
                try:
                    self._process_transcription(displayed, False)
                finally:
                    with self._lock:
                        if (
                            adapter is not None
                            and self._adapter is adapter
                            and self._input_epoch == input_epoch
                        ):
                            # Unchanged text is not an audio endpoint. Retire
                            # capture before releasing callbacks so cumulative
                            # audio and late corrections cannot enter a new turn.
                            self._input_epoch += 1
                            if supports_reset:
                                next_epoch = self._input_epoch
                                try:
                                    adapter.reset_capture(
                                        lambda text, partial: self._handle_transcription(
                                            text, partial, input_epoch=next_epoch,
                                        ),
                                    )
                                except Exception as exc:
                                    self._report_error("reset_capture", exc)
                                else:
                                    # F: acknowledgement clears submitted PCM
                                    # without replacing the loaded model/stream.
                                    return
                            self._generation += 1
                            self._boundary_depth += 1
                            self._cancel_silence_timer_locked()
                            self._active = False
                            self._started = False
                            self._adapter = None
                            retired_adapter = adapter
        finally:
            if fallback_started:
                # stop() may join a thread waiting in a callback. Keep the
                # callback lock free and block activation until teardown ends.
                try:
                    self._stop_adapter(retired_adapter)
                finally:
                    with self._lock:
                        if retired_adapter is not None:
                            self._boundary_depth -= 1
                        self._fallback_stop = None
                        stop_done.set()
                    self._emit_state()
                    self._activate_async()

    def _cancel_silence_timer_locked(self) -> None:
        self._silence_generation += 1
        timer = self._silence_timer
        self._silence_timer = None
        if timer is not None:
            timer.cancel()
