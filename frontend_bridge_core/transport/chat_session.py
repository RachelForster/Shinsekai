"""Transport adapter for a chat runtime session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from frontend_bridge_core.transport.chat_commands import (
    parse_chat_command,
    send_chat_command_ack,
)
from frontend_bridge_core.transport.ws_client import WSClientSink


@dataclass(slots=True)
class ChatSessionTransport:
    """Own concrete WebSocket sinks while exposing narrow application ports."""

    stream_sink: WSClientSink | None = None
    init_sink: WSClientSink | None = None

    @property
    def streaming(self) -> bool:
        return self.stream_sink is not None

    def emit(self, payload: dict[str, Any]) -> None:
        if self.stream_sink is not None:
            self.stream_sink.emit(payload)

    def emit_initialization(self, payload: dict[str, Any]) -> None:
        sink = self.init_sink or self.stream_sink
        if sink is not None:
            sink.emit(payload)

    def bind_command_dispatcher(self, dispatcher: Any) -> None:
        if self.stream_sink is None:
            return

        def handle(raw_command: dict[str, object]) -> None:
            request = parse_chat_command(raw_command)
            result = dispatcher.execute(request)
            send_chat_command_ack(self.stream_sink.emit, request, result)

        self.stream_sink.set_command_handler(handle)

    def close_initialization(self) -> None:
        if self.init_sink is None or self.init_sink is self.stream_sink:
            return
        self.init_sink.close()

    def close(self) -> None:
        if self.stream_sink is not None:
            self.stream_sink.close()


def create_transport(options: Any) -> ChatSessionTransport:
    """Create runtime and initialization sinks from parsed launch options."""

    args = options.args
    stream_endpoint = str(getattr(args, "stream_endpoint", "") or "").strip()
    init_endpoint = str(getattr(args, "init_stream_endpoint", "") or "").strip()
    stream_sink = WSClientSink(stream_endpoint) if stream_endpoint else None
    init_sink = (
        stream_sink
        if init_endpoint and init_endpoint == stream_endpoint
        else WSClientSink(init_endpoint) if init_endpoint else None
    )
    transport = ChatSessionTransport(stream_sink=stream_sink, init_sink=init_sink)
    if stream_sink is not None:
        transport.emit({"type": "status.change", "status": "idle"})
    return transport
