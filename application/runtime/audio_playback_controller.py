"""Backend-neutral blocking control for dialog voice playback."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol


class PlaybackState(str, Enum):
    STARTING = "starting"
    STARTED = "started"
    FINISHED = "finished"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    TIMED_OUT = "timed-out"


TERMINAL_PLAYBACK_STATES = {
    PlaybackState.FINISHED,
    PlaybackState.INTERRUPTED,
    PlaybackState.FAILED,
    PlaybackState.TIMED_OUT,
}


@dataclass(frozen=True)
class VoicePlaybackRequest:
    playback_id: str
    character_name: str
    audio_path: str
    volume: float


@dataclass(frozen=True)
class PlaybackResult:
    playback_id: str
    state: PlaybackState
    error: str = ""


PlaybackSignalHandler = Callable[[str, PlaybackState | str, str], bool]


class VoicePlaybackBackend(Protocol):
    def start(
        self,
        request: VoicePlaybackRequest,
        signal: PlaybackSignalHandler,
    ) -> None: ...

    def stop(self, request: VoicePlaybackRequest) -> None: ...


@dataclass
class _ActivePlayback:
    request: VoicePlaybackRequest
    done: threading.Event
    on_started: Callable[[], None] | None
    state: PlaybackState = PlaybackState.STARTING
    error: str = ""
    renderer_id: str = ""
    started_notified: bool = False


class VoicePlaybackController:
    """Own the blocking, completion, and interruption contract for UIWorker."""

    def __init__(
        self,
        backend: VoicePlaybackBackend,
        *,
        interrupt_event: threading.Event | None = None,
        default_timeout_seconds: float = 300.0,
    ) -> None:
        self._backend = backend
        self._interrupt_event = interrupt_event or threading.Event()
        self._default_timeout_seconds = max(1.0, float(default_timeout_seconds))
        self._lock = threading.RLock()
        self._active: _ActivePlayback | None = None

    @property
    def interrupt_event(self) -> threading.Event:
        return self._interrupt_event

    @property
    def current_audio_path(self) -> str | None:
        with self._lock:
            active = self._active
            if active is None or active.state in TERMINAL_PLAYBACK_STATES:
                return None
            return active.request.audio_path

    def is_active(self) -> bool:
        with self._lock:
            return bool(
                self._active is not None
                and self._active.state not in TERMINAL_PLAYBACK_STATES
            )

    def prepare_next(self) -> None:
        self._interrupt_event.clear()

    def wait_interruptibly(self, duration_seconds: float) -> bool:
        """Wait for dialog pacing. Return False when interrupted."""
        duration = max(0.0, float(duration_seconds))
        return not self._interrupt_event.wait(timeout=duration)

    def play_and_wait(
        self,
        *,
        character_name: str,
        audio_path: str,
        volume: float = 1.0,
        minimum_duration_seconds: float = 0.0,
        timeout_seconds: float | None = None,
        on_started: Callable[[], None] | None = None,
    ) -> PlaybackResult:
        request = VoicePlaybackRequest(
            playback_id=uuid.uuid4().hex,
            character_name=str(character_name or ""),
            audio_path=str(audio_path or ""),
            volume=min(1.0, max(0.0, float(volume))),
        )
        active = _ActivePlayback(
            request=request,
            done=threading.Event(),
            on_started=on_started,
        )
        with self._lock:
            if self._active is not None:
                raise RuntimeError("dialog voice playback is already active")
            self._active = active
            interrupted_before_start = self._interrupt_event.is_set()
            if interrupted_before_start:
                active.state = PlaybackState.INTERRUPTED
                active.done.set()

        started_at = time.monotonic()
        try:
            if not interrupted_before_start:
                try:
                    with self._lock:
                        if active.state not in TERMINAL_PLAYBACK_STATES:
                            self._backend.start(request, self.handle_signal)
                except Exception as exc:
                    self._finish_active(
                        request.playback_id,
                        PlaybackState.FAILED,
                        str(exc),
                        stop_backend=True,
                    )

            timeout = (
                self._default_timeout_seconds
                if timeout_seconds is None
                else max(0.01, float(timeout_seconds))
            )
            if not active.done.wait(timeout=timeout):
                self._finish_active(
                    request.playback_id,
                    PlaybackState.TIMED_OUT,
                    "dialog voice playback timed out",
                    stop_backend=True,
                )

            with self._lock:
                state = active.state
                error = active.error

            remaining = max(
                0.0,
                float(minimum_duration_seconds) - (time.monotonic() - started_at),
            )
            if state in {
                PlaybackState.FINISHED,
                PlaybackState.FAILED,
                PlaybackState.TIMED_OUT,
            } and remaining > 0:
                if self._interrupt_event.wait(timeout=remaining):
                    state = PlaybackState.INTERRUPTED
        finally:
            with self._lock:
                if self._active is active:
                    self._active = None

        return PlaybackResult(
            playback_id=request.playback_id,
            state=state,
            error=error,
        )

    def handle_signal(
        self,
        playback_id: str,
        state: PlaybackState | str,
        error: str = "",
        *,
        renderer_id: str = "",
    ) -> bool:
        try:
            normalized_state = (
                state if isinstance(state, PlaybackState) else PlaybackState(str(state))
            )
        except ValueError:
            return False

        callback: Callable[[], None] | None = None
        stop_request: VoicePlaybackRequest | None = None
        with self._lock:
            active = self._active
            if active is None or active.request.playback_id != str(playback_id or ""):
                return False
            if active.state in TERMINAL_PLAYBACK_STATES:
                return False
            normalized_renderer_id = str(renderer_id or "").strip()
            if normalized_renderer_id:
                if (
                    active.renderer_id
                    and active.renderer_id != normalized_renderer_id
                    and normalized_state is not PlaybackState.STARTED
                ):
                    return False
                active.renderer_id = normalized_renderer_id
            if normalized_state is PlaybackState.STARTED:
                active.state = normalized_state
                if not active.started_notified:
                    active.started_notified = True
                    callback = active.on_started
            elif normalized_state in TERMINAL_PLAYBACK_STATES:
                active.state = normalized_state
                active.error = str(error or "")
                if normalized_state is PlaybackState.INTERRUPTED:
                    self._interrupt_event.set()
                if normalized_state in {
                    PlaybackState.FAILED,
                    PlaybackState.INTERRUPTED,
                }:
                    stop_request = active.request
                active.done.set()
            else:
                return False

        if callback is not None:
            try:
                callback()
            except Exception:
                pass
        if stop_request is not None:
            try:
                self._backend.stop(stop_request)
            except Exception:
                pass
        return True

    def interrupt(self) -> bool:
        self._interrupt_event.set()
        with self._lock:
            active = self._active
            if active is None or active.state in TERMINAL_PLAYBACK_STATES:
                return False
            active.state = PlaybackState.INTERRUPTED
            active.done.set()
            request = active.request
        try:
            self._backend.stop(request)
        except Exception:
            pass
        return True

    def shutdown(self) -> None:
        self.interrupt()

    def _finish_active(
        self,
        playback_id: str,
        state: PlaybackState,
        error: str,
        *,
        stop_backend: bool,
    ) -> bool:
        with self._lock:
            active = self._active
            if active is None or active.request.playback_id != playback_id:
                return False
            if active.state in TERMINAL_PLAYBACK_STATES:
                return False
            active.state = state
            active.error = error
            active.done.set()
            request = active.request
        if stop_backend:
            try:
                self._backend.stop(request)
            except Exception:
                pass
        return True


class FrontendVoicePlaybackBackend:
    """Emit playback requests; completion arrives through frontend signals."""

    def __init__(self, ui_updates: object) -> None:
        self._ui_updates = ui_updates

    def start(
        self,
        request: VoicePlaybackRequest,
        signal: PlaybackSignalHandler,
    ) -> None:
        del signal
        self._ui_updates.post_tts_play(
            request.character_name,
            request.audio_path,
            playback_id=request.playback_id,
            volume=request.volume,
        )

    def stop(self, request: VoicePlaybackRequest) -> None:
        self._ui_updates.post_tts_skip(playback_id=request.playback_id)


class UnavailableVoicePlaybackBackend:
    """Fail immediately when the configured native audio channel is unavailable."""

    def start(
        self,
        request: VoicePlaybackRequest,
        signal: PlaybackSignalHandler,
    ) -> None:
        signal(
            request.playback_id,
            PlaybackState.FAILED,
            "dialog voice playback backend is unavailable",
        )

    def stop(self, request: VoicePlaybackRequest) -> None:
        del request


class PygameVoicePlaybackBackend:
    """Adapt a pygame mixer channel to the same playback signal protocol."""

    def __init__(
        self,
        *,
        channel: object,
        sound_factory: Callable[[str], object],
        ui_updates: object,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        self._channel = channel
        self._sound_factory = sound_factory
        self._ui_updates = ui_updates
        self._poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self._lock = threading.Lock()
        self._current_id = ""
        self._current_sound: object | None = None

    def start(
        self,
        request: VoicePlaybackRequest,
        signal: PlaybackSignalHandler,
    ) -> None:
        sound = self._sound_factory(request.audio_path)
        sound.set_volume(request.volume)
        self._channel.play(sound)
        with self._lock:
            self._current_id = request.playback_id
            self._current_sound = sound
        self._ui_updates.post_tts_play(
            request.character_name,
            request.audio_path,
            playback_id=request.playback_id,
            volume=request.volume,
        )
        signal(request.playback_id, PlaybackState.STARTED, "")
        threading.Thread(
            target=self._wait_for_channel,
            args=(request, signal),
            name=f"dialog-audio-{request.playback_id[:8]}",
            daemon=True,
        ).start()

    def stop(self, request: VoicePlaybackRequest) -> None:
        with self._lock:
            if self._current_id != request.playback_id:
                return
            sound = self._current_sound
            self._current_id = ""
            self._current_sound = None
        self._channel.stop()
        if sound is not None:
            try:
                sound.stop()
            except Exception:
                pass
        self._ui_updates.post_tts_skip(playback_id=request.playback_id)

    def _wait_for_channel(
        self,
        request: VoicePlaybackRequest,
        signal: PlaybackSignalHandler,
    ) -> None:
        try:
            while True:
                with self._lock:
                    if self._current_id != request.playback_id:
                        return
                if not self._channel.get_busy():
                    break
                time.sleep(self._poll_interval_seconds)
            with self._lock:
                if self._current_id != request.playback_id:
                    return
                self._current_id = ""
                self._current_sound = None
            signal(request.playback_id, PlaybackState.FINISHED, "")
        except Exception as exc:
            signal(request.playback_id, PlaybackState.FAILED, str(exc))
