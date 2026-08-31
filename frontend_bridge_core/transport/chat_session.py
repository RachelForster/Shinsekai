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


def create_initialization_transport(endpoints: Any) -> ChatSessionTransport:
    """Connect the earliest available producer endpoint before config parsing."""

    init_endpoint = str(getattr(endpoints, "init_stream_endpoint", "") or "").strip()
    stream_endpoint = str(getattr(endpoints, "stream_endpoint", "") or "").strip()
    endpoint = init_endpoint or stream_endpoint
    sink = WSClientSink(endpoint) if endpoint else None
    transport = ChatSessionTransport(init_sink=sink)
    if sink is not None and not init_endpoint:
        transport.emit_initialization({"type": "status.change", "status": "idle"})
    return transport


def create_transport(
    options: Any,
    transport: ChatSessionTransport | None = None,
) -> ChatSessionTransport:
    """Upgrade an initialization transport with the parsed runtime endpoint."""

    args = options.args
    stream_endpoint = str(getattr(args, "stream_endpoint", "") or "").strip()
    init_endpoint = str(getattr(args, "init_stream_endpoint", "") or "").strip()
    transport = transport or ChatSessionTransport()
    bootstrap_sink = transport.init_sink

    if stream_endpoint:
        transport.stream_sink = (
            bootstrap_sink
            if _sink_endpoint(bootstrap_sink) == stream_endpoint
            else WSClientSink(stream_endpoint)
        )
    else:
        transport.stream_sink = None

    if init_endpoint:
        if _sink_endpoint(bootstrap_sink) == init_endpoint:
            transport.init_sink = bootstrap_sink
        elif _sink_endpoint(transport.stream_sink) == init_endpoint:
            transport.init_sink = transport.stream_sink
        else:
            transport.init_sink = WSClientSink(init_endpoint)
    elif (
        bootstrap_sink is not None and _sink_endpoint(bootstrap_sink) == stream_endpoint
    ):
        transport.init_sink = transport.stream_sink
    else:
        transport.init_sink = None

    if transport.stream_sink is not None:
        transport.emit({"type": "status.change", "status": "idle"})
    return transport


def _sink_endpoint(sink: Any | None) -> str:
    return str(getattr(sink, "endpoint", "") or "").strip()
