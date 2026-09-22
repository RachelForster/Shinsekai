from __future__ import annotations

import time
import pytest
from threading import Event, Thread

from ai.asr.streaming_controller import StreamingASRController
from sdk.adapters.asr import ASRAdapter


@pytest.fixture
def hold_runtime():
    events, submitted, adapters = [], [], []
    def factory(callback):
        adapter = _FakeASRAdapter(callback)
        adapters.append(adapter)
        return adapter
    controller = StreamingASRController(
        adapter_factory=factory, emit_event=events.append,
        submit_final=submitted.append, silence_submit_seconds=0.01,
    )
    controller.begin_hold()
    _wait_until(lambda: controller._active)
    yield controller, adapters[0], events, submitted
    controller.close()


def test_hold_streams_segments_without_sending_until_release(hold_runtime):
    controller, adapter, events, submitted = hold_runtime
    adapter.callback("hello", False)
    adapter.callback("wor", True)
    time.sleep(0.03)
    assert submitted == []
    assert events[-1] == {"type": "asr.partial", "text": "hello wor"}
    def finish():
        adapter.callback("world", False)
        adapter.stop()
    adapter.finish = finish
    controller.finish_hold()
    controller.finish_hold()
    adapter.callback("late result", False)
    assert submitted == ["hello world"]
    assert not controller.enabled
    assert {"type": "asr.final", "text": "hello world"} in events
    controller.reply_finished()
    assert adapter.status == "Stopped"


def test_hold_cancel_discards_text_and_allows_next_recording(hold_runtime):
    controller, adapter, events, submitted = hold_runtime
    adapter.callback("discard", False)
    controller.finish_hold(cancel=True)
    assert submitted == []
    assert events[-1]["type"] == "asr.state"
    assert events[-1]["enabled"] is False
    controller.begin_hold()
    _wait_until(lambda: controller._active)
    adapter.callback("new", True)
    controller.finish_hold()
    assert submitted == ["new"]


def test_hold_reuses_adapter_that_can_stay_warm() -> None:
    adapters: list[_WarmHoldASRAdapter] = []
    events: list[dict] = []
    submitted: list[str] = []

    def factory(callback):
        adapter = _WarmHoldASRAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory,
        emit_event=events.append,
        submit_final=submitted.append,
    )
    try:
        controller.begin_hold()
        _wait_until(lambda: bool(adapters) and controller._active)
        adapter = adapters[0]
        adapter.callback("first", True)
        controller.finish_hold()

        assert submitted == ["first"]
        assert adapter.calls == ["start", "finish-hold"]
        assert controller._started is True
        assert controller._hold_adapter_warm is True

        warm_resume_event_index = len(events)
        controller.begin_hold()
        _wait_until(lambda: controller._active)
        adapter.callback("second", True)
        controller.finish_hold()

        assert submitted == ["first", "second"]
        assert adapter.calls == ["start", "finish-hold", "resume", "finish-hold"]
        assert len(adapters) == 1
        assert not any(
            event.get("type") == "asr.state" and event.get("loading")
            for event in events[warm_resume_event_index:]
        )
    finally:
        controller.close()


def test_cancelled_hold_can_keep_expensive_adapter_warm() -> None:
    adapters: list[_WarmHoldASRAdapter] = []
    submitted: list[str] = []

    def factory(callback):
        adapter = _WarmHoldASRAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory,
        emit_event=lambda _event: None,
        submit_final=submitted.append,
    )
    try:
        controller.begin_hold()
        _wait_until(lambda: bool(adapters) and controller._active)
        adapters[0].callback("discard", True)
        controller.finish_hold(cancel=True)
        controller.begin_hold()
        _wait_until(lambda: controller._active)

        assert submitted == []
        assert adapters[0].calls == ["start", "cancel-hold", "resume"]
    finally:
        controller.close()


def test_hold_empty_recording_does_not_submit(hold_runtime):
    controller, adapter, events, submitted = hold_runtime
    controller.finish_hold()
    assert submitted == []
    assert not controller.enabled


def test_hold_release_during_loading_does_not_start_capture():
    entered, release = Event(), Event()
    adapters, submitted = [], []
    def factory(callback):
        entered.set()
        assert release.wait(1)
        adapter = _FakeASRAdapter(callback)
        adapters.append(adapter)
        return adapter
    controller = StreamingASRController(adapter_factory=factory, emit_event=lambda event: None,
                                        submit_final=submitted.append)
    try:
        controller.begin_hold()
        assert entered.wait(1)
        controller.finish_hold()
        release.set()
        _wait_until(lambda: not controller._activating)
        assert "start" not in adapters[0].calls
        assert submitted == []
        controller.begin_hold()
        _wait_until(lambda: controller._active)
        adapters[0].callback("next hold", True)
        controller.finish_hold()
        assert submitted == ["next hold"]
    finally:
        release.set()
        controller.close()


def test_hold_finalization_failure_preserves_draft_without_sending(hold_runtime):
    controller, adapter, events, submitted = hold_runtime
    adapter.callback("draft", True)
    def finish():
        raise RuntimeError("decoder failed")
    adapter.finish = finish
    with pytest.raises(RuntimeError, match="decoder failed"):
        controller.finish_hold()
    assert submitted == []
    assert not controller.enabled
    assert adapter.status == "Stopped"


def test_hold_duplicate_begin_does_not_reset_transcript(hold_runtime):
    controller, adapter, events, submitted = hold_runtime
    adapter.callback("keep", True)
    controller.begin_hold()
    controller.finish_hold()
    assert submitted == ["keep"]


def test_hold_keeps_transcript_when_submission_is_rejected(hold_runtime):
    controller, adapter, events, submitted = hold_runtime
    adapter.callback("keep draft", True)
    controller._submit_final = lambda text: False
    with pytest.raises(RuntimeError, match="transcript was kept"):
        controller.finish_hold()
    assert not any(event.get("type") == "asr.final" for event in events)
    assert events[-2] == {"type": "asr.partial", "text": "keep draft"}
    assert events[-1]["enabled"] is False


def test_hold_publishes_final_only_after_submission_is_accepted(hold_runtime):
    controller, adapter, events, _submitted = hold_runtime
    adapter.callback("accepted", True)
    observed = []

    def submit(text):
        observed.append((text, any(event.get("type") == "asr.final" for event in events)))
        return True

    controller._submit_final = submit
    controller.finish_hold()

    assert observed == [("accepted", False)]
    assert {"type": "asr.final", "text": "accepted"} in events


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


class _WarmHoldASRAdapter(_FakeASRAdapter):
    def finish_hold(self, *, cancel: bool = False) -> bool:
        self.calls.append("cancel-hold" if cancel else "finish-hold")
        self.status = "Paused"
        return True


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
    assert events[-1] == {"type": "asr.partial", "text": "hello"}

    adapter.callback("hello world", False)
    assert submitted == ["hello world"]
    assert adapter.calls[-1] == "pause"
    assert events[-2:] == [
        {"type": "asr.final", "text": "hello world"},
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
        {"type": "asr.partial", "text": ""},
        {
            "type": "asr.state",
            "enabled": True,
            "loading": False,
            "running": True,
        },
    ]

    controller.close()
    assert adapter.calls[-1] == "stop"


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


def test_rejected_final_submission_resumes_listening_without_publishing_final() -> None:
    adapters: list[_FakeASRAdapter] = []
    events: list[dict] = []

    def factory(callback):
        adapter = _FakeASRAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory,
        emit_event=events.append,
        submit_final=lambda _text: False,
        resume_delay_seconds=0,
    )
    controller.user_resume()
    _wait_until(lambda: bool(adapters) and "start" in adapters[0].calls)

    adapters[0].callback("rejected", False)
    _wait_until(lambda: "resume" in adapters[0].calls)

    assert controller.enabled is True
    assert not any(event.get("type") == "asr.final" for event in events)
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

    assert {"type": "asr.final", "text": "silence fallback"} in events
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
