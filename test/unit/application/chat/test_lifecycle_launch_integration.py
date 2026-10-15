"""Exercise actual bridge launch/resume through the supervisor, using fake Popen."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from application.chat import composition as chat
from application.chat.stop_chat import stop_chat
from frontend_bridge_core import chat_session
from sdk.chat_process import ChatProcessContext, ChatProcessEvent
from sdk.chat_session import ChatSessionContext, ChatSessionEvent
from test.unit.application.chat.runtime_process_fakes import (
    FakeChild,
    RecordingStream,
    make_state,
)


class OwnedStream(RecordingStream):
    def __init__(self):
        super().__init__()
        self.deleted = []

    def create_session(self, snapshot):
        self.snapshot = {**snapshot, "sessionId": "actual-session"}
        return {
            "sessionId": "actual-session",
            "producerEndpoint": "ws://fixture?sessionId=actual-session",
        }

    def wait_for_producer(self, *_args, **_kwargs):
        return True

    def close_session(self, session_id, *, reason):
        self.snapshot["sessionClosedReason"] = reason

    def delete_session(self, session_id):
        self.deleted.append(session_id)
        self.snapshot = None


@pytest.mark.parametrize("mode", ["launch", "resume"])
def test_production_entrypoints_publish_real_session_identity_before_state_binding(
    tmp_path, monkeypatch, mode
):
    state = make_state(tmp_path, monkeypatch)
    state.chat_session = {}
    state.chat_stream = OwnedStream()
    state.config_manager.config.effect_list = []
    state.config_manager.config.background_list = []
    events = []
    remove = chat._application_events.subscribe(events.append)
    monkeypatch.setattr(
        "plugin_system.host.service.get_plugin_hook_dispatcher", lambda: None
    )
    monkeypatch.setattr(
        chat.subprocess, "Popen", lambda *_args, **_kwargs: FakeChild(["timeout", 0])
    )
    monkeypatch.setattr(
        chat_session,
        "_repair_template_parts_from_session_if_needed",
        lambda _state, scene, system: (scene, system),
    )
    try:
        if mode == "launch":
            result = chat_session.launch_chat(
                state, {"scenario": "scene", "system": "system"}
            )
        else:
            monkeypatch.setattr(
                chat_session,
                "_load_template_session_payload",
                lambda _: {
                    "scenario": "scene",
                    "system": "system",
                    "historyPath": str(tmp_path / "resume"),
                    "selectedCharacters": [],
                },
            )
            monkeypatch.setattr(
                chat_session,
                "_resume_template_parts",
                lambda _: ("scene", "system", "resume"),
            )
            result = chat_session.resume_last_chat(state)
        process_events = [
            context for context in events if isinstance(context, ChatProcessContext)
        ]
        assert result["sessionId"] == "actual-session"
        assert [context.event for context in process_events] == [
            ChatProcessEvent.STARTING,
            ChatProcessEvent.STARTED,
        ]
        assert all(context.session_id == "actual-session" for context in process_events)
        assert process_events[0].launch_id == state.chat_session_launch_id
        assert process_events[0].launch_id == process_events[1].launch_id
    finally:
        chat.shutdown_active_chat_process(wait_before_signal=0.5)
        if getattr(state, "chat_session_lifecycle", None) is not None:
            state.chat_session_lifecycle.dispose()
        remove()


def test_async_react_mobile_access_waits_for_ready_not_just_connected(
    tmp_path, monkeypatch
):
    state = make_state(tmp_path, monkeypatch)
    state.chat_session = {}
    state.chat_stream = OwnedStream()
    state.config_manager.config.effect_list = []
    state.config_manager.config.background_list = []
    started = []
    state.mobile_access_service = SimpleNamespace(
        start=lambda: started.append(True), stop=lambda: None, snapshot=lambda: None
    )
    monkeypatch.setattr(
        chat_session,
        "configure_mobile_access",
        lambda _state, **options: started.append(options["enabled"]),
    )
    monkeypatch.setattr(
        chat_session, "_launch_runtime_chat", lambda *_args, **_kwargs: "聊天进程已启动"
    )
    monkeypatch.setattr(
        chat_session,
        "_repair_template_parts_from_session_if_needed",
        lambda _state, scene, system: (scene, system),
    )
    stream = state.chat_stream.create_session({})
    chat_session.launch_chat(
        state,
        {"scenario": "scene", "system": "system", "enableMobileAccess": True},
        init_stream_info=stream,
    )
    assert started == []
    state.chat_session_lifecycle.ready()
    assert started == [True]
    state.chat_session_lifecycle.dispose()


def test_real_close_response_releases_closing_flag_before_final_snapshot(
    tmp_path, monkeypatch
):
    state = make_state(tmp_path, monkeypatch)
    state.chat_session = {}
    state.chat_stream = OwnedStream()
    state.config_manager.config.effect_list = []
    state.config_manager.config.background_list = []
    monkeypatch.setattr(
        chat.subprocess, "Popen", lambda *_args, **_kwargs: FakeChild(["timeout", 0])
    )
    monkeypatch.setattr(
        chat_session,
        "_repair_template_parts_from_session_if_needed",
        lambda _state, scene, system: (scene, system),
    )
    chat_session.launch_chat(state, {"scenario": "scene", "system": "system"})
    try:
        result = stop_chat(state)
        assert result["chatRuntimeClosing"] is False
        assert result["chatProcessRunning"] is False
        assert result["sessionId"] == "actual-session"
        assert state.chat_session["sessionId"] == ""
        assert state.chat_stream.deleted == ["actual-session"]
    finally:
        state.chat_session_lifecycle.dispose()
        chat._supervisor.close_log()
