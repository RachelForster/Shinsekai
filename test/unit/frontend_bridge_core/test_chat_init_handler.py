from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace

import pytest

from frontend_bridge_core.handler import FrontendBridgeHandler


def _handler() -> FrontendBridgeHandler:
    handler = FrontendBridgeHandler.__new__(FrontendBridgeHandler)
    handler.server = SimpleNamespace(state=SimpleNamespace())
    return handler


def test_chat_init_route_returns_accepted_task(monkeypatch):
    handler = _handler()
    handler.path = "/api/chat/init"
    handler._require_authorized_write = lambda _path: None
    handler._read_json = lambda: {"mode": "resume-last"}
    task = {"id": "chat-init-1", "kind": "chat-init", "status": "queued"}
    handler._start_chat_init = lambda _body: task
    responses: list[tuple[object, object]] = []
    handler._send_json = lambda payload, status=HTTPStatus.OK: responses.append((payload, status))

    handler.do_POST()

    assert responses == [(task, HTTPStatus.ACCEPTED)]


def test_start_chat_init_validates_launch_payload():
    handler = _handler()

    with pytest.raises(ValueError, match="payload must be an object"):
        handler._start_chat_init({"mode": "launch", "payload": "invalid"})

    with pytest.raises(ValueError, match="mode must be"):
        handler._start_chat_init({"mode": "unknown"})


def test_start_chat_init_forwards_launch_and_resume_callbacks(monkeypatch):
    handler = _handler()
    calls: list[tuple[str, object, object]] = []

    def launch_chat(payload, *, init_stream_info=None):
        calls.append(("launch", payload, init_stream_info))
        return {"status": "idle"}

    def resume_chat(*, init_stream_info=None):
        calls.append(("resume-last", None, init_stream_info))
        return {"status": "idle"}

    handler._launch_chat = launch_chat
    handler._resume_last_chat = resume_chat

    def start_chat_init(_state, *, mode, launch):
        stream_info = {"sessionId": "init-session"}
        result = launch(stream_info)
        calls.append(("coordinator", mode, result))
        return {"id": f"task-{mode}"}

    monkeypatch.setattr("frontend_bridge_core.handler.start_chat_init", start_chat_init)

    launch_task = handler._start_chat_init({"mode": "launch", "payload": {"templateId": "demo"}})
    resume_task = handler._start_chat_init({"mode": "resume-last"})

    assert launch_task == {"id": "task-launch"}
    assert resume_task == {"id": "task-resume-last"}
    assert calls == [
        ("launch", {"templateId": "demo"}, {"sessionId": "init-session"}),
        ("coordinator", "launch", {"status": "idle"}),
        ("resume-last", None, {"sessionId": "init-session"}),
        ("coordinator", "resume-last", {"status": "idle"}),
    ]


def test_legacy_chat_routes_keep_synchronous_snapshot_shape():
    handler = _handler()
    handler._require_authorized_write = lambda _path: None
    handler._read_json = lambda: {"templateId": "demo"}
    responses: list[tuple[object, object]] = []
    handler._send_json = lambda payload, status=HTTPStatus.OK: responses.append((payload, status))
    launch_snapshot = {"status": "idle", "sessionId": "legacy-launch"}
    resume_snapshot = {"status": "idle", "sessionId": "legacy-resume"}
    handler._launch_chat = lambda _body: launch_snapshot
    handler._resume_last_chat = lambda: resume_snapshot

    handler.path = "/api/chat/launch"
    handler.do_POST()
    handler.path = "/api/chat/resume-last"
    handler.do_POST()

    assert responses == [
        (launch_snapshot, HTTPStatus.OK),
        (resume_snapshot, HTTPStatus.OK),
    ]
