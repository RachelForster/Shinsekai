from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock
from queue import Queue
import pytest

from core.messaging.continuous_asr_policy import ContinuousASRPolicy
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
            input_queue=object(), presentation_queue=object(), ui_worker=None
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


def _live_wiring(*, continuous: bool):
    queue = Queue()
    service = ChatTurnService(continuous_policy=ContinuousASRPolicy() if continuous else None, sink=queue.put, options=ChatTurnOptions(interrupt_enabled=True))
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
        assert instance.last_user_message["text"] == "rejected"
    finally:
        service.close()
        controller.close()


@pytest.mark.parametrize("batch", [False, True])
def test_hold_input_keeps_official_manual_delivery_in_experimental_session(batch):
    instance, service, queue = _live_wiring(continuous=True)
    service.update_options(ChatTurnOptions(batch_enabled=batch, batch_idle_seconds=300))
    turn = service.begin_turn()
    controller = instance._create_streaming_asr()
    try:
        controller.begin_hold()
        _wait_until(lambda: controller._active)
        controller._adapter.callback("manual hold input", True)
        assert queue.empty()
        controller.finish_hold()
        assert queue.get_nowait() == "manual hold input"
        assert queue.empty()
        assert turn.is_cancelled()
        events = [call.args[0] for call in instance.transport.emit.call_args_list]
        transcripts = [event for event in events if event["type"] in ("asr.partial", "asr.final")]
        assert transcripts
        assert all(event.get("continuous") is not True for event in transcripts)
        assert all("utteranceId" not in event for event in transcripts)
        assert len([event for event in transcripts if event["type"] == "asr.final"]) == 1
    finally:
        controller.close()
        service.close()


@pytest.mark.parametrize("fallback", [False, True])
def test_disabled_feature_submits_then_pauses_until_original_reply_finished(fallback):
    instance, service, queue = _live_wiring(continuous=False)
    controller = instance._create_streaming_asr()
    controller._silence_submit_seconds = 300
    instance.runtime_asr = controller
    instance._bind_asr_presentation_hooks()
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        adapter = controller._adapter
        if fallback:
            adapter.callback("ordinary speech", True)
            timer = controller._silence_timer
            timer.function(*timer.args, **timer.kwargs)
        else:
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
        assert adapter.calls == ["start", "pause", "resume"]
        assert controller._adapter is adapter
        assert queue.empty()
    finally:
        service.close()
        controller.close()


@pytest.mark.parametrize("reply_first", [False, True])
@pytest.mark.parametrize("fallback", [False, True])
def test_continuous_wiring_batches_speech_and_clears_drafts_only_on_admission(reply_first, fallback):
    instance, service, queue = _live_wiring(continuous=True)
    service.update_options(ChatTurnOptions(batch_enabled=True, batch_idle_seconds=300))
    turn = service.begin_turn()
    controller = instance._create_streaming_asr()
    controller._silence_submit_seconds = 300
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        adapter = controller._adapter
        ids = []
        for text in ("first sentence", "second sentence"):
            adapter = controller._adapter
            adapter.callback(text, True)
            assert not service.batch_state().scheduled
            ids.append(controller._utterance_id)
            if fallback:
                timer = controller._silence_timer
                timer.function(*timer.args, **timer.kwargs)
                _wait_until(lambda: controller._active and controller._adapter is not adapter)
                adapter.callback("corrected cumulative old text", True)
                adapter.callback("old final", False)
            else:
                adapter.callback(text, False)
            assert service.batch_state().scheduled
        assert not turn.is_cancelled()
        assert queue.empty()
        events = lambda: [call.args[0] for call in instance.transport.emit.call_args_list]
        assert not [event for event in events() if event["type"] == "asr.final"]
        service.mark_generation_complete(turn)
        if reply_first:
            service.finish_turn(turn)
            assert queue.empty()
        timer = service._batch_timer
        timer.function(*timer.args, **timer.kwargs)
        if not reply_first:
            assert queue.empty()
            service.finish_turn(turn)
        assert queue.get_nowait() == "first sentence\n---\nsecond sentence"
        assert queue.empty()
        finals = [event for event in events() if event["type"] == "asr.final"]
        assert [event["utteranceId"] for event in finals] == ids
        assert instance.last_user_message["text"] == "first sentence\n---\nsecond sentence"
        assert adapter.calls == (["start", "stop"] if fallback else ["start"])
    finally:
        controller.close()
        service.close()


def test_pausing_capture_releases_stacked_speech_activity_without_clearing_manual_draft():
    instance, service, queue = _live_wiring(continuous=True)
    service.update_options(ChatTurnOptions(batch_enabled=True, batch_idle_seconds=300))
    controller = instance._create_streaming_asr()
    controller._silence_submit_seconds = 300
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        controller._adapter.callback("first", False)
        controller._adapter.callback("unfinished", True)
        service.input_changed(has_text=True)
        controller.user_pause()
        assert not service.batch_state().scheduled
        service.input_changed(has_text=False)
        timer = service._batch_timer
        timer.function(*timer.args, **timer.kwargs)
        assert queue.get_nowait() == "first"
        assert queue.empty()
    finally:
        controller.close()
        service.close()


def test_noise_only_final_releases_stacked_speech_activity():
    instance, service, queue = _live_wiring(continuous=True)
    service.update_options(ChatTurnOptions(batch_enabled=True, batch_idle_seconds=300))
    controller = instance._create_streaming_asr()
    controller._silence_submit_seconds = 300
    try:
        controller.user_resume()
        _wait_until(lambda: controller._active)
        adapter = controller._adapter
        adapter.callback("first", False)
        adapter.callback("noise", True)
        assert not service.batch_state().scheduled
        old_id = controller._utterance_id
        adapter.callback("", False)
        assert controller._utterance_id != old_id
        timer = service._batch_timer
        assert timer is not None
        timer.function(*timer.args, **timer.kwargs)
        assert queue.get_nowait() == "first"
        assert queue.empty()
        events = [call.args[0] for call in instance.transport.emit.call_args_list]
        assert {"type": "asr.partial", "text": "", "utteranceId": old_id, "continuous": True} in events
    finally:
        controller.close()
        service.close()
