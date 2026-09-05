from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock
from queue import Queue

from core.messaging.chat_turn_service import ChatTurnService, ChatTurnOptions
from plugin_system.host.service import wire_user_input_plugins
from test.unit.adapters.test_streaming_asr_controller import _FakeASRAdapter, _wait_until

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
    emit_user_text.side_effect = lambda text, **kwargs: (
        kwargs["on_admit"](text, kwargs["attachments"]) or True
    )
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
        interrupt_current=None,
        defer_until_idle=False,
        on_admit=emit_user_text.call_args.kwargs["on_admit"],
    )
    ui_updates.post_notification.assert_called_once_with("main.notify_submitted")


def test_submit_runtime_text_reports_unavailable_input_sink() -> None:
    ui_updates = SimpleNamespace(post_notification=Mock())
    instance = _create_wiring(ui_updates=ui_updates)
    instance.emit_user_text = None

    accepted = instance.submit_runtime_text("hello")

    assert accepted is False
    ui_updates.post_notification.assert_called_once_with("main.notify_chat")


def _live_wiring(*, continuous: bool):
    queue = Queue()
    service = ChatTurnService(sink=queue.put, options=ChatTurnOptions(interrupt_enabled=True))
    instance = _create_wiring(
        config=SimpleNamespace(config=SimpleNamespace(system_config=SimpleNamespace(
            asr_continuous_during_reply_experimental_enabled=continuous,
        ))),
        chat_turn_service=service,
        create_asr_adapter=lambda callback: _FakeASRAdapter(callback),
        ui_updates=SimpleNamespace(
            post_notification=Mock(), post_llm_reply_finished=Mock(),
            post_busy_bar=Mock(), hide_busy_bar=Mock(),
        ),
    )
    instance.emit_user_text = wire_user_input_plugins(queue, sink=service.submit)
    return instance, service, queue


def test_continuous_wiring_defers_final_until_full_round_and_tracks_admission():
    instance, service, queue = _live_wiring(continuous=True)
    turn = service.begin_turn()
    controller = instance._create_streaming_asr()
    instance.runtime_asr = controller
    instance._bind_asr_presentation_hooks()
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        controller._adapter.callback("blue umbrella", True)
        controller._adapter.callback("blue umbrella 731", False)
        assert queue.empty()
        assert instance.last_user_message["text"] == ""
        assert not turn.is_cancelled()
        assert not service.finish_turn(turn)
        service.mark_generation_complete(turn)
        assert queue.empty()
        assert service.finish_turn(turn, before_next=instance.ui_updates.post_llm_reply_finished)
        assert queue.get_nowait() == "blue umbrella 731"
        assert queue.empty()
        assert not service.finish_turn(turn)
        assert instance.last_user_message["text"] == "blue umbrella 731"
        events = [call.args[0] for call in instance.transport.emit.call_args_list]
        final = [event for event in events if event["type"] == "asr.final"]
        partials = [event for event in events if event["type"] == "asr.partial" and event["text"]]
        assert len(final) == 1
        assert final[0]["utteranceId"] == partials[-1]["utteranceId"]
        assert events[-1] == {"type": "status.change", "status": "generating"}
        assert controller._adapter.calls == ["start"]
    finally:
        service.close()
        controller.close()


def test_disabled_feature_recovers_from_plugin_rejection(monkeypatch):
    from plugin_system.host import service as plugin_service
    plugin_manager = SimpleNamespace(wire_user_input=lambda emit, processors: processors.append(lambda text: None))
    monkeypatch.setattr(plugin_service, "_plugin_manager", plugin_manager)
    instance, service, queue = _live_wiring(continuous=False)
    controller = instance._create_streaming_asr()
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        controller._adapter.callback("rejected", False)
        _wait_until(lambda: controller._active)
        assert queue.empty()
        assert "resume" in controller._adapter.calls
        assert instance.last_user_message["text"] == ""
    finally:
        service.close()
        controller.close()


def test_disabled_feature_submits_then_pauses_until_original_reply_finished():
    instance, service, queue = _live_wiring(continuous=False)
    controller = instance._create_streaming_asr()
    instance.runtime_asr = controller
    instance._bind_asr_presentation_hooks()
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        adapter = controller._adapter
        adapter.callback("ordinary speech", False)
        assert queue.get_nowait() == "ordinary speech"
        assert not controller._active
        assert "pause" in adapter.calls
        finals = [
            call.args[0] for call in instance.transport.emit.call_args_list
            if call.args[0]["type"] == "asr.final"
        ]
        assert len(finals) == 1
        turn = service.begin_turn()
        service.mark_generation_complete(turn)
        assert service.finish_turn(turn, before_next=instance.ui_updates.post_llm_reply_finished)
        _wait_until(lambda: controller._active)
        assert "resume" in adapter.calls
        assert queue.empty()
    finally:
        service.close()
        controller.close()
