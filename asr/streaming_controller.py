from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from sdk.adapters.asr import ASRAdapter, TranscriptionCallback


_log = logging.getLogger(__name__)

EventEmitter = Callable[[dict[str, Any]], None]
AdapterFactory = Callable[[TranscriptionCallback], ASRAdapter]


class StreamingASRController:
    """Run the configured ASR adapter for the non-Qt streaming chat runtime.

    The lifecycle mirrors ``MicButton``: the adapter remains loaded while it is
    paused for a chat turn, a final transcript is submitted immediately, and
    listening resumes shortly after the reply finishes. Partial-only adapters
    are finalized after a short silence so they cannot strand a recognized turn.
    """

    def __init__(
        self,
        *,
        adapter_factory: AdapterFactory,
        emit_event: EventEmitter,
        submit_final: Callable[[str], None],
        on_loading_changed: Callable[[bool], None] | None = None,
        on_error: Callable[[str, BaseException], None] | None = None,
        resume_delay_seconds: float = 0.5,
        silence_submit_seconds: float = 2.0,
    ) -> None:
        self._adapter_factory = adapter_factory
        self._emit_event = emit_event
        self._submit_final = submit_final
        self._on_loading_changed = on_loading_changed
        self._on_error = on_error
        self._resume_delay_seconds = max(0.0, float(resume_delay_seconds))
        self._silence_submit_seconds = max(0.0, float(silence_submit_seconds))

        self._lock = threading.RLock()
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

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled and not self._closed

    def user_resume(self) -> None:
        """Enable ASR, loading the selected adapter lazily on first use."""
        with self._lock:
            if self._closed:
                return
            self._enabled = True
            self._turn_paused = False
            self._clear_on_activation = True
            self._cancel_resume_timer_locked()
            self._cancel_silence_timer_locked()
        self._emit_state()
        self._activate_async()

    def user_pause(self) -> None:
        """Disable automatic resume until the user explicitly enables ASR again."""
        with self._lock:
            if self._closed:
                return
            self._enabled = False
            self._active = False
            self._turn_paused = False
            self._clear_on_activation = False
            self._cancel_resume_timer_locked()
            self._cancel_silence_timer_locked()
            adapter = self._adapter if self._started else None
        self._pause_adapter(adapter)
        self._emit_state()

    def pause_for_turn(self) -> bool:
        """Temporarily pause an enabled adapter while a chat turn is processed."""
        with self._lock:
            if self._closed or not self._enabled:
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
            if self._closed or not self._enabled or not self._turn_paused:
                return
            self._cancel_resume_timer_locked()
            timer = threading.Timer(
                self._resume_delay_seconds, self._resume_after_delay
            )
            timer.daemon = True
            self._resume_timer = timer
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
        if adapter is not None:
            try:
                adapter.stop()
            except Exception as exc:
                self._report_error("stop", exc)

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
        if should_load:
            self._notify_loading(True)
            try:
                adapter = self._adapter_factory(self._handle_transcription)
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
                try:
                    adapter.stop()
                except Exception:
                    _log.debug(
                        "Failed to stop stale streaming ASR adapter", exc_info=True
                    )
                return

        if adapter is None:
            return

        with self._lock:
            should_activate = (
                not self._closed
                and generation == self._generation
                and self._enabled
                and not self._turn_paused
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
                )
            if retry_activation:
                self._activate_async()
            return

        try:
            if started:
                adapter.resume()
            else:
                adapter.start()
        except BaseException as exc:
            with self._lock:
                if generation == self._generation:
                    self._activating = False
                    self._active = False
                    self._enabled = False
            self._report_error("start", exc)
            self._emit_state()
            return

        with self._lock:
            self._started = True
            self._activating = False
            should_remain_active = (
                not self._closed
                and generation == self._generation
                and self._enabled
                and not self._turn_paused
            )
            self._active = should_remain_active
            clear_transcript = should_remain_active and self._clear_on_activation
            if clear_transcript:
                self._clear_on_activation = False
                self._original_text = ""
                self._current_text = ""

        if not should_remain_active:
            with self._lock:
                closed = self._closed
            if closed:
                try:
                    adapter.stop()
                except Exception as exc:
                    self._report_error("stop", exc)
            else:
                self._pause_adapter(adapter)
            self._emit_state()
            return
        if clear_transcript:
            self._emit_event_safe({"type": "asr.partial", "text": ""})
        self._emit_state()

    def _handle_transcription(self, text: str, is_partial: bool) -> None:
        raw_text = str(text or "")
        with self._lock:
            if self._closed or not self._enabled or self._turn_paused:
                return
            adapter = self._adapter
            language = str(getattr(adapter, "language", "") or "").strip().lower()
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
                    return
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
                self._turn_paused = True
                self._active = False
                active_adapter = adapter

        self._emit_event_safe(
            {"type": "asr.partial" if is_partial else "asr.final", "text": displayed}
        )
        if is_partial:
            return

        self._pause_adapter(active_adapter)
        self._emit_state()
        try:
            self._submit_final(displayed)
        except BaseException as exc:
            self._report_error("submit", exc)
            with self._lock:
                if not self._closed and self._enabled:
                    self._turn_paused = False
                    self._clear_on_activation = True
            self._activate_async()

    def _pause_adapter(self, adapter: ASRAdapter | None) -> None:
        if adapter is None:
            return
        try:
            adapter.pause()
        except Exception as exc:
            self._report_error("pause", exc)

    def _emit_state(self) -> None:
        with self._lock:
            enabled = self._enabled and not self._closed
            running = enabled and self._active and not self._turn_paused
            loading = (
                enabled
                and not self._turn_paused
                and (self._loading or self._activating)
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
        if callback is not None:
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
            if generation != self._silence_generation:
                return
            self._silence_timer = None
            if (
                self._closed
                or not self._enabled
                or not self._active
                or self._turn_paused
            ):
                return
            displayed = self._current_text.strip()
        if not displayed:
            return
        _log.info(
            "Streaming ASR finalized transcript after %.1fs of silence",
            self._silence_submit_seconds,
        )
        self._handle_transcription(displayed, False)

    def _cancel_silence_timer_locked(self) -> None:
        self._silence_generation += 1
        timer = self._silence_timer
        self._silence_timer = None
        if timer is not None:
            timer.cancel()
