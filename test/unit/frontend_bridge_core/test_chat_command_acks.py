"""Unit tests for ChatStreamService command ACK waiters and ACK envelope fields."""

from __future__ import annotations

import threading
import time

from application.chat.runtime.commands import ChatCommandRequest, ChatCommandResult
from frontend_bridge_core.chat_command_acks import CommandAckRegistry
from frontend_bridge_core.chat_stream import ChatStreamService
from frontend_bridge_core.transport.chat_commands import send_chat_command_ack


def test_command_ack_registry_resolve_timeout_and_cancel() -> None:
    registry = CommandAckRegistry()

    registry.register("cmd-ok")
    assert registry.resolve({"type": "cmd.ack", "cmdId": "cmd-ok", "ok": True}) is True
    resolved = registry.wait("cmd-ok", timeout=0.5)
    assert resolved is not None and resolved["ok"] is True
    assert registry.wait("cmd-ok", timeout=0.05) is None

    registry.register("cmd-timeout")
    assert registry.wait("cmd-timeout", timeout=0.02) is None

    registry.register("cmd-disc")
    registry.cancel_all("Producer left")
    disc = registry.wait("cmd-disc", timeout=0.5)
    assert disc is not None
    assert disc["ok"] is False
    assert disc["disconnected"] is True
    assert disc["error"] == "Producer left"


def test_send_chat_command_ack_projects_structured_error_metadata() -> None:
    emitted: list[dict] = []
    req = ChatCommandRequest(type="behavior-command", command_id="cid-9", payload={})
    res = ChatCommandResult(
        ok=False,
        error="Busy generating beat",
        error_code="behavior.busy",
        http_status=409,
    )
    send_chat_command_ack(emitted.append, req, res)
    assert emitted == [
        {
            "type": "cmd.ack",
            "cmdId": "cid-9",
            "commandType": "behavior-command",
            "ok": False,
            "error": "Busy generating beat",
            "errorCode": "behavior.busy",
            "httpStatus": 409,
        }
    ]


def test_chat_stream_send_command_and_wait_ack_paths(monkeypatch) -> None:
    stream = ChatStreamService(host="127.0.0.1", bridge_port=18787)
    info = stream.create_session({"status": "idle"})
    sid = info["sessionId"]

    # When send_command fails, waiter cleans up and returns delivered=False immediately
    monkeypatch.setattr(stream, "send_command", lambda _sid, _cmd: False)
    undelivered = stream.send_command_and_wait_ack(sid, {"type": "behavior-command"}, timeout=0.5)
    assert undelivered["delivered"] is False
    assert undelivered["ok"] is False

    # Rejected ACK propagates errorCode + httpStatus
    def _send_and_reject(_sid: str, cmd: dict) -> bool:
        session = stream._sessions[sid]

        def _emit_ack() -> None:
            time.sleep(0.01)
            session.pending_acks.resolve(
                {
                    "type": "cmd.ack",
                    "cmdId": cmd["cmdId"],
                    "ok": False,
                    "error": "Busy",
                    "errorCode": "behavior.busy",
                    "httpStatus": 409,
                }
            )

        threading.Thread(target=_emit_ack, daemon=True).start()
        return True

    monkeypatch.setattr(stream, "send_command", _send_and_reject)
    rejected = stream.send_command_and_wait_ack(sid, {"type": "behavior-command"}, timeout=1.0)
    assert rejected == {
        "delivered": True,
        "ok": False,
        "timedOut": False,
        "disconnected": False,
        "error": "Busy",
        "errorCode": "behavior.busy",
        "httpStatus": 409,
    }

    # Timeout returns delivered=True, timedOut=True, httpStatus=504
    monkeypatch.setattr(stream, "send_command", lambda _sid, _cmd: True)
    timed_out = stream.send_command_and_wait_ack(sid, {"type": "behavior-command"}, timeout=0.03)
    assert timed_out["delivered"] is True
    assert timed_out["ok"] is False
    assert timed_out["timedOut"] is True
    assert timed_out["httpStatus"] == 504
