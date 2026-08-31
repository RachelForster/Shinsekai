from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from application.chat import wire_streaming_session as wiring


def _create_wiring(**overrides):
    values = {
        "args": SimpleNamespace(history="history.json"),
        "config": SimpleNamespace(),
        "startup": SimpleNamespace(llm_manager=SimpleNamespace(), tts_manager=None),
        "transport": SimpleNamespace(emit=Mock(), bind_command_dispatcher=Mock()),
        "runtime": SimpleNamespace(
            input_queue=object(), audio_queue=object(), ui_worker=None
        ),
        "ui_updates": SimpleNamespace(
            post_notification=Mock(),
            post_llm_reply_finished=Mock(),
        ),
        "chat_turn_service": SimpleNamespace(submit=Mock()),
        "shutdown_session": Mock(),
        "translate": lambda key, **_kwargs: key,
        "create_asr_adapter": Mock(),
        "save_history": Mock(return_value=True),
    }
    values.update(overrides)
    return wiring._StreamingSessionWiring(**values)


def test_wiring_composes_plugins_branches_asr_and_command_dispatcher(
    monkeypatch,
) -> None:
    emit_user_text = Mock(return_value=True)
    branch_manager = SimpleNamespace()
    runtime_asr = SimpleNamespace()
    dispatcher = SimpleNamespace()
    instance = _create_wiring()
    bind_asr = Mock()
    monkeypatch.setattr(
        "plugin_system.host.wire_user_input_plugins",
        lambda queue, *, sink: (
            emit_user_text
            if queue is instance.runtime.input_queue
            and sink is instance.chat_turn_service.submit
            else None
        ),
    )
    monkeypatch.setattr(
        instance,
        "_create_branch_manager",
        lambda: branch_manager,
    )
    monkeypatch.setattr(
        instance,
        "_create_streaming_asr",
        lambda: runtime_asr,
    )
    monkeypatch.setattr(instance, "_bind_asr_presentation_hooks", bind_asr)
    monkeypatch.setattr(
        instance,
        "_create_command_dispatcher",
        lambda: dispatcher,
    )

    bindings = instance.wire()

    assert bindings.branch_manager is branch_manager
    assert bindings.runtime_asr is runtime_asr
    assert bindings.last_user_message == {"attachments": [], "text": ""}
    assert instance.emit_user_text is emit_user_text
    bind_asr.assert_called_once_with()
    instance.transport.bind_command_dispatcher.assert_called_once_with(dispatcher)


def test_submit_runtime_text_resolves_attachments_and_tracks_last_message(
    monkeypatch,
) -> None:
    attachment = SimpleNamespace(to_payload=lambda: {"path": "image.png"})
    emit_user_text = Mock(return_value=True)
    ui_updates = SimpleNamespace(post_notification=Mock())
    instance = _create_wiring(ui_updates=ui_updates)
    instance.emit_user_text = emit_user_text
    monkeypatch.setattr(
        wiring,
        "resolve_chat_attachments",
        lambda raw: [attachment] if raw else [],
    )

    accepted = instance.submit_runtime_text(
        " hello ",
        attachments=[{"path": "image.png"}],
    )

    assert accepted is True
    assert instance.last_user_message == {
        "attachments": [{"path": "image.png"}],
        "text": "hello",
    }
    emit_user_text.assert_called_once_with(
        "hello",
        attachments=[{"path": "image.png"}],
    )
    ui_updates.post_notification.assert_called_once_with("main.notify_submitted")


def test_submit_runtime_text_reports_unavailable_input_sink() -> None:
    ui_updates = SimpleNamespace(post_notification=Mock())
    instance = _create_wiring(ui_updates=ui_updates)
    instance.emit_user_text = None

    accepted = instance.submit_runtime_text("hello")

    assert accepted is False
    ui_updates.post_notification.assert_called_once_with("main.notify_chat")
