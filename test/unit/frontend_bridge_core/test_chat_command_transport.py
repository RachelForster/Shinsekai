from application.chat.commands import ChatCommandResult
from frontend_bridge_core.transport.chat_commands import (
    parse_chat_command,
    send_chat_command_ack,
)


def test_parse_chat_command_keeps_websocket_envelope_out_of_application() -> None:
    request = parse_chat_command(
        {
            "type": " send-message ",
            "cmdId": " command-1 ",
            "payload": {"text": "hello"},
            "transportOnly": True,
        }
    )

    assert request.type == "send-message"
    assert request.command_id == "command-1"
    assert request.payload == {"text": "hello"}


def test_send_chat_command_ack_projects_success_and_failure() -> None:
    emitted: list[dict[str, object]] = []
    request = parse_chat_command(
        {"type": "clear-history", "cmdId": "command-2", "payload": None}
    )

    send_chat_command_ack(emitted.append, request, ChatCommandResult(ok=True))
    send_chat_command_ack(
        emitted.append,
        request,
        ChatCommandResult(ok=False, error="failed"),
    )

    assert emitted == [
        {
            "type": "cmd.ack",
            "cmdId": "command-2",
            "commandType": "clear-history",
            "ok": True,
        },
        {
            "type": "cmd.ack",
            "cmdId": "command-2",
            "commandType": "clear-history",
            "ok": False,
            "error": "failed",
        },
    ]


def test_send_chat_command_ack_ignores_fire_and_forget_commands() -> None:
    emitted: list[dict[str, object]] = []
    request = parse_chat_command({"type": "pause-asr"})

    send_chat_command_ack(emitted.append, request, ChatCommandResult(ok=True))

    assert emitted == []
