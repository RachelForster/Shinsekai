from __future__ import annotations

from types import SimpleNamespace

import pytest

import frontend_bridge
from frontend_bridge_core import chat


class _ChatStreamStub:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


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
