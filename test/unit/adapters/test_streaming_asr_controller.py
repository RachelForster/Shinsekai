from __future__ import annotations

import time
from threading import Event

from asr.streaming_controller import StreamingASRController
from sdk.adapters.asr import ASRAdapter


class _FakeASRAdapter(ASRAdapter):
    def __init__(self, callback, *, language: str = "en") -> None:
        super().__init__(language, callback)
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> None:
        self.calls.append("stop")

    def get_status(self) -> str:
        return self.calls[-1] if self.calls else "idle"

    def pause(self) -> None:
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")


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
