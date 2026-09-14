from __future__ import annotations

import time
from threading import Event, Thread
import pytest

from ai.asr.streaming_controller import ASRSubmissionResult, StreamingASRController
from sdk.adapters.asr import ASRAdapter


class _FakeASRAdapter(ASRAdapter):
    def __init__(self, callback, *, language: str = "en") -> None:
        super().__init__(language, callback)
        self.calls: list[str] = []
        self.status = "Stopped"

    def start(self) -> None:
        self.calls.append("start")
        self.status = "Running"

    def stop(self) -> None:
        self.calls.append("stop")
        self.status = "Stopped"

    def get_status(self) -> str:
        return self.status

    def pause(self) -> None:
        self.calls.append("pause")
        self.status = "Paused"

    def resume(self) -> None:
        self.calls.append("resume")
        self.status = "Running"


def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not met before timeout")


def test_streaming_asr_submits_final_and_resumes_after_reply() -> None:
    adapters: list[_FakeASRAdapter] = []
    events: list[dict] = []
    submitted: list[str] = []
    loading: list[bool] = []

    def factory(callback):
        adapter = _FakeASRAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory,
        emit_event=events.append,
        submit_final=submitted.append,
        on_loading_changed=loading.append,
        resume_delay_seconds=0.01,
    )

    controller.user_resume()
    _wait_until(lambda: bool(adapters) and "start" in adapters[0].calls)
    adapter = adapters[0]
    assert loading == [True, False]
    assert {
        "type": "asr.state",
        "enabled": True,
        "loading": True,
        "running": False,
    } in events
    assert events[-1] == {
        "type": "asr.state",
        "enabled": True,
        "loading": False,
        "running": True,
    }

    adapter.callback("hello", True)
    utterance_id = events[-1]["utteranceId"]
    assert events[-1] == {"type": "asr.partial", "text": "hello", "utteranceId": utterance_id}

    adapter.callback("hello world", False)
    assert submitted == ["hello world"]
    assert adapter.calls[-1] == "pause"
    assert events[-2:] == [
        {"type": "asr.final", "text": "hello world", "utteranceId": utterance_id},
        {
            "type": "asr.state",
            "enabled": True,
            "loading": False,
            "running": False,
        },
    ]

    controller.reply_finished()
    _wait_until(lambda: "resume" in adapter.calls)
    assert events[-2:] == [
        {"type": "asr.partial", "text": "", "utteranceId": controller._utterance_id},
        {
            "type": "asr.state",
            "enabled": True,
            "loading": False,
            "running": True,
        },
    ]

    controller.close()
    assert adapter.calls[-1] == "stop"


def test_continuous_listening_submits_each_final_without_pausing_for_reply() -> None:
    adapters: list[_FakeASRAdapter] = []
    events: list[dict] = []
    submitted: list[str] = []

    controller = StreamingASRController(
        adapter_factory=lambda callback: adapters.append(_FakeASRAdapter(callback)) or adapters[-1],
        emit_event=events.append,
        submit_final=submitted.append,
        continuous_listening=True,
    )
    controller.user_resume()
    _wait_until(lambda: bool(adapters) and "start" in adapters[0].calls)
    adapter = adapters[0]

    assert controller.pause_for_turn() is False
    adapter.callback("first phrase", False)
    adapter.callback("second phrase", False)

    assert submitted == ["first phrase", "second phrase"]
    finals = [event for event in events if event["type"] == "asr.final"]
    assert [event["text"] for event in finals] == ["first phrase", "second phrase"]
    assert finals[0]["utteranceId"] != finals[1]["utteranceId"]
    assert "pause" not in adapter.calls
    assert adapter.get_status() == "Running"
    controller.reply_finished()
    assert events[-1] == {
        "type": "asr.state",
        "enabled": True,
        "loading": False,
        "running": True,
    }
    controller.close()


def test_continuous_listening_restores_rejected_final_as_draft() -> None:
    adapters: list[_FakeASRAdapter] = []
    events: list[dict] = []
    controller = StreamingASRController(
        adapter_factory=lambda callback: adapters.append(_FakeASRAdapter(callback)) or adapters[-1],
        emit_event=events.append,
        submit_final=lambda _text: False,
        continuous_listening=True,
    )
    controller.user_resume()
    _wait_until(lambda: bool(adapters) and "start" in adapters[0].calls)

    adapters[0].callback("keep this", False)

    assert events[-1] == {"type": "asr.partial", "text": "keep this", "utteranceId": events[-1]["utteranceId"]}
    assert not any(event["type"] == "asr.final" for event in events)
    assert "pause" not in adapters[0].calls
    controller.close()


def test_continuous_listening_keeps_deferred_final_as_draft() -> None:
    adapters: list[_FakeASRAdapter] = []
    events: list[dict] = []
    controller = StreamingASRController(
        adapter_factory=lambda callback: adapters.append(_FakeASRAdapter(callback)) or adapters[-1],
        emit_event=events.append,
        submit_final=lambda _text: ASRSubmissionResult(accepted=True, admitted=False),
        continuous_listening=True,
    )
    controller.user_resume()
    _wait_until(lambda: bool(adapters) and "start" in adapters[0].calls)

    adapters[0].callback("queued voice", False)

    assert events[-1] == {"type": "asr.partial", "text": "queued voice", "utteranceId": events[-1]["utteranceId"]}
    assert not any(event["type"] == "asr.final" for event in events)
    controller.close()


def test_user_pause_cancels_automatic_resume() -> None:
    adapters: list[_FakeASRAdapter] = []
    events: list[dict] = []

    def factory(callback):
        adapter = _FakeASRAdapter(callback, language="zh")
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory,
        emit_event=events.append,
        submit_final=lambda _text: None,
        resume_delay_seconds=0.01,
    )
    controller.user_resume()
    _wait_until(lambda: bool(adapters) and "start" in adapters[0].calls)
    adapter = adapters[0]

    adapter.callback("你 好", False)
    controller.user_pause()
    assert adapter.calls[-1] == "stop"
    resume_count = adapter.calls.count("resume")
    controller.reply_finished()
    time.sleep(0.03)

    assert adapter.calls.count("resume") == resume_count
    assert controller.enabled is False
    assert events[-1] == {
        "type": "asr.state",
        "enabled": False,
        "loading": False,
        "running": False,
    }
    controller.close()


def test_user_resume_starts_capture_again_after_user_pause_released_it() -> None:
    adapters: list[_FakeASRAdapter] = []

    def factory(callback):
        adapter = _FakeASRAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory,
        emit_event=lambda _event: None,
        submit_final=lambda _text: None,
    )
    controller.user_resume()
    _wait_until(lambda: bool(adapters) and adapters[0].calls == ["start"])

    controller.user_pause()
    assert adapters[0].calls == ["start", "stop"]

    controller.user_resume()
    _wait_until(lambda: adapters[0].calls == ["start", "stop", "start"])
    controller.close()


def test_failed_adapter_start_does_not_report_listening() -> None:
    events: list[dict] = []
    errors: list[tuple[str, str]] = []

    class _FailedAdapter(_FakeASRAdapter):
        def start(self) -> None:
            self.calls.append("start")
            self.status = "Stopped"

    controller = StreamingASRController(
        adapter_factory=lambda callback: _FailedAdapter(callback),
        emit_event=events.append,
        submit_final=lambda _text: None,
        on_error=lambda operation, exc: errors.append((operation, str(exc))),
    )

    controller.user_resume()
    _wait_until(lambda: bool(errors))

    assert errors[0][0] == "start"
    assert "did not enter a running state" in errors[0][1]
    assert controller.enabled is False
    assert events[-1] == {
        "type": "asr.state",
        "enabled": False,
        "loading": False,
        "running": False,
    }
    controller.close()


def test_rejected_final_submission_resumes_listening() -> None:
    adapters: list[_FakeASRAdapter] = []

    def factory(callback):
        adapter = _FakeASRAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory,
        emit_event=lambda _event: None,
        submit_final=lambda _text: False,
        resume_delay_seconds=0,
    )
    controller.user_resume()
    _wait_until(lambda: bool(adapters) and "start" in adapters[0].calls)

    adapters[0].callback("rejected", False)
    _wait_until(lambda: "resume" in adapters[0].calls)

    assert controller.enabled is True
    controller.close()


def test_close_waits_for_inflight_callback_and_suppresses_later_events() -> None:
    adapters: list[_FakeASRAdapter] = []
    callback_entered = Event()
    release_callback = Event()
    close_finished = Event()
    events: list[dict] = []

    def emit(event: dict) -> None:
        events.append(event)
        if event.get("type") == "asr.partial" and event.get("text") == "blocking":
            callback_entered.set()
            assert release_callback.wait(timeout=1)

    controller = StreamingASRController(
        adapter_factory=lambda callback: adapters.append(_FakeASRAdapter(callback)) or adapters[-1],
        emit_event=emit,
        submit_final=lambda _text: None,
    )
    controller.user_resume()
    _wait_until(lambda: bool(adapters) and "start" in adapters[0].calls)

    callback_thread = Thread(target=adapters[0].callback, args=("blocking", True))
    callback_thread.start()
    assert callback_entered.wait(timeout=1)

    close_thread = Thread(target=lambda: (controller.close(), close_finished.set()))
    close_thread.start()
    assert not close_finished.wait(timeout=0.02)
    release_callback.set()
    assert close_finished.wait(timeout=1)
    callback_thread.join(timeout=1)
    close_thread.join(timeout=1)

    event_count = len(events)
    adapters[0].callback("too late", True)
    assert len(events) == event_count


def test_turn_pause_keeps_asr_enabled_until_the_user_disables_it() -> None:
    adapters: list[_FakeASRAdapter] = []
    events: list[dict] = []

    def factory(callback):
        adapter = _FakeASRAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory,
        emit_event=events.append,
        submit_final=lambda _text: None,
        resume_delay_seconds=0.01,
    )
    controller.user_resume()
    _wait_until(lambda: bool(adapters) and "start" in adapters[0].calls)

    assert controller.pause_for_turn() is True
    assert controller.enabled is True
    assert events[-1] == {
        "type": "asr.state",
        "enabled": True,
        "loading": False,
        "running": False,
    }

    controller.user_pause()
    assert controller.enabled is False
    assert controller.pause_for_turn() is False
    controller.close()


def test_partial_transcript_is_submitted_after_silence_without_adapter_final() -> None:
    adapters: list[_FakeASRAdapter] = []
    events: list[dict] = []
    submitted: list[str] = []

    def factory(callback):
        adapter = _FakeASRAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory,
        emit_event=events.append,
        submit_final=submitted.append,
        silence_submit_seconds=0.01,
    )
    controller.user_resume()
    _wait_until(lambda: bool(adapters) and "start" in adapters[0].calls)
    adapter = adapters[0]

    adapter.callback("silence fallback", True)
    _wait_until(lambda: submitted == ["silence fallback"])

    assert any(event["type"] == "asr.final" and event["text"] == "silence fallback" for event in events)
    assert adapter.calls[-1] == "pause"
    adapter.callback("silence fallback", False)
    assert submitted == ["silence fallback"]
    controller.close()


def test_default_silence_window_allows_natural_speech_pauses() -> None:
    adapters: list[_FakeASRAdapter] = []

    def factory(callback):
        adapter = _FakeASRAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory,
        emit_event=lambda _event: None,
        submit_final=lambda _text: None,
    )
    controller.user_resume()
    _wait_until(lambda: bool(adapters) and "start" in adapters[0].calls)

    adapters[0].callback("keep listening", True)

    assert controller._silence_timer is not None
    assert controller._silence_timer.interval == 3.5
    controller.close()


def test_user_pause_cancels_pending_silence_submission() -> None:
    adapters: list[_FakeASRAdapter] = []
    submitted: list[str] = []

    def factory(callback):
        adapter = _FakeASRAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory,
        emit_event=lambda _event: None,
        submit_final=submitted.append,
        silence_submit_seconds=0.01,
    )
    controller.user_resume()
    _wait_until(lambda: bool(adapters) and "start" in adapters[0].calls)

    adapters[0].callback("do not submit", True)
    controller.user_pause()
    time.sleep(0.03)

    assert submitted == []
    controller.close()


def test_repeated_identical_partials_do_not_postpone_silence_submission() -> None:
    adapters: list[_FakeASRAdapter] = []

    def factory(callback):
        adapter = _FakeASRAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory,
        emit_event=lambda _event: None,
        submit_final=lambda _text: None,
        silence_submit_seconds=30,
    )
    controller.user_resume()
    _wait_until(lambda: bool(adapters) and "start" in adapters[0].calls)

    adapters[0].callback("stable transcript", True)
    original_timer = controller._silence_timer
    adapters[0].callback("stable transcript", True)

    assert original_timer is not None
    assert controller._silence_timer is original_timer
    controller.close()


def test_user_can_cancel_and_restart_lazy_adapter_loading() -> None:
    factory_entered = Event()
    release_factory = Event()
    adapters: list[_FakeASRAdapter] = []

    def factory(callback):
        factory_entered.set()
        assert release_factory.wait(timeout=1.0)
        adapter = _FakeASRAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory,
        emit_event=lambda _event: None,
        submit_final=lambda _text: None,
    )
    controller.user_resume()
    assert factory_entered.wait(timeout=1.0)
    controller.user_pause()
    release_factory.set()
    _wait_until(lambda: bool(adapters))
    time.sleep(0.01)
    assert "start" not in adapters[0].calls

    controller.user_resume()
    _wait_until(lambda: "start" in adapters[0].calls)
    controller.close()


@pytest.mark.parametrize("late_partial,late_final", [("hello", "hello"), ("hello world", "hello world"), (None, "corrected final")])
def test_continuous_fallback_suppresses_late_events_then_allows_repeated_utterance(late_partial, late_final):
    submitted = []
    events = []
    controller = StreamingASRController(
        adapter_factory=_FakeASRAdapter, emit_event=events.append,
        submit_final=submitted.append, continuous_listening=True,
        silence_submit_seconds=300,
    )
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        adapter = controller._adapter
        adapter.callback("hello", True)
        timer = controller._silence_timer
        timer.function(*timer.args, **timer.kwargs)
        assert submitted == ["hello"]
        event_count = len(events)
        if late_partial is not None:
            adapter.callback(late_partial, True)
        adapter.callback(late_final, False)
        assert submitted == ["hello"]
        assert len(events) == event_count
        adapter.callback("hello", True)
        adapter.callback("hello", False)
        assert submitted == ["hello", "hello"]
        finals = [event for event in events if event["type"] == "asr.final"]
        assert finals[0]["utteranceId"] != finals[1]["utteranceId"]
    finally:
        controller.close()


def test_continuous_fallback_allows_dissimilar_new_partial_without_engine_final():
    submitted = []
    controller = StreamingASRController(
        adapter_factory=_FakeASRAdapter, emit_event=lambda event: None,
        submit_final=submitted.append, continuous_listening=True, silence_submit_seconds=300,
    )
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        controller._adapter.callback("first", True)
        timer = controller._silence_timer
        timer.function(*timer.args, **timer.kwargs)
        controller._adapter.callback("second", True)
        controller._adapter.callback("second", False)
        assert submitted == ["first", "second"]
    finally:
        controller.close()


def test_continuous_draft_is_published_before_inline_admission():
    events = []

    def submit(text, utterance_id):
        events.append({"type": "asr.final", "text": text, "utteranceId": utterance_id})
        return ASRSubmissionResult(True, True)

    controller = StreamingASRController(
        adapter_factory=_FakeASRAdapter, emit_event=events.append,
        submit_final=lambda text: pytest.fail("legacy callback must not be used"),
        submit_utterance=submit, continuous_listening=True,
    )
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        controller._adapter.callback("hello word", True)
        partial_id = events[-1]["utteranceId"]
        controller._adapter.callback("hello world", False)
        assert events[-1] == {"type": "asr.final", "text": "hello world", "utteranceId": partial_id}
        assert events[-2] == {"type": "asr.partial", "text": "hello world", "utteranceId": partial_id}
    finally:
        controller.close()


def test_noncontinuous_result_object_rejection_recovers():
    controller = StreamingASRController(
        adapter_factory=_FakeASRAdapter, emit_event=lambda event: None,
        submit_final=lambda text: ASRSubmissionResult(False, False),
    )
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        controller._adapter.callback("rejected", False)
        _wait_until(lambda: controller._active)
        assert controller._adapter.calls == ["start", "pause", "resume"]
    finally:
        controller.close()


@pytest.mark.parametrize("block_stage", ["load", "start"])
def test_history_boundary_during_activation_fences_old_adapter(block_stage):
    entered, release = Event(), Event()
    adapters = []
    submitted = []

    class SlowAdapter(_FakeASRAdapter):
        def start(self):
            if block_stage == "start" and self is adapters[0]:
                entered.set()
                assert release.wait(2)
            super().start()

    def factory(callback):
        adapter = SlowAdapter(callback)
        adapters.append(adapter)
        if block_stage == "load" and len(adapters) == 1:
            entered.set()
            assert release.wait(2)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory, emit_event=lambda event: None,
        submit_final=submitted.append, continuous_listening=True,
    )
    try:
        controller.user_resume()
        assert entered.wait(1)
        with controller.input_boundary():
            adapters[0].callback("old during boundary", False)
        release.set()
        _wait_until(lambda: controller._active and len(adapters) == 2)
        adapters[0].callback("old after boundary", False)
        adapters[1].callback("fresh", False)
        assert submitted == ["fresh"]
        assert adapters[0].status == "Stopped"
    finally:
        release.set()
        controller.close()


def test_boundary_does_not_enable_a_user_paused_microphone():
    events = []
    controller = StreamingASRController(
        adapter_factory=_FakeASRAdapter, emit_event=events.append, submit_final=lambda text: None,
    )
    try:
        with controller.input_boundary():
            pass
        assert not controller.enabled
        assert events[-1] == {"type": "asr.state", "enabled": False, "loading": False, "running": False}
    finally:
        controller.close()
