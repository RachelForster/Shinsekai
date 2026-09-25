from __future__ import annotations

import time
from threading import Event, Thread
import pytest

from ai.asr.streaming_controller import ASRSubmissionResult, StreamingASRController
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
        "continuous": True, "type": "asr.state",
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

    assert events[-1] == {"continuous": True, "type": "asr.partial", "text": "keep this", "utteranceId": events[-1]["utteranceId"]}
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

    assert events[-1] == {"continuous": True, "type": "asr.partial", "text": "queued voice", "utteranceId": events[-1]["utteranceId"]}
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

    assert any(event["type"] == "asr.final" and event["text"] == "silence fallback" for event in events)
    _wait_until(lambda: adapter.calls[-1] == "pause")
    assert adapter.calls == ["start", "pause"]
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



@pytest.mark.parametrize("late_partial,late_final", [("hello", "hello"), ("hello world", "hello world"), ("corrected old words", "corrected final")])
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
        _wait_until(lambda: controller._active and controller._adapter is not adapter)
        assert adapter.status == "Stopped"
        event_count = len(events)
        if late_partial is not None:
            adapter.callback(late_partial, True)
        adapter.callback(late_final, False)
        assert submitted == ["hello"]
        assert len(events) == event_count
        controller._adapter.callback("hello", True)
        controller._adapter.callback("hello", False)
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
        old_adapter = controller._adapter
        timer = controller._silence_timer
        timer.function(*timer.args, **timer.kwargs)
        _wait_until(lambda: controller._active and controller._adapter is not old_adapter)
        controller._adapter.callback("second", True)
        controller._adapter.callback("second", False)
        assert submitted == ["first", "second"]
    finally:
        controller.close()



@pytest.mark.parametrize("phrases", [
    ["麦克输入测试", "第一笔语音讯息", "第二笔语音讯息"],
    ["重复这句话", "重复这句话", "重复这句话"],
])
def test_continuous_fallback_starts_fresh_audio_for_each_sentence(phrases):
    class CumulativeAdapter(_FakeASRAdapter):
        def __init__(self, callback):
            super().__init__(callback, language="zh")
            self.audio_text = ""

        def hear(self, text):
            # Like faster-whisper without a quiet RMS endpoint: every partial
            # retranscribes all audio captured since the last endpoint.
            self.audio_text += text
            self.callback(self.audio_text, True)

    submitted, events, retired = [], [], []
    controller = StreamingASRController(
        adapter_factory=CumulativeAdapter, emit_event=events.append,
        submit_final=submitted.append, continuous_listening=True, silence_submit_seconds=300,
    )
    try:
        controller.user_resume()
        for index, phrase in enumerate(phrases):
            _wait_until(lambda: controller._active)
            adapter = controller._adapter
            old_callback = adapter.callback
            adapter.hear(phrase)
            timer = controller._silence_timer
            timer.function(*timer.args, **timer.kwargs)
            retired.append(adapter)
            _wait_until(lambda: controller._active)
            for old in retired:
                old.callback("辨识修正后的旧句子" + old.audio_text, True)
                old.callback(old.audio_text, False)
            assert submitted == phrases[:index + 1]
            transcripts = [e for e in events if e["type"] in {"asr.partial", "asr.final"}]
            assert transcripts[-1]["type"] == "asr.final"
            assert transcripts[-1]["text"] == phrase
        finals = [e for e in events if e["type"] == "asr.final"]
        assert len({e["utteranceId"] for e in finals}) == 3
        assert all(a.calls == ["start", "stop"] for a in retired)
    finally:
        controller.close()



@pytest.mark.parametrize("phrases", [
    ["第一句", "第二句", "第三句"],
    ["重复这句话", "重复这句话", "重复这句话"],
])
def test_normal_fallback_discards_audio_before_resuming_after_reply(phrases):
    class CumulativeAdapter(_FakeASRAdapter):
        def __init__(self, callback):
            super().__init__(callback, language="zh")
            self.audio_text = ""

        def reset_capture(self, next_callback):
            self.audio_text = ""
            self.callback = next_callback
            self.calls.append("reset")

        def hear(self, text):
            self.audio_text += text
            self.callback(self.audio_text, True)

    submitted, events, adapters = [], [], []

    def factory(callback):
        adapter = CumulativeAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory, emit_event=events.append,
        submit_final=submitted.append, continuous_listening=False,
        silence_submit_seconds=300, resume_delay_seconds=0,
    )
    try:
        controller.user_resume()
        for index, phrase in enumerate(phrases):
            _wait_until(lambda: controller._active)
            adapter = controller._adapter
            old_callback = adapter.callback
            adapter.hear(phrase)
            timer = controller._silence_timer
            timer.function(*timer.args, **timer.kwargs)
            assert submitted == phrases[:index + 1]
            assert not controller._active
            assert controller._turn_paused
            # No replacement may start before the reply ends.
            assert len(adapters) == 1
            controller.reply_finished()
            _wait_until(lambda: controller._active)
            event_count = len(events)
            old_callback("修正后的旧句子" + adapter.audio_text, True)
            old_callback(adapter.audio_text, False)
            assert len(events) == event_count
            assert submitted == phrases[:index + 1]
        assert len(adapters) == 1
        assert adapters[0].calls.count("reset") == len(phrases)
        finals = [e for e in events if e["type"] == "asr.final"]
        assert len(finals) == len(phrases)
    finally:
        controller.close()



@pytest.mark.parametrize("continuous", [True])
def test_fallback_releases_callback_lock_before_stopping_capture(continuous):
    callbacks_finished = []

    class JoiningAdapter(_FakeASRAdapter):
        def stop(self):
            callback_thread = Thread(target=lambda: self.callback("late final at shutdown", False))
            callback_thread.start()
            callback_thread.join(timeout=1)
            callbacks_finished.append(not callback_thread.is_alive())
            super().stop()

    submitted = []
    controller = StreamingASRController(
        adapter_factory=JoiningAdapter, emit_event=lambda event: None,
        submit_final=submitted.append, continuous_listening=continuous, silence_submit_seconds=300,
    )
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        controller._adapter.callback("first", True)
        timer = controller._silence_timer
        timer.function(*timer.args, **timer.kwargs)
        assert callbacks_finished == [True]
        assert submitted == ["first"]
    finally:
        controller.close()



@pytest.mark.parametrize("action", ["pause", "close", "pause-resume"])
@pytest.mark.parametrize("continuous", [True])
def test_fallback_teardown_respects_user_lifecycle(action, continuous):
    entered, release = Event(), Event()
    adapters, submitted = [], []

    class SlowStopAdapter(_FakeASRAdapter):
        def stop(self):
            if self is adapters[0]:
                entered.set()
                assert release.wait(2)
            super().stop()

    def factory(callback):
        adapter = SlowStopAdapter(callback)
        adapters.append(adapter)
        return adapter

    controller = StreamingASRController(
        adapter_factory=factory, emit_event=lambda event: None,
        submit_final=submitted.append, continuous_listening=continuous, silence_submit_seconds=300,
    )
    fallback_thread = None
    close_thread = None
    close_finished = Event()
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        adapters[0].callback("first", True)
        timer = controller._silence_timer
        fallback_thread = Thread(target=lambda: timer.function(*timer.args, **timer.kwargs))
        fallback_thread.start()
        assert entered.wait(1)
        if action == "close":
            close_thread = Thread(target=lambda: (controller.close(), close_finished.set()))
            close_thread.start()
            _wait_until(lambda: not controller.enabled)
            assert not close_finished.wait(.02)
        else:
            controller.user_pause()
            if action == "pause-resume":
                controller.user_resume()
        assert len(adapters) == 1  # A second microphone cannot start during stop().
        adapters[0].callback("corrected old final", False)
        release.set()
        fallback_thread.join(1)
        assert not fallback_thread.is_alive()
        if action == "pause-resume":
            _wait_until(lambda: controller._active and len(adapters) == 2)
            adapters[1].callback("second", False)
            assert submitted == ["first", "second"]
        else:
            if close_thread is not None:
                assert close_finished.wait(1)
                close_thread.join(1)
                assert adapters[0].status == "Stopped"
            assert not controller.enabled
            assert len(adapters) == 1
            assert submitted == ["first"]
    finally:
        release.set()
        if fallback_thread is not None:
            fallback_thread.join(1)
        if close_thread is not None:
            close_thread.join(1)
        controller.close()



@pytest.mark.parametrize("continuous", [True])
def test_rejected_fallback_still_retires_old_capture(continuous):
    controller = StreamingASRController(
        adapter_factory=_FakeASRAdapter, emit_event=lambda event: None,
        submit_final=lambda text: ASRSubmissionResult(False, False),
        continuous_listening=continuous, silence_submit_seconds=300,
    )
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        old_adapter = controller._adapter
        old_adapter.callback("rejected", True)
        timer = controller._silence_timer
        timer.function(*timer.args, **timer.kwargs)
        _wait_until(lambda: controller._active and controller._adapter is not old_adapter)
        old_adapter.callback("rejected with more old words", True)
        assert controller._current_text == ""
        assert old_adapter.status == "Stopped"
    finally:
        controller.close()



def test_normal_fallback_immediate_reply_waits_for_capture_reset():
    errors = []

    class ResetAdapter(_FakeASRAdapter):
        def reset_capture(self, next_callback):
            self.callback = next_callback
            self.calls.append("reset")

    def submit(text):
        controller.reply_finished()
        timer = controller._resume_timer
        timer.cancel()
        timer.function(*timer.args, **timer.kwargs)
        assert not controller._activating
        assert controller._adapter.calls == ["start", "pause"]
        return True

    controller = StreamingASRController(
        adapter_factory=ResetAdapter, emit_event=lambda event: None,
        submit_final=submit, continuous_listening=False,
        silence_submit_seconds=300, resume_delay_seconds=300,
        on_error=lambda operation, exc: errors.append((operation, exc)),
    )
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        old_adapter = controller._adapter
        old_adapter.callback("first", True)
        timer = controller._silence_timer
        timer.function(*timer.args, **timer.kwargs)
        _wait_until(lambda: controller._active and controller._adapter is old_adapter)
        assert old_adapter.calls == ["start", "pause", "reset", "resume"]
        assert errors == []
    finally:
        controller.close()



def test_continuous_draft_is_published_before_inline_admission():
    events = []

    def submit(text, utterance_id):
        events.append({"continuous": True, "type": "asr.final", "text": text, "utteranceId": utterance_id})
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
        assert events[-1] == {"continuous": True, "type": "asr.final", "text": "hello world", "utteranceId": partial_id}
        assert events[-2] == {"continuous": True, "type": "asr.partial", "text": "hello world", "utteranceId": partial_id}
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
