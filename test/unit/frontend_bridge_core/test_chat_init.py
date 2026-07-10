from __future__ import annotations

import threading
import time
from typing import Any

from frontend_bridge_core.chat_init import start_chat_init
from frontend_bridge_core.state import BridgeState
from frontend_bridge_core.tasks import _get_task, _request_task_cancel


class _ChatStreamStub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counter = 0
        self.deleted_sessions: list[str] = []
        self.snapshots: dict[str, dict[str, Any]] = {}

    def create_session(self, snapshot: dict[str, Any]) -> dict[str, str]:
        with self._lock:
            self._counter += 1
            session_id = f"init-session-{self._counter}"
            self.snapshots[session_id] = {**snapshot, "sessionId": session_id}
        return {
            "producerEndpoint": f"ws://127.0.0.1:8788/ws?sessionId={session_id}&role=producer",
            "sessionId": session_id,
            "wsUrl": "ws://127.0.0.1:8788/ws",
        }

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            self.deleted_sessions.append(session_id)
            self.snapshots.pop(session_id, None)

    def get_snapshot(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            snapshot = self.snapshots.get(session_id)
            if snapshot is None:
                return None
            result = dict(snapshot)
            if isinstance(result.get("initTask"), dict):
                result["initTask"] = dict(result["initTask"])
            return result

    def set_init_task(self, session_id: str, task: dict[str, Any]) -> None:
        with self._lock:
            self.snapshots[session_id]["initTask"] = dict(task)


def _state() -> BridgeState:
    state = BridgeState(
        background_manager=None,
        character_manager=None,
        config_manager=None,
        template_generator=None,
    )
    state.chat_stream = _ChatStreamStub()
    return state


def _wait_for_task(state: BridgeState, task_id: str, statuses: set[str], timeout: float = 3.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = _get_task(state, task_id)
        if str(task.get("status") or "") in statuses:
            return task
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not reach {statuses}: {_get_task(state, task_id)}")


def _patch_runtime(monkeypatch, *, mode: str = "react") -> dict[str, Any]:
    runtime = {"running": False, "closeReasons": []}

    monkeypatch.setattr("frontend_bridge_core.chat_init._chat_process_running", lambda: runtime["running"])
    monkeypatch.setattr("frontend_bridge_core.chat_init._chat_runtime_mode", lambda _state: mode)
    monkeypatch.setattr(
        "frontend_bridge_core.chat_init._chat_snapshot",
        lambda _state, *_args, **_kwargs: {
            "chatProcessRunning": runtime["running"],
            "dialogText": "",
            "inputDraft": "",
            "options": [],
            "sprites": [],
            "status": "idle",
        },
    )

    def close_chat(_state, *, reason: str, **_kwargs):
        runtime["running"] = False
        runtime["closeReasons"].append(reason)
        return {"status": "idle"}

    monkeypatch.setattr("frontend_bridge_core.chat_init._close_chat", close_chat)
    return runtime


def test_chat_init_deduplicates_and_waits_for_explicit_completion(monkeypatch):
    state = _state()
    runtime = _patch_runtime(monkeypatch)
    release_completion = threading.Event()
    launch_calls: list[str] = []

    def launch(stream_info: dict[str, str]) -> dict[str, Any]:
        session_id = stream_info["sessionId"]
        launch_calls.append(session_id)
        runtime["running"] = True
        state.chat_session = {"sessionId": session_id}
        state.chat_stream.set_init_task(
            session_id,
            {"status": "running", "phase": "memory", "progress": 0.45, "message": "Loading memory"},
        )

        def complete() -> None:
            release_completion.wait(timeout=2.0)
            state.chat_stream.set_init_task(
                session_id,
                {"status": "succeeded", "phase": "completed", "progress": 1, "message": "Ready"},
            )

        threading.Thread(target=complete, daemon=True).start()
        return {"status": "idle", "_chatInitStreamAttached": True}

    first = start_chat_init(state, mode="launch", launch=launch, timeout=2.0)
    running = _wait_for_task(state, first["id"], {"running"})
    while running.get("phase") != "memory":
        time.sleep(0.01)
        running = _get_task(state, first["id"])

    second = start_chat_init(state, mode="launch", launch=launch, timeout=2.0)
    assert second["id"] == first["id"]
    assert running["progress"] == 0.45
    assert running["message"] == "Loading memory"

    release_completion.set()
    finished = _wait_for_task(state, first["id"], {"succeeded"})

    assert len(launch_calls) == 1
    assert finished["progress"] == 1
    assert finished["result"]["chatProcessRunning"] is True
    assert state.chat_stream.deleted_sessions == []
    assert state.chat_init_task_id == ""


def test_producer_connection_without_init_terminal_event_times_out(monkeypatch):
    state = _state()
    runtime = _patch_runtime(monkeypatch)

    def launch(_stream_info: dict[str, str]) -> dict[str, Any]:
        runtime["running"] = True
        return {"status": "idle", "_chatInitStreamAttached": True}

    task = start_chat_init(state, mode="launch", launch=launch, timeout=0.08)
    failed = _wait_for_task(state, task["id"], {"failed"})

    assert "timed out" in failed["error"]
    assert runtime["closeReasons"] == ["Chat initialization did not complete."]
    assert state.chat_stream.deleted_sessions == ["init-session-1"]


def test_chat_init_does_not_treat_a_closing_runtime_as_ready(monkeypatch):
    state = _state()
    state.chat_runtime_closing = True
    runtime = _patch_runtime(monkeypatch)
    runtime["running"] = True
    launch_called = False

    def launch(_stream_info: dict[str, str]) -> dict[str, Any]:
        nonlocal launch_called
        launch_called = True
        return {"status": "idle", "_chatInitStreamAttached": True}

    task = start_chat_init(state, mode="launch", launch=launch, timeout=1.0)
    failed = _wait_for_task(state, task["id"], {"failed"})

    assert "closing" in failed["error"]
    assert launch_called is False
    assert state.chat_stream.snapshots == {}


def test_failed_init_event_fails_task_and_cleans_process_and_session(monkeypatch):
    state = _state()
    runtime = _patch_runtime(monkeypatch)

    def launch(stream_info: dict[str, str]) -> dict[str, Any]:
        runtime["running"] = True
        state.chat_session = {"sessionId": stream_info["sessionId"]}
        state.chat_stream.set_init_task(
            stream_info["sessionId"],
            {
                "status": "failed",
                "phase": "tts",
                "progress": 0.3,
                "message": "TTS failed",
                "error": "server did not start",
            },
        )
        return {"status": "idle", "_chatInitStreamAttached": True}

    task = start_chat_init(state, mode="launch", launch=launch, timeout=1.0)
    failed = _wait_for_task(state, task["id"], {"failed"})

    assert failed["phase"] == "failed"
    assert failed["error"] == "server did not start"
    assert runtime["running"] is False
    assert state.chat_stream.deleted_sessions == ["init-session-1"]
    assert state.chat_session["sessionId"] == ""


def test_runtime_dependency_error_is_a_successful_actionable_result(monkeypatch):
    state = _state()
    _patch_runtime(monkeypatch)
    dependency_snapshot = {
        "dialogText": "Missing Python module: demo_runtime",
        "inputDraft": "",
        "options": [],
        "runtimeDependencyError": {
            "kind": "missing_dependency",
            "moduleName": "demo_runtime",
            "packageName": "demo-runtime",
        },
        "sprites": [],
        "status": "error",
        "statusMessage": "Missing Python module: demo_runtime",
    }

    task = start_chat_init(
        state,
        mode="launch",
        launch=lambda _stream_info: dict(dependency_snapshot),
        timeout=1.0,
    )
    finished = _wait_for_task(state, task["id"], {"succeeded"})

    assert finished["result"] == dependency_snapshot
    assert state.chat_stream.deleted_sessions == ["init-session-1"]


def test_cancelled_chat_init_cleans_runtime(monkeypatch):
    state = _state()
    runtime = _patch_runtime(monkeypatch)
    launched = threading.Event()

    def launch(_stream_info: dict[str, str]) -> dict[str, Any]:
        runtime["running"] = True
        launched.set()
        return {"status": "idle", "_chatInitStreamAttached": True}

    task = start_chat_init(state, mode="resume-last", launch=launch, timeout=2.0)
    assert launched.wait(timeout=1.0)
    _request_task_cancel(state, task["id"])
    cancelled = _wait_for_task(state, task["id"], {"cancelled"})

    assert cancelled["status"] == "cancelled"
    assert runtime["running"] is False
    assert state.chat_stream.deleted_sessions == ["init-session-1"]


def test_native_chat_init_deletes_hidden_progress_session_after_success(monkeypatch):
    state = _state()
    runtime = _patch_runtime(monkeypatch, mode="native")

    def launch(stream_info: dict[str, str]) -> dict[str, Any]:
        runtime["running"] = True
        state.chat_stream.set_init_task(
            stream_info["sessionId"],
            {"status": "succeeded", "phase": "completed", "progress": 1, "message": "Ready"},
        )
        return {"status": "idle", "_chatInitStreamAttached": True}

    task = start_chat_init(state, mode="launch", launch=launch, timeout=1.0)
    finished = _wait_for_task(state, task["id"], {"succeeded"})

    assert finished["result"]["chatProcessRunning"] is True
    assert state.chat_stream.deleted_sessions == ["init-session-1"]
    assert not state.chat_session.get("sessionId")
