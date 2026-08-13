from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from application.runtime.audio_playback_controller import (
    FrontendVoicePlaybackBackend,
    PlaybackState,
    VoicePlaybackController,
)


class _FakeBackend:
    def __init__(self) -> None:
        self.request = None
        self.signal = None
        self.started = threading.Event()
        self.stopped_ids: list[str] = []

    def start(self, request, signal) -> None:
        self.request = request
        self.signal = signal
        self.started.set()

    def stop(self, request) -> None:
        self.stopped_ids.append(request.playback_id)


def _start_playback(controller: VoicePlaybackController, **kwargs):
    result: dict[str, object] = {}

    def run() -> None:
        result["value"] = controller.play_and_wait(
            character_name="Alice",
            audio_path="alice.wav",
            minimum_duration_seconds=0,
            timeout_seconds=1,
            **kwargs,
        )

    thread = threading.Thread(target=run)
    thread.start()
    return thread, result


def _wait_for_post_tts_play(ui_updates, timeout: float = 1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        call_args = ui_updates.post_tts_play.call_args
        if call_args is not None:
            return call_args.kwargs
        time.sleep(0.01)
    raise AssertionError("post_tts_play was not called")


def test_controller_blocks_until_matching_backend_finished_signal() -> None:
    backend = _FakeBackend()
    controller = VoicePlaybackController(backend)
    on_started = MagicMock()
    thread, result = _start_playback(controller, on_started=on_started)

    assert backend.started.wait(timeout=1)
    assert controller.is_active() is True
    assert thread.is_alive()
    assert backend.signal("stale-id", PlaybackState.FINISHED, "") is False
    assert thread.is_alive()

    assert backend.signal(
        backend.request.playback_id,
        PlaybackState.STARTED,
        "",
    ) is True
    on_started.assert_called_once_with()
    assert thread.is_alive()

    assert backend.signal(
        backend.request.playback_id,
        PlaybackState.FINISHED,
        "",
    ) is True
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert result["value"].state is PlaybackState.FINISHED
    assert controller.is_active() is False


def test_controller_interrupt_stops_backend_and_releases_waiter() -> None:
    backend = _FakeBackend()
    interrupt_event = threading.Event()
    controller = VoicePlaybackController(backend, interrupt_event=interrupt_event)
    thread, result = _start_playback(controller)

    assert backend.started.wait(timeout=1)
    assert controller.interrupt() is True
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert interrupt_event.is_set()
    assert backend.stopped_ids == [backend.request.playback_id]
    assert result["value"].state is PlaybackState.INTERRUPTED


def test_controller_interrupts_remaining_dialog_pacing_after_audio_finishes() -> None:
    backend = _FakeBackend()
    controller = VoicePlaybackController(backend)
    result: dict[str, object] = {}

    thread = threading.Thread(
        target=lambda: result.setdefault(
            "value",
            controller.play_and_wait(
                character_name="Alice",
                audio_path="short.wav",
                minimum_duration_seconds=5,
                timeout_seconds=1,
            ),
        )
    )
    thread.start()
    assert backend.started.wait(timeout=1)
    backend.signal(backend.request.playback_id, PlaybackState.FINISHED, "")

    assert thread.is_alive()
    assert controller.interrupt() is False
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert result["value"].state is PlaybackState.INTERRUPTED


def test_controller_uses_same_interrupt_event_for_non_audio_dialog_wait() -> None:
    controller = VoicePlaybackController(_FakeBackend())
    finished: list[bool] = []
    waiter = threading.Thread(
        target=lambda: finished.append(controller.wait_interruptibly(5))
    )
    waiter.start()

    controller.interrupt()
    waiter.join(timeout=1)

    assert finished == [False]


def test_controller_does_not_start_audio_after_dispatch_was_interrupted() -> None:
    backend = _FakeBackend()
    controller = VoicePlaybackController(backend)
    controller.interrupt()

    result = controller.play_and_wait(
        character_name="Alice",
        audio_path="cancelled.wav",
        minimum_duration_seconds=0,
        timeout_seconds=1,
    )

    assert result.state is PlaybackState.INTERRUPTED
    assert backend.request is None


def test_frontend_backend_emits_ids_and_waits_for_external_signal() -> None:
    ui_updates = SimpleNamespace(
        post_tts_play=MagicMock(),
        post_tts_skip=MagicMock(),
    )
    backend = FrontendVoicePlaybackBackend(ui_updates)
    controller = VoicePlaybackController(backend)
    thread, result = _start_playback(controller)

    assert thread.is_alive()
    play_kwargs = _wait_for_post_tts_play(ui_updates)
    playback_id = play_kwargs["playback_id"]
    assert play_kwargs["volume"] == 1.0
    assert controller.handle_signal(playback_id, "started") is True
    assert controller.handle_signal(playback_id, "finished") is True
    thread.join(timeout=1)

    assert result["value"].state is PlaybackState.FINISHED


def test_controller_rejects_terminal_signal_from_a_different_renderer() -> None:
    ui_updates = SimpleNamespace(
        post_tts_play=MagicMock(),
        post_tts_skip=MagicMock(),
    )
    controller = VoicePlaybackController(FrontendVoicePlaybackBackend(ui_updates))
    thread, result = _start_playback(controller)
    playback_id = _wait_for_post_tts_play(ui_updates)["playback_id"]

    assert controller.handle_signal(
        playback_id,
        "started",
        renderer_id="renderer-desktop",
    )
    assert not controller.handle_signal(
        playback_id,
        "finished",
        renderer_id="renderer-mobile",
    )
    assert thread.is_alive()
    assert controller.handle_signal(
        playback_id,
        "finished",
        renderer_id="renderer-desktop",
    )
    thread.join(timeout=1)

    assert result["value"].state is PlaybackState.FINISHED
