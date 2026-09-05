from __future__ import annotations

import threading
import time
from queue import Queue
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


from application.runtime.context import AppRuntime, get_app_runtime, set_app_runtime
from application.runtime.workers import (
    LLMWorker,
    PresentationWorker,
    DialogMediaWorker,
)
from core.messaging.stream_events import STREAM_DIALOG_REPAIR_KEY
from ai.llm.llm_manager import LLMManager
from sdk.messages import LLMDialogMessage, PresentationMessage, UserInputMessage
from test.mocks import MockLLMAdapter


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
    from application.runtime import context as _mod

    saved = getattr(_mod, "_runtime", None)
    _mod._runtime = None
    yield
    _mod._runtime = saved


def _make_app_runtime(
    dialog_queue: Queue | None = None,
    presentation_queue: Queue | None = None,
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
        dialog_queue=dialog_queue or CountingQueue(),
        presentation_queue=presentation_queue or CountingQueue(),
        text_processor=MagicMock(),
        opencc=SimpleNamespace(convert=lambda value: f"converted:{value}"),
    )
    set_app_runtime(runtime)
    return runtime


def _run_streaming_llm_worker(llm_manager) -> tuple[AppRuntime, list[LLMDialogMessage]]:
    user_input_queue = CountingQueue()
    dialog_queue = CountingQueue()
    user_input_queue.put(UserInputMessage(text="hello"))
    user_input_queue.put(None)
    runtime = _make_app_runtime(dialog_queue=dialog_queue)
    runtime.config.config.api_config.is_streaming = True
    runtime.llm_manager = llm_manager

    LLMWorker(user_input_queue, dialog_queue).run()

    output = []
    while not dialog_queue.empty():
        output.append(dialog_queue.get_nowait())
    return runtime, output


def test_workers_keep_original_queue_attributes_and_bind_ports() -> None:
    _make_app_runtime()
    user_input_queue = Queue()
    dialog_queue = Queue()
    presentation_queue = Queue()

    llm_worker = LLMWorker(user_input_queue, dialog_queue)
    dialog_media_worker = DialogMediaWorker(dialog_queue, presentation_queue)
    ui_worker = PresentationWorker(presentation_queue)

    assert llm_worker.user_input_queue is user_input_queue
    assert llm_worker.dialog_queue is dialog_queue
    assert llm_worker.inq(LLMWorker.PORT_USER_INPUT) is user_input_queue
    assert llm_worker.outq(LLMWorker.PORT_DIALOG) is dialog_queue

    assert dialog_media_worker.dialog_queue is dialog_queue
    assert dialog_media_worker.presentation_queue is presentation_queue
    assert dialog_media_worker.inq(DialogMediaWorker.PORT_DIALOG) is dialog_queue
    assert dialog_media_worker.outq(DialogMediaWorker.PORT_PRESENTATION) is presentation_queue

    assert ui_worker.presentation_queue is presentation_queue
    assert ui_worker.inq(PresentationWorker.PORT_PRESENTATION) is presentation_queue


def test_llm_worker_run_uses_original_queues_and_marks_input_done(
    monkeypatch,
) -> None:
    user_input_queue = CountingQueue()
    dialog_queue = CountingQueue()
    user_input_queue.put(UserInputMessage(text="hello"))
    user_input_queue.put(None)

    runtime = _make_app_runtime()
    runtime.config.config.api_config.is_streaming = False
    runtime.llm_manager.chat.return_value = (
        '{"character_name":"Alice","speech":"Hi","sprite":"0"}'
    )

    worker = LLMWorker(user_input_queue, dialog_queue)
    monkeypatch.setattr(worker, "_init_app", lambda: None)
    worker.ui_update_manager = runtime.ui_update_manager
    worker.llm_manager = runtime.llm_manager

    worker.run()

    output = dialog_queue.get_nowait()
    assert isinstance(output, LLMDialogMessage)
    assert output.name == "Alice"
    assert output.text == "Hi"
    assert output.turn_id == runtime.chat_turn_service.current_turn().id
    assert output._dialog_index == 0
    assert output._history_binding is not None
    assert "dialog_index" not in output.model_dump(by_alias=True)
    assert "history_binding" not in output.model_dump(by_alias=True)
    assert user_input_queue.task_done_calls == 2
    assert user_input_queue.unfinished_tasks == 0
    runtime.llm_manager.chat.assert_called_once_with(
        "hello",
        stream=False,
        dialog_output_required=True,
        user_attachments=[],
        user_input_text="hello",
    )


def test_llm_worker_does_not_requeue_dialogue_after_stream_repair() -> None:
    valid = (
        '{"dialog":['
        '{"character_name":"Alice","speech":"First","sprite":"0"},'
        '{"character_name":"Bob","speech":"Second","sprite":"1"}'
        "]}"
    )
    adapter = MockLLMAdapter(responses=[f"```json\n{valid}\n```", valid])
    manager = LLMManager(adapter=adapter, user_template="S")

    _, output = _run_streaming_llm_worker(manager)

    assert [(message.name, message.text) for message in output] == [
        ("Alice", "First"),
        ("Bob", "Second"),
    ]
    assert [call["stream"] for call in adapter.call_history] == [True, False]
    assert manager.messages[-1]["content"] == valid


def test_llm_worker_appends_repaired_suffix_with_turn_identity() -> None:
    alice = '{"character_name":"Alice","speech":"First","sprite":"0"}'
    bob = '{"character_name":"Bob","speech":"Second","sprite":"1"}'
    repaired = f'{{"dialog":[{alice},{bob}]}}'
    llm_manager = MagicMock()
    llm_manager.chat.return_value = iter(
        [f'{{"dialog":[{alice},', {STREAM_DIALOG_REPAIR_KEY: repaired}]
    )

    runtime, output = _run_streaming_llm_worker(llm_manager)

    assert [(message.name, message.text) for message in output] == [
        ("Alice", "First"),
        ("Bob", "Second"),
    ]
    assert {message.turn_id for message in output} == {
        runtime.chat_turn_service.current_turn().id
    }
    assert [message._dialog_index for message in output] == [0, 1]


def test_llm_worker_passes_locally_read_attachments_without_file_tool_group(tmp_path) -> None:
    image = tmp_path / "scene.png"
    image.write_bytes(b"image")
    document = tmp_path / "notes.txt"
    document.write_text("notes", encoding="utf-8")
    user_input_queue = CountingQueue()
    dialog_queue = CountingQueue()
    user_input_queue.put(
        UserInputMessage(
            text="Inspect these",
            attachments=[
                {"kind": "image", "path": str(image)},
                {"kind": "file", "path": str(document)},
            ],
        )
    )
    user_input_queue.put(None)

    runtime = _make_app_runtime()
    runtime.config.config.api_config.is_streaming = False
    runtime.llm_manager.llm_adapter.supports_native_vision = True
    runtime.llm_manager.chat.return_value = '{"character_name":"Alice","speech":"Done","sprite":"0"}'
    worker = LLMWorker(user_input_queue, dialog_queue)
    worker.run()

    content = runtime.llm_manager.chat.call_args.args[0]
    assert content[0]["type"] == "text"
    assert "notes" in content[0]["text"]
    assert "BEGIN ATTACHED FILE: notes.txt" in content[0]["text"]
    assert content[1]["type"] == "local_image"
    assert runtime.llm_manager.chat.call_args.kwargs["user_display_text"] == (
        "Inspect these\n[image: scene.png] [file: notes.txt]"
    )
    assert runtime.llm_manager.chat.call_args.kwargs["user_input_text"] == "Inspect these"
    assert runtime.llm_manager.chat.call_args.kwargs["dialog_output_required"] is True
    assert [item["kind"] for item in runtime.llm_manager.chat.call_args.kwargs["user_attachments"]] == [
        "image",
        "file",
    ]
    assert "tool_groups" not in runtime.llm_manager.chat.call_args.kwargs
    runtime.ui_update_manager.record_user_message.assert_called_once_with(
        "Inspect these\n[image: scene.png] [file: notes.txt]"
    )


def test_dialog_media_worker_exception_path_emits_fallback(
    monkeypatch,
) -> None:
    dialog_queue = CountingQueue()
    presentation_queue = CountingQueue()
    dialog_queue.put(LLMDialogMessage(name="Alice", text="broken", asset_id="2", effect="shake"))
    dialog_queue.put(None)
    _make_app_runtime(dialog_queue=dialog_queue, presentation_queue=presentation_queue)

    worker = DialogMediaWorker(dialog_queue, presentation_queue)
    monkeypatch.setattr(worker, "_init_app", lambda: None)
    worker.dialog_media_dispatcher = SimpleNamespace(
        dispatch=MagicMock(side_effect=RuntimeError("tts failed"))
    )

    worker.run()

    output = presentation_queue.get_nowait()
    assert isinstance(output, PresentationMessage)
    assert output.name == "converted:Alice"
    assert output.text == "broken"
    assert output.asset_id == "2"
    assert output.effect == "shake"
    assert dialog_queue.task_done_calls == 2
    assert dialog_queue.unfinished_tasks == 0


def test_dialog_media_worker_start_clears_previous_cancel_state(monkeypatch) -> None:
    worker = DialogMediaWorker(Queue(), Queue())
    worker._cancel_event.set()
    starts = []

    monkeypatch.setattr(
        "application.runtime.workers.ThreadDagNode.start",
        lambda self: starts.append(self),
    )

    worker.start()

    assert not worker._cancel_event.is_set()
    assert starts == [worker]


def test_dialog_media_worker_drops_message_scoped_to_interrupted_turn(monkeypatch) -> None:
    dialog_queue = CountingQueue()
    presentation_queue = CountingQueue()
    runtime = _make_app_runtime(dialog_queue=dialog_queue, presentation_queue=presentation_queue)
    interrupted_turn = runtime.chat_turn_service.begin_turn()
    runtime.chat_turn_service.interrupt()
    current_turn = runtime.chat_turn_service.begin_turn()
    dialog_queue.put(
        LLMDialogMessage(
            name="Alice",
            text="stale reply",
            asset_id="-1",
            turn_id=interrupted_turn.id,
        )
    )
    dialog_queue.put(None)
    worker = DialogMediaWorker(dialog_queue, presentation_queue)
    monkeypatch.setattr(worker, "_init_app", lambda: None)
    worker.dialog_media_dispatcher = SimpleNamespace(dispatch=MagicMock())

    worker.run()

    assert current_turn.id != interrupted_turn.id
    worker.dialog_media_dispatcher.dispatch.assert_not_called()
    assert presentation_queue.empty()
    assert dialog_queue.task_done_calls == 2


def test_dialog_media_worker_drops_dispatch_output_after_cancel() -> None:
    presentation_queue = CountingQueue()
    _make_app_runtime(presentation_queue=presentation_queue)
    worker = DialogMediaWorker(CountingQueue(), presentation_queue)
    started = threading.Event()
    release = threading.Event()
    attempted_emit = threading.Event()

    def dispatch(_item):
        started.set()
        assert release.wait(timeout=1)
        get_app_runtime().presentation_queue.put(
            PresentationMessage(
                audio_path="late.wav",
                name="Alice",
                text="late",
                asset_id="-1",
            )
        )
        attempted_emit.set()

    worker.dialog_media_dispatcher = SimpleNamespace(dispatch=dispatch)
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
    assert presentation_queue.empty()
    for _ in range(20):
        if get_app_runtime().presentation_queue is presentation_queue:
            break
        time.sleep(0.01)
    assert get_app_runtime().presentation_queue is presentation_queue


def test_dialog_media_worker_drops_dispatch_output_after_runtime_cancel() -> None:
    presentation_queue = CountingQueue()
    runtime = _make_app_runtime(presentation_queue=presentation_queue)
    turn = runtime.chat_turn_service.begin_turn()
    worker = DialogMediaWorker(CountingQueue(), presentation_queue)
    started = threading.Event()
    release = threading.Event()
    attempted_emit = threading.Event()

    def dispatch(_item):
        started.set()
        assert release.wait(timeout=1)
        get_app_runtime().presentation_queue.put(
            PresentationMessage(
                audio_path="late.wav",
                name="Alice",
                text="late",
                asset_id="-1",
            )
        )
        attempted_emit.set()

    worker.dialog_media_dispatcher = SimpleNamespace(dispatch=dispatch)
    runner = threading.Thread(
        target=worker._dispatch_with_cancel,
        args=(LLMDialogMessage(name="Alice", text="hello", asset_id="-1"),),
    )

    runner.start()
    assert started.wait(timeout=1)
    turn.cancelled.set()
    release.set()
    assert attempted_emit.wait(timeout=1)
    runner.join(timeout=1)

    assert not runner.is_alive()
    assert presentation_queue.empty()
    for _ in range(20):
        if get_app_runtime().presentation_queue is presentation_queue:
            break
        time.sleep(0.01)
    assert get_app_runtime().presentation_queue is presentation_queue


def test_ui_worker_skip_speech_is_noop_when_no_dialog_or_audio_is_active() -> None:
    presentation_queue = Queue()
    runtime = _make_app_runtime(presentation_queue=presentation_queue)
    worker = PresentationWorker(presentation_queue)
    worker.task_done_requested = FakeEvent()
    worker.current_audio_path = None
    runtime.ui_playback.current_audio_path = None
    worker.dialog_channel = MagicMock()
    worker.dialog_channel.get_busy.return_value = False
    worker._dialog_active = False

    worker.skip_speech()

    worker.dialog_channel.stop.assert_not_called()
    runtime.ui_update_manager.post_tts_skip.assert_not_called()
    assert worker.task_done_requested.set_calls == 0


def test_ui_worker_finishes_turn_after_all_system_output_is_drained() -> None:
    ui_manager = MagicMock()
    runtime = _make_app_runtime(ui_manager=ui_manager)
    turn = runtime.chat_turn_service.begin_turn()
    runtime.chat_turn_service.mark_generation_complete(turn)
    worker = PresentationWorker(runtime.presentation_queue)
    worker.ui_update_manager = ui_manager
    worker.dialog_channel = MagicMock()
    worker.dialog_channel.get_busy.return_value = False

    assert worker._finish_turn_if_drained(turn) is True
    assert runtime.chat_turn_service.is_active() is False
    ui_manager.post_llm_reply_finished.assert_called_once_with()


def test_ui_worker_does_not_finish_while_tts_work_is_still_inflight() -> None:
    ui_manager = MagicMock()
    runtime = _make_app_runtime(ui_manager=ui_manager)
    turn = runtime.chat_turn_service.begin_turn()
    runtime.chat_turn_service.mark_generation_complete(turn)
    runtime.dialog_queue.put(LLMDialogMessage(name="NARR", text="pending", asset_id="-1"))
    worker = PresentationWorker(runtime.presentation_queue)
    worker.ui_update_manager = ui_manager
    worker.dialog_channel = MagicMock()
    worker.dialog_channel.get_busy.return_value = False

    assert worker._finish_turn_if_drained(turn) is False
    assert runtime.chat_turn_service.is_active() is True
    ui_manager.post_llm_reply_finished.assert_not_called()


def test_ui_worker_does_not_finish_while_shared_playback_is_active() -> None:
    ui_manager = MagicMock()
    runtime = _make_app_runtime(ui_manager=ui_manager)
    turn = runtime.chat_turn_service.begin_turn()
    runtime.chat_turn_service.mark_generation_complete(turn)
    controller = MagicMock()
    controller.is_active.return_value = True
    runtime.ui_playback.playback_controller = controller
    worker = PresentationWorker(runtime.presentation_queue)
    worker.ui_update_manager = ui_manager
    worker.dialog_channel = None

    assert worker._finish_turn_if_drained(turn) is False
    assert runtime.chat_turn_service.is_active() is True
    ui_manager.post_llm_reply_finished.assert_not_called()


def test_ui_worker_skip_speech_interrupts_shared_playback_controller() -> None:
    runtime = _make_app_runtime()
    controller = MagicMock()
    controller.is_active.return_value = True
    runtime.ui_playback.playback_controller = controller
    worker = PresentationWorker(runtime.presentation_queue)
    worker._dialog_active = False

    worker.skip_speech()

    controller.interrupt.assert_called_once_with()
    runtime.ui_update_manager.post_tts_skip.assert_not_called()


def test_ui_worker_skip_speech_stops_busy_channel_without_queued_audio() -> None:
    presentation_queue = Queue()
    runtime = _make_app_runtime(presentation_queue=presentation_queue)
    worker = PresentationWorker(presentation_queue)
    worker.task_done_requested = FakeEvent()
    worker.current_audio_path = None
    runtime.ui_playback.current_audio_path = None
    worker.dialog_channel = MagicMock()
    worker.dialog_channel.get_busy.return_value = True

    worker.skip_speech()

    worker.dialog_channel.stop.assert_called_once_with()
    assert worker.current_audio_path is None
    assert runtime.ui_playback.current_audio_path is None
    runtime.ui_update_manager.post_tts_skip.assert_called_once_with()
    assert worker.task_done_requested.set_calls == 1


def test_ui_worker_skip_speech_stops_active_audio_and_emits_tts_skip() -> None:
    presentation_queue = Queue()
    runtime = _make_app_runtime(presentation_queue=presentation_queue)
    worker = PresentationWorker(presentation_queue)
    worker.task_done_requested = FakeEvent()
    worker.current_audio_path = "current.wav"
    runtime.ui_playback.current_audio_path = "current.wav"
    worker.dialog_channel = MagicMock()
    worker.dialog_channel.get_busy.return_value = True

    worker.skip_speech()

    worker.dialog_channel.stop.assert_called_once_with()
    assert worker.current_audio_path is None
    assert runtime.ui_playback.current_audio_path is None
    runtime.ui_update_manager.post_tts_skip.assert_called_once_with()
    assert worker.task_done_requested.set_calls == 1


def test_ui_worker_skip_speech_advances_waiting_dialog_without_emitting_tts_skip() -> None:
    presentation_queue = Queue()
    runtime = _make_app_runtime(presentation_queue=presentation_queue)
    worker = PresentationWorker(presentation_queue)
    worker.task_done_requested = FakeEvent()
    worker.current_audio_path = None
    runtime.ui_playback.current_audio_path = None
    worker.dialog_channel = MagicMock()
    worker.dialog_channel.get_busy.return_value = False
    worker._dialog_active = True

    worker.skip_speech()

    worker.dialog_channel.stop.assert_not_called()
    runtime.ui_update_manager.post_tts_skip.assert_not_called()
    assert worker.task_done_requested.set_calls == 1


def test_ui_worker_exception_branch_keeps_original_wait_and_task_done(
    monkeypatch,
) -> None:
    presentation_queue = CountingQueue()
    presentation_queue.put(
        PresentationMessage(
            audio_path="",
            name="Alice",
            text="1234567890",
            asset_id="-1",
            effect="",
        )
    )
    presentation_queue.put(None)
    ui_manager = MagicMock()
    _make_app_runtime(presentation_queue=presentation_queue, ui_manager=ui_manager)

    worker = PresentationWorker(presentation_queue)
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
    assert presentation_queue.task_done_calls == 2
    assert presentation_queue.unfinished_tasks == 0
