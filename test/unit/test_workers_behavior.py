from __future__ import annotations

import threading
import time
from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


from core.runtime.app_runtime import AppRuntime, get_app_runtime, set_app_runtime
from core.runtime.workers import LLMWorker, TTSWorker, UIWorker
from sdk.messages import LLMDialogMessage, TTSOutputMessage, UserInputMessage


pytestmark = pytest.mark.unit


class CountingQueue(Queue):
    def __init__(self) -> None:
        super().__init__()
        self.task_done_calls = 0

    def task_done(self) -> None:
        self.task_done_calls += 1
        super().task_done()


class FakeEvent:
    def __init__(self) -> None:
        self.set_calls = 0
        self.wait_calls: list[float | None] = []
        self._set = False

    def set(self) -> None:
        self.set_calls += 1
        self._set = True

    def clear(self) -> None:
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def wait(self, timeout: float | None = None) -> bool:
        self.wait_calls.append(timeout)
        return self._set


@pytest.fixture(autouse=True)
def _isolate_app_runtime() -> None:
    """Save/restore the module-level app runtime so tests don't leak."""
    from core.runtime import app_runtime as _mod

    saved = getattr(_mod, "_runtime", None)
    _mod._runtime = None
    yield
    _mod._runtime = saved


def _make_app_runtime(
    tts_queue: Queue | None = None,
    audio_path_queue: Queue | None = None,
    ui_manager: MagicMock | None = None,
) -> AppRuntime:
    runtime = AppRuntime(
        config=MagicMock(),
        ui_update_manager=ui_manager or MagicMock(chat_history=[]),
        llm_manager=MagicMock(),
        tts_manager=None,
        t2i_manager=None,
        bgm_list=[],
        user_input_queue=Queue(),
        tts_queue=tts_queue or CountingQueue(),
        audio_path_queue=audio_path_queue or CountingQueue(),
        text_processor=MagicMock(),
        opencc=SimpleNamespace(convert=lambda value: f"converted:{value}"),
    )
    set_app_runtime(runtime)
    return runtime


def test_workers_keep_original_queue_attributes_and_bind_ports() -> None:
    _make_app_runtime()
    user_input_queue = Queue()
    tts_queue = Queue()
    audio_path_queue = Queue()

    llm_worker = LLMWorker(user_input_queue, tts_queue)
    tts_worker = TTSWorker(tts_queue, audio_path_queue)
    ui_worker = UIWorker(audio_path_queue)

    assert llm_worker.user_input_queue is user_input_queue
    assert llm_worker.tts_queue is tts_queue
    assert llm_worker.inq(LLMWorker.PORT_USER_INPUT) is user_input_queue
    assert llm_worker.outq(LLMWorker.PORT_LLM_OUTPUT) is tts_queue

    assert tts_worker.tts_queue is tts_queue
    assert tts_worker.audio_path_queue is audio_path_queue
    assert tts_worker.inq(TTSWorker.PORT_LLM_OUTPUT) is tts_queue
    assert tts_worker.outq(TTSWorker.PORT_TTS_OUTPUT) is audio_path_queue

    assert ui_worker.audio_path_queue is audio_path_queue
    assert ui_worker.inq(UIWorker.PORT_TTS_OUTPUT) is audio_path_queue


def test_llm_worker_run_uses_original_queues_and_marks_input_done(
    monkeypatch,
) -> None:
    user_input_queue = CountingQueue()
    tts_queue = CountingQueue()
    user_input_queue.put(UserInputMessage(text="hello"))
    user_input_queue.put(None)

    runtime = _make_app_runtime()
    runtime.config.config.api_config.is_streaming = False
    runtime.llm_manager.chat.return_value = (
        '{"character_name":"Alice","speech":"Hi","sprite":"0"}'
    )

    worker = LLMWorker(user_input_queue, tts_queue)
    monkeypatch.setattr(worker, "_init_app", lambda: None)
    worker.ui_update_manager = runtime.ui_update_manager
    worker.llm_manager = runtime.llm_manager

    worker.run()

    output = tts_queue.get_nowait()
    assert isinstance(output, LLMDialogMessage)
    assert output.name == "Alice"
    assert output.text == "Hi"
    assert user_input_queue.task_done_calls == 2
    assert user_input_queue.unfinished_tasks == 0
    runtime.llm_manager.chat.assert_called_once_with("hello", stream=False)


def test_tts_worker_exception_path_uses_original_put_data_fallback(
    monkeypatch,
) -> None:
    tts_queue = CountingQueue()
    audio_path_queue = CountingQueue()
    tts_queue.put(LLMDialogMessage(name="Alice", text="broken", asset_id="2", effect="shake"))
    tts_queue.put(None)
    _make_app_runtime(tts_queue=tts_queue, audio_path_queue=audio_path_queue)

    worker = TTSWorker(tts_queue, audio_path_queue)
    monkeypatch.setattr(worker, "_init_app", lambda: None)
    worker.tts_message_dispatcher = SimpleNamespace(
        dispatch=MagicMock(side_effect=RuntimeError("tts failed"))
    )

    worker.run()

    output = audio_path_queue.get_nowait()
    assert isinstance(output, TTSOutputMessage)
    assert output.name == "converted:Alice"
    assert output.text == "broken"
    assert output.asset_id == "2"
    assert output.effect == "shake"
    assert tts_queue.task_done_calls == 2
    assert tts_queue.unfinished_tasks == 0


def test_tts_worker_start_clears_previous_cancel_state(monkeypatch) -> None:
    worker = TTSWorker(Queue(), Queue())
    worker._cancel_event.set()
    starts = []

    monkeypatch.setattr(
        "core.runtime.workers.QThreadDagNode.start",
        lambda self: starts.append(self),
    )

    worker.start()

    assert not worker._cancel_event.is_set()
    assert starts == [worker]


def test_tts_worker_drops_dispatch_output_after_cancel() -> None:
    audio_path_queue = CountingQueue()
    _make_app_runtime(audio_path_queue=audio_path_queue)
    worker = TTSWorker(CountingQueue(), audio_path_queue)
    started = threading.Event()
    release = threading.Event()
    attempted_emit = threading.Event()

    def dispatch(_item):
        started.set()
        assert release.wait(timeout=1)
        get_app_runtime().audio_path_queue.put(
            TTSOutputMessage(
                audio_path="late.wav",
                name="Alice",
                text="late",
                asset_id="-1",
            )
        )
        attempted_emit.set()

    worker.tts_message_dispatcher = SimpleNamespace(dispatch=dispatch)
    runner = threading.Thread(
        target=worker._dispatch_with_cancel,
        args=(LLMDialogMessage(name="Alice", text="hello", asset_id="-1"),),
    )

    runner.start()
    assert started.wait(timeout=1)
    worker._cancel_event.set()
    release.set()
    assert attempted_emit.wait(timeout=1)
    runner.join(timeout=1)

    assert not runner.is_alive()
    assert audio_path_queue.empty()
    for _ in range(20):
        if get_app_runtime().audio_path_queue is audio_path_queue:
            break
        time.sleep(0.01)
    assert get_app_runtime().audio_path_queue is audio_path_queue


def test_ui_worker_skip_speech_is_noop_when_queue_empty() -> None:
    audio_path_queue = Queue()
    _make_app_runtime(audio_path_queue=audio_path_queue)
    worker = UIWorker(audio_path_queue)
    worker.task_done_requested = FakeEvent()
    worker.current_audio_path = "current.wav"
    worker.dialog_channel = MagicMock()

    worker.skip_speech()

    worker.dialog_channel.stop.assert_not_called()
    assert worker.current_audio_path == "current.wav"
    assert worker.task_done_requested.set_calls == 0


def test_ui_worker_exception_branch_keeps_original_wait_and_task_done(
    monkeypatch,
) -> None:
    audio_path_queue = CountingQueue()
    audio_path_queue.put(
        TTSOutputMessage(
            audio_path="",
            name="Alice",
            text="1234567890",
            asset_id="-1",
            effect="",
        )
    )
    audio_path_queue.put(None)
    ui_manager = MagicMock()
    _make_app_runtime(audio_path_queue=audio_path_queue, ui_manager=ui_manager)

    worker = UIWorker(audio_path_queue)
    fake_event = FakeEvent()
    monkeypatch.setattr(worker, "_init_app", lambda: None)
    worker.task_done_requested = fake_event
    worker.ui_update_manager = ui_manager
    worker.ui_out_dispatcher = SimpleNamespace(
        dispatch=MagicMock(side_effect=RuntimeError("ui failed"))
    )

    worker.run()

    ui_manager.post_notification.assert_called_once()
    assert fake_event.wait_calls == [1.0]
    assert audio_path_queue.task_done_calls == 2
    assert audio_path_queue.unfinished_tasks == 0
