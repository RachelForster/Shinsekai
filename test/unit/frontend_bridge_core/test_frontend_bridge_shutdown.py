from __future__ import annotations

from types import SimpleNamespace

import pytest

import frontend_bridge
from application.chat import runtime_process as chat


class _ChatStreamStub:
    def __init__(self):
        self.sent = []
        self.stopped = False

    def send_command(self, session_id, command):
        self.sent.append((session_id, command))
        return True

    def stop(self):
        self.stopped = True


def test_plugin_frontend_input_forwards_to_active_chat_stream() -> None:
    stream = _ChatStreamStub()
    state = SimpleNamespace(
        chat_session={"sessionId": "session-1"},
        chat_stream=stream,
    )

    frontend_bridge._forward_plugin_user_input(
        state,
        {
            "pluginId": "demo.plugin",
            "text": "[短信] 请角色回复",
            "type": "plugin.user-input.submit",
        },
    )

    assert len(stream.sent) == 1
    session_id, command = stream.sent[0]
    assert session_id == "session-1"
    assert command["type"] == "send-message"
    assert command["payload"] == {
        "attachments": [],
        "text": "[短信] 请角色回复",
    }
    assert command["cmdId"]


def test_shutdown_bridge_runtime_stops_active_chat_and_stream(monkeypatch):
    calls = []
    stream = _ChatStreamStub()
    state = SimpleNamespace(chat_stream=stream)

    def fake_shutdown_active_chat_process(*, wait_timeout, wait_before_signal=0.0):
        calls.append((wait_timeout, wait_before_signal))

    monkeypatch.setattr(chat, "shutdown_active_chat_process", fake_shutdown_active_chat_process)
    frontend_bridge._set_bridge_state(state)
    try:
        frontend_bridge._shutdown_bridge_runtime("unit-test")
    finally:
        frontend_bridge._set_bridge_state(None)

    assert calls == [(1.5, 0.0)]
    assert stream.stopped is True


def test_parent_watchdog_exit_cleans_bridge_runtime_before_process_exit(monkeypatch):
    calls = []

    def fake_exit(code):
        raise SystemExit(code)

    monkeypatch.setattr(frontend_bridge, "_shutdown_bridge_runtime", lambda reason: calls.append(reason))
    monkeypatch.setattr(frontend_bridge.os, "_exit", fake_exit)

    with pytest.raises(SystemExit) as exc:
        frontend_bridge._exit_bridge_after_parent_loss("parent_missing parent_pid=123")

    assert exc.value.code == 0
    assert calls == ["parent watchdog parent_missing parent_pid=123"]
