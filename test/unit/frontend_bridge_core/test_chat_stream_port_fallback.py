from __future__ import annotations

import socket

from frontend_bridge_core.chat_stream import ChatStreamService


def test_chat_stream_falls_back_to_ephemeral_port_when_ws_port_is_busy() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        occupied_ws_port = int(blocker.getsockname()[1])
        bridge_port = occupied_ws_port - 1
        service = ChatStreamService(host="127.0.0.1", bridge_port=bridge_port)
        service.start()
        try:
            assert service.ws_port != occupied_ws_port
            assert service.ws_port > 0
            assert service.ws_base == f"ws://127.0.0.1:{service.ws_port}/ws"
            session = service.create_session({"dialogText": "fallback"})
            assert session["wsUrl"] == service.ws_base
        finally:
            service.stop()
