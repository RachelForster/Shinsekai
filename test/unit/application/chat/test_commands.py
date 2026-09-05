from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from application.chat.commands import (
    ChatCommandBindings,
    ChatCommandDispatcher,
    ChatCommandRequest,
    ChatCommandUiBindings,
)
from core.messaging.chat_turn_service import ChatTurnOptions


@dataclass
class _ApiConfig:
    interrupt_enabled: bool = False
    is_batch_input_enabled: bool = False
    batch_input_timeout: float = 5.0

    def model_copy(self, *, deep: bool = False) -> _ApiConfig:
        return copy(self)


@dataclass
class _SystemConfig:
    voice_language: str = "en"

    def model_copy(self, *, deep: bool = False) -> _SystemConfig:
        return copy(self)


class _TurnService:
    def __init__(self) -> None:
        self.options = ChatTurnOptions()
        self.calls: list[tuple[str, object]] = []

    def update_options(self, options: ChatTurnOptions) -> None:
        self.options = options
        self.calls.append(("update", options))

    def input_changed(self, **state: object) -> None:
        self.calls.append(("input", state))

    def flush(self) -> None:
        self.calls.append(("flush", None))

    def cancel_pending_batch(self) -> None:
        self.calls.append(("cancel", None))


class _LlmManager:
    def __init__(self, messages: list[dict[str, Any]] | None = None) -> None:
        self.messages = list(messages or [])
        self.stripped = False

    def get_messages(self) -> list[dict[str, Any]]:
        return self.messages

    def set_messages(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages

    def clear_messages(self) -> None:
        self.messages.clear()

    def _strip_orphaned_tool_calls(self) -> None:
        self.stripped = True


@pytest.fixture
def command_runtime() -> SimpleNamespace:
    submitted: list[tuple[str, dict[str, object]]] = []
    notifications: list[str] = []
    ui_calls: list[tuple[str, object]] = []
    confirmations: list[tuple[str, str]] = []

    def submit_text(text: str, **kwargs: object) -> bool:
        submitted.append((text, kwargs))
        return True

    def resolve_confirmation(confirmation_id: str, action: str) -> bool:
        confirmations.append((confirmation_id, action))
        return True

    def translate(key: str, **kwargs: object) -> str:
        return f"{key}:{kwargs.get('lang', '')}"

    config = SimpleNamespace(
        config=SimpleNamespace(
            api_config=_ApiConfig(),
            system_config=_SystemConfig(),
        ),
        save_system_config=Mock(),
    )
    llm_manager = _LlmManager()
    runtime_asr = SimpleNamespace(
        pause_for_turn=Mock(),
        user_pause=Mock(),
        user_resume=Mock(),
    )
    turn_service = _TurnService()
    branch_manager = SimpleNamespace(
        reset=Mock(),
        persist=Mock(),
        publish_tree=Mock(),
        fork=Mock(),
        switch=Mock(),
        rename=Mock(),
    )
    tts_manager = SimpleNamespace(set_language=Mock())
    shutdown = Mock()
    dispatcher = ChatCommandDispatcher(
        bindings=ChatCommandBindings(
            submit_text=submit_text,
            can_submit_text=lambda: True,
            shutdown_session=shutdown,
            resolve_tool_confirmation=resolve_confirmation,
            ui=ChatCommandUiBindings(
                clear_options=lambda: ui_calls.append(("clear-options", None)),
                sync_history=lambda: ui_calls.append(("sync-history", None)),
                notify=notifications.append,
                clear_tool_confirmation=lambda value: ui_calls.append(
                    ("clear-confirmation", value)
                ),
                handle_playback_signal=lambda *values: ui_calls.append(
                    ("playback", values)
                ),
                skip_speech=lambda: ui_calls.append(("skip", None)),
            ),
            translate=translate,
        ),
        config=config,
        llm_manager=llm_manager,
        runtime_asr=runtime_asr,
        chat_turn_service=turn_service,
        branch_manager=branch_manager,
        chat_history=[],
        last_user_message={},
        audio_path_queue=SimpleNamespace(put=Mock()),
        history_presenter=object(),
        tts_manager=tts_manager,
    )
    return SimpleNamespace(
        dispatcher=dispatcher,
        submitted=submitted,
        notifications=notifications,
        ui_calls=ui_calls,
        confirmations=confirmations,
        config=config,
        llm_manager=llm_manager,
        runtime_asr=runtime_asr,
        turn_service=turn_service,
        branch_manager=branch_manager,
        tts_manager=tts_manager,
        shutdown=shutdown,
    )


def _execute(runtime: SimpleNamespace, command_type: str, payload: object = None):
    return runtime.dispatcher.execute(ChatCommandRequest(command_type, payload))


@pytest.mark.parametrize("command", ["clear-history", "revert-history", "fork-history", "switch-branch"])
def test_history_invalidated_before_handler_even_without_asr_boundary(command_runtime, command):
    from core.messaging.chat_turn_service import ChatTurnService

    events = []
    service = ChatTurnService()
    turn = service.begin_turn()
    command_runtime.dispatcher.chat_turn_service = service
    command_runtime.llm_manager.invalidate_history = lambda: events.append("invalidated")

    def mutate(payload):
        assert turn.is_cancelled()
        events.append("mutated")

    command_runtime.dispatcher._handlers[command] = mutate
    assert _execute(command_runtime, command, 0).ok
    assert events == ["invalidated", "mutated"]


@pytest.mark.parametrize("command", ["clear-history", "revert-history", "fork-history", "switch-branch"])
def test_history_commands_quiesce_asr_before_mutation(command_runtime, command):
    from contextlib import contextmanager
    events = []

    @contextmanager
    def boundary():
        events.append("quiesced")
        try:
            yield
        finally:
            events.append("resumed")

    command_runtime.runtime_asr.input_boundary = boundary
    command_runtime.turn_service.cancel_pending_batch = lambda: events.append("cancelled")
    command_runtime.dispatcher._handlers[command] = lambda payload: events.append("mutated")
    assert _execute(command_runtime, command, 0).ok
    assert events == ["quiesced", "cancelled", "mutated", "resumed"]


@pytest.mark.parametrize("command", ["clear-history", "revert-history", "fork-history", "switch-branch"])
def test_history_commands_discard_live_transcript_and_deferred_admission(command_runtime, command):
    from ai.asr.streaming_controller import ASRSubmissionResult, StreamingASRController
    from core.messaging.chat_turn_service import ChatTurnService
    from test.unit.adapters.test_streaming_asr_controller import _FakeASRAdapter, _wait_until

    delivered = []
    service = ChatTurnService(sink=delivered.append)
    turn = service.begin_turn()

    def submit(text):
        service.submit(text, defer_until_idle=True)
        return ASRSubmissionResult(True, False)

    controller = StreamingASRController(
        adapter_factory=_FakeASRAdapter,
        emit_event=lambda event: None,
        submit_final=submit,
        continuous_listening=True,
        silence_submit_seconds=300,
    )
    command_runtime.dispatcher.runtime_asr = controller
    command_runtime.dispatcher.chat_turn_service = service
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        old_adapter = controller._adapter
        old_adapter.callback("old completed speech", False)
        old_adapter.callback("old unfinished speech", True)
        old_timer = controller._silence_timer

        def mutate(_payload):
            old_adapter.callback("late old final during mutation", False)
            assert delivered == []

        command_runtime.dispatcher._handlers[command] = mutate
        assert _execute(command_runtime, command, 0).ok
        _wait_until(lambda: controller._active)
        old_timer.function(*old_timer.args, **old_timer.kwargs)
        old_adapter.callback("late old final after mutation", False)
        service.mark_generation_complete(turn)
        service.finish_turn(turn)
        assert delivered == []
        controller._adapter.callback("new history speech", True)
        controller._adapter.callback("new history speech", False)
        assert delivered == ["new history speech"]
    finally:
        service.close()
        controller.close()


def test_dispatches_close_send_message_and_option_commands(command_runtime) -> None:
    runtime = command_runtime

    assert _execute(runtime, "close-session").ok
    assert _execute(
        runtime,
        "send-message",
        {"text": "hello", "attachments": [{"path": "a.png"}]},
    ).ok
    assert _execute(runtime, "submit-option", "choice A").ok
    assert _execute(
        runtime,
        "submit-option",
        {
            "kind": "tool-confirmation",
            "confirmationId": "confirmation-1",
            "action": "CONFIRM",
        },
    ).ok

    runtime.shutdown.assert_called_once_with()
    assert runtime.runtime_asr.pause_for_turn.call_count == 2
    assert runtime.submitted == [
        (
            "hello",
            {"attachments": [{"path": "a.png"}], "notify_key": None},
        ),
        ("choice A", {}),
    ]
    assert runtime.confirmations == [("confirmation-1", "confirm")]
    assert ("clear-confirmation", "confirmation-1") in runtime.ui_calls


def test_dispatches_turn_input_asr_and_speech_commands(command_runtime) -> None:
    runtime = command_runtime

    assert _execute(
        runtime,
        "update-turn-options",
        {
            "interruptEnabled": True,
            "batchEnabled": True,
            "batchIdleSeconds": 1.5,
        },
    ).ok
    assert _execute(
        runtime,
        "chat-input-state",
        {"hasText": True, "composing": False},
    ).ok
    for command_type in (
        "flush-input-batch",
        "cancel-input-batch",
        "pause-asr",
        "resume-asr",
        "skip-speech",
        "dialog-advance",
    ):
        assert _execute(runtime, command_type).ok

    assert runtime.turn_service.options == ChatTurnOptions(
        interrupt_enabled=True,
        batch_enabled=True,
        batch_idle_seconds=1.5,
    )
    assert runtime.config.config.api_config.interrupt_enabled is True
    assert runtime.config.config.api_config.is_batch_input_enabled is True
    assert runtime.config.config.api_config.batch_input_timeout == 1.5
    assert (
        "input",
        {"has_text": True, "composing": False},
    ) in runtime.turn_service.calls
    assert ("flush", None) in runtime.turn_service.calls
    assert ("cancel", None) in runtime.turn_service.calls
    runtime.runtime_asr.user_pause.assert_called_once_with()
    runtime.runtime_asr.user_resume.assert_called_once_with()
    assert runtime.ui_calls.count(("skip", None)) == 2


def test_validates_and_dispatches_audio_playback_signal(command_runtime) -> None:
    runtime = command_runtime

    result = _execute(
        runtime,
        "audio-playback-signal",
        {
            "playbackId": "playback-1",
            "rendererId": "renderer-1",
            "state": "finished",
            "error": "",
        },
    )

    assert result.ok
    assert runtime.ui_calls[-1] == (
        "playback",
        ("playback-1", "finished", "", "renderer-1"),
    )


def test_reroll_removes_last_turn_and_resubmits_canonical_payload(
    command_runtime,
) -> None:
    runtime = command_runtime
    runtime.dispatcher.chat_history.extend(
        [
            "<p><b>你</b>：hello [image: old.png]</p>",
            "<p><b style='color:#fff'>Alice</b>：reply</p>",
        ]
    )
    runtime.llm_manager.messages.extend(
        [
            {
                "role": "user",
                "content": "rendered",
                "input_text": "hello",
                "attachments": [{"path": "old.png"}],
            },
            {"role": "assistant", "content": "reply"},
        ]
    )

    result = _execute(runtime, "reroll")

    assert result.ok
    assert runtime.dispatcher.chat_history == []
    assert runtime.llm_manager.messages == []
    assert runtime.llm_manager.stripped is True
    assert runtime.submitted == [
        (
            "hello",
            {
                "attachments": [{"path": "old.png"}],
                "ignore_unavailable_attachments": True,
                "notify_key": None,
            },
        )
    ]
    assert runtime.ui_calls[:2] == [
        ("clear-options", None),
        ("sync-history", None),
    ]
    assert runtime.notifications == ["main.notify_reroll:"]


def test_clear_history_owns_storage_and_branch_reset(
    monkeypatch, command_runtime
) -> None:
    runtime = command_runtime
    calls: list[tuple[str, object]] = []
    runtime.dispatcher.history_argument = "session.json"
    monkeypatch.setattr(
        "application.chat.commands.chat_history_active_path",
        lambda value: Path("resolved") / value,
    )
    monkeypatch.setattr(
        "application.chat.commands.remove_chat_history_storage",
        lambda value: calls.append(("remove", value)),
    )
    monkeypatch.setattr(
        "application.chat.commands.clear_chat_history",
        lambda path, queue, manager: calls.append(("clear", path)),
    )

    result = _execute(runtime, "clear-history")

    assert result.ok
    assert ("cancel", None) in runtime.turn_service.calls
    assert calls == [
        ("remove", "session.json"),
        ("clear", str(Path("resolved") / "session.json")),
    ]
    runtime.branch_manager.reset.assert_called_once_with()
    runtime.branch_manager.persist.assert_called_once_with()
    runtime.branch_manager.publish_tree.assert_called_once_with()
    assert runtime.ui_calls[-2:] == [
        ("clear-options", None),
        ("sync-history", None),
    ]


def test_changes_voice_language_and_persists_config(command_runtime) -> None:
    runtime = command_runtime

    result = _execute(runtime, "change-voice-language", " JA ")

    assert result.ok
    runtime.tts_manager.set_language.assert_called_once_with("ja")
    assert runtime.config.config.system_config.voice_language == "ja"
    runtime.config.save_system_config.assert_called_once_with()
    assert runtime.notifications == [
        "desktop.menu.notify_voice_language:template.voice_lang_ja:"
    ]


def test_reverts_history_inside_application(monkeypatch, command_runtime) -> None:
    runtime = command_runtime
    revert = Mock()
    monkeypatch.setattr("application.chat.commands.revert_chat_history", revert)

    result = _execute(runtime, "revert-history", "2")

    assert result.ok
    revert.assert_called_once_with(
        2,
        llm_manager=runtime.llm_manager,
        hist=runtime.dispatcher.chat_history,
        window=runtime.dispatcher.history_presenter,
    )
    assert runtime.turn_service.calls[-1] == ("cancel", None)
    assert runtime.ui_calls[-2:] == [
        ("clear-options", None),
        ("sync-history", None),
    ]


def test_dispatches_branch_commands(command_runtime) -> None:
    runtime = command_runtime

    assert _execute(
        runtime,
        "fork-history",
        {"userIndex": 3, "branchId": " branch-3 "},
    ).ok
    assert _execute(runtime, "switch-branch", "branch-2").ok
    assert _execute(
        runtime,
        "rename-branch",
        {"branchId": "branch-2", "label": "Alternate"},
    ).ok

    runtime.branch_manager.fork.assert_called_once_with(3, branch_id="branch-3")
    runtime.branch_manager.switch.assert_called_once_with("branch-2")
    runtime.branch_manager.rename.assert_called_once_with("branch-2", "Alternate")
    assert runtime.notifications == ["已切换对话分支。", "已重命名对话分支。"]


@pytest.mark.parametrize(
    ("command_type", "payload", "error"),
    [
        ("unknown", None, "未知实时聊天命令"),
        ("submit-option", {"unexpected": True}, "must be a string"),
        (
            "update-turn-options",
            {"interruptEnabled": True, "batchEnabled": True, "batchIdleSeconds": 0.1},
            "between 0.3 and 120",
        ),
        ("audio-playback-signal", {}, "signal is invalid"),
        ("change-voice-language", "", "语音语言不能为空"),
    ],
)
def test_returns_failed_result_and_notifies_for_invalid_commands(
    command_runtime,
    command_type: str,
    payload: object,
    error: str,
) -> None:
    result = _execute(command_runtime, command_type, payload)

    assert result.ok is False
    assert error in result.error
    assert command_runtime.notifications == [result.error]
