"""Tests for unified runtime shutdown orchestration and host-vs-standalone server lifetime."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai.t2i.t2i_adapter import ComfyUIT2IAdapter
from application.chat.runtime import session as session_runtime
from application.runtime.stop_managed_services import stop_managed_services
from sdk import process_guard


def test_stop_managed_services_stops_all_subsystems_and_reports_partial_errors(
    monkeypatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "application.chat.stop_chat.stop_chat",
        lambda state, reason, wait_timeout: calls.append(f"stop_chat:{reason}:{wait_timeout}"),
    )
    monkeypatch.setattr(
        "application.chat.composition.shutdown_active_chat_process",
        lambda wait_timeout: calls.append(f"shutdown_active_chat:{wait_timeout}"),
    )
    monkeypatch.setattr(
        "application.perception.server_launcher.shutdown_perception_local_server",
        lambda: calls.append("shutdown_perception"),
    )
    monkeypatch.setattr(
        process_guard,
        "get_process_registry",
        lambda: SimpleNamespace(
            shutdown_host_all=lambda timeout: calls.append(f"shutdown_host_all:{timeout}") or 3
        ),
    )
    # Patch the already-imported binding inside stop_managed_services.
    import application.runtime.stop_managed_services as sms

    monkeypatch.setattr(
        sms,
        "get_process_registry",
        lambda: SimpleNamespace(
            shutdown_host_all=lambda timeout: calls.append(f"shutdown_host_all:{timeout}") or 3
        ),
    )

    state = SimpleNamespace(
        chat_session={"sessionId": "sess-1"},
        services=SimpleNamespace(close_runtimes=lambda: calls.append("close_agent")),
    )
    result = stop_managed_services(state, reason="desktop exit", chat_wait_timeout=5.0, process_wait_timeout=4.0)

    assert result == {"ok": True, "stoppedProcesses": 3, "errors": []}
    assert calls == [
        "stop_chat:desktop exit:5.0",
        "shutdown_active_chat:2.0",
        "close_agent",
        "shutdown_perception",
        "shutdown_host_all:4.0",
    ]


def test_stop_managed_services_continues_on_subsystem_failure(monkeypatch) -> None:
    import application.runtime.stop_managed_services as sms

    monkeypatch.setattr(
        "application.chat.stop_chat.stop_chat",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("chat boom")),
    )
    monkeypatch.setattr(
        "application.chat.composition.shutdown_active_chat_process",
        lambda **_kw: None,
    )
    monkeypatch.setattr(
        "application.perception.server_launcher.shutdown_perception_local_server",
        lambda: (_ for _ in ()).throw(RuntimeError("perception boom")),
    )
    registry_calls: list[float] = []
    monkeypatch.setattr(
        sms,
        "get_process_registry",
        lambda: SimpleNamespace(shutdown_host_all=lambda timeout: registry_calls.append(timeout) or 1),
    )

    state = SimpleNamespace(
        chat_session={"sessionId": "sess-err"},
        services=SimpleNamespace(close_runtimes=lambda: (_ for _ in ()).throw(RuntimeError("agent boom"))),
    )
    result = stop_managed_services(state, process_wait_timeout=2.5)

    assert result["ok"] is True
    assert result["stoppedProcesses"] == 1
    assert [err["step"] for err in result["errors"]] == ["chat", "agent", "perception"]
    assert registry_calls == [2.5]


def test_system_route_runtime_shutdown_calls_use_case(monkeypatch) -> None:
    from frontend_bridge_core.routes.system_routes import SYSTEM_ROUTES

    route = next(r for r in SYSTEM_ROUTES if r.pattern == "/api/runtime/shutdown")
    assert "POST" in route.methods

    monkeypatch.setattr(
        "application.runtime.stop_managed_services.stop_managed_services",
        lambda state, reason="shutdown": {"ok": True, "reason": reason, "hasState": state is not None},
    )
    response = route.handler(SimpleNamespace(state="mock-state", query={}, body={}, params={}))
    assert response.data == {"ok": True, "reason": "bridge shutdown", "hasState": True}


def test_chat_session_tts_and_t2i_shutdown_keeps_servers_alive_under_host(monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []
    fake_tts = SimpleNamespace(shutdown=lambda *, stop_server=True: calls.append(("tts", stop_server)))
    fake_t2i = SimpleNamespace(shutdown=lambda *, stop_server=False: calls.append(("t2i", stop_server)))
    session = session_runtime.StreamingChatSession(
        options=SimpleNamespace(args=SimpleNamespace()),
        startup=SimpleNamespace(tts_manager=fake_tts, t2i_manager=fake_t2i),
        transport=SimpleNamespace(),
        initialization=SimpleNamespace(),
    )

    shutdown_cb = session._tts_shutdown()
    assert shutdown_cb is not None

    monkeypatch.setattr("sdk.process_guard.is_host_managed", lambda: True)
    shutdown_cb()
    assert calls == [("tts", False), ("t2i", False)]

    calls.clear()
    monkeypatch.setattr("sdk.process_guard.is_host_managed", lambda: False)
    shutdown_cb()
    assert calls == [("tts", True), ("t2i", True)]


def test_comfyui_adapter_registers_autostart_server_and_stops_on_ready_timeout(
    tmp_path,
    monkeypatch,
) -> None:
    portable = tmp_path / "ComfyPortable"
    for rel in ("python_embeded/python.exe", "ComfyUI/main.py"):
        target = portable / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()

    registered: list[tuple[object, dict[str, object]]] = []
    stopped: list[object] = []

    fake_registry = SimpleNamespace(
        register=lambda proc, **kw: registered.append((proc, kw)),
        stop_process=lambda proc, timeout=5.0: stopped.append((proc, timeout)),
    )
    monkeypatch.setattr("ai.t2i.comfyui_server.get_process_registry", lambda: fake_registry)

    fake_proc = SimpleNamespace(pid=32100)
    monkeypatch.setattr("ai.t2i.t2i_adapter.subprocess.Popen", lambda *_a, **_kw: fake_proc)

    adapter = ComfyUIT2IAdapter.__new__(ComfyUIT2IAdapter)
    adapter.api_url = "http://127.0.0.1:8189"
    adapter.work_path = str(portable)
    adapter.startup_args = ""
    adapter.auto_start = True
    monkeypatch.setattr(adapter, "_is_server_ready", lambda: False)
    monkeypatch.setattr(adapter, "_wait_for_server_ready", lambda: True)

    adapter._start_server_process()
    assert adapter.owns_server_process is True
    assert registered[0][0] is fake_proc
    assert registered[0][1] == {
        "name": "comfyui",
        "kind": "t2i",
        "scope": "host",
        "name_hint": "python",
    }

    adapter.stop_server()
    assert adapter.owns_server_process is False
    assert stopped == [(fake_proc, 5.0)]

    # If readiness times out, the newly spawned process is stopped before raising.
    stopped.clear()
    monkeypatch.setattr(adapter, "_wait_for_server_ready", lambda: False)
    with pytest.raises(RuntimeError, match="ComfyUI"):
        adapter._start_server_process()
    assert stopped == [(fake_proc, 5.0)]
