"""WebSocket envelope adapter for realtime chat commands."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from application.chat.commands import ChatCommandRequest, ChatCommandResult


def parse_chat_command(raw_command: Mapping[str, object]) -> ChatCommandRequest:
    """Convert a raw WebSocket command envelope to an application request."""

    return ChatCommandRequest(
        type=str(raw_command.get("type") or "").strip(),
        command_id=str(raw_command.get("cmdId") or "").strip(),
        payload=raw_command.get("payload"),
    )


def send_chat_command_ack(
    emit: Callable[[dict[str, Any]], None],
    request: ChatCommandRequest,
    result: ChatCommandResult,
) -> None:
    """Project an application result back to the WebSocket ack envelope."""

    if not request.command_id:
        return
    emit(
        {
            "type": "cmd.ack",
            "cmdId": request.command_id,
            "commandType": request.type,
            "ok": result.ok,
            **({"error": result.error} if result.error else {}),
        }
    )
