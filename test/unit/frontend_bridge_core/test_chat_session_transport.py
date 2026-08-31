from types import SimpleNamespace
from unittest.mock import Mock

from application.chat.commands import ChatCommandResult
from frontend_bridge_core.transport import chat_session
from frontend_bridge_core.transport.chat_session import ChatSessionTransport


class _Sink:
    def __init__(self) -> None:
        self.events = []
        self.handler = None
        self.closed = 0

    def emit(self, payload) -> None:
        self.events.append(payload)

    def set_command_handler(self, handler) -> None:
        self.handler = handler

    def close(self) -> None:
        self.closed += 1


def test_transport_parses_commands_and_projects_ack() -> None:
    sink = _Sink()
    dispatcher = SimpleNamespace(execute=lambda _request: ChatCommandResult(ok=True))
    transport = ChatSessionTransport(stream_sink=sink)

    transport.bind_command_dispatcher(dispatcher)
    sink.handler({"type": "send-message", "cmdId": "cmd-1", "payload": "hello"})

    assert sink.events == [
        {
            "type": "cmd.ack",
            "cmdId": "cmd-1",
            "commandType": "send-message",
            "ok": True,
        }
    ]


def test_transport_uses_separate_initialization_sink_and_closes_each_once() -> None:
    stream_sink = _Sink()
    init_sink = _Sink()
    transport = ChatSessionTransport(
        stream_sink=stream_sink,
        init_sink=init_sink,
    )

    transport.emit({"type": "runtime"})
    transport.emit_initialization({"type": "init"})
    transport.close_initialization()
    transport.close()

    assert stream_sink.events == [{"type": "runtime"}]
    assert init_sink.events == [{"type": "init"}]
    assert stream_sink.closed == 1
    assert init_sink.closed == 1


def test_factory_creates_runtime_and_initialization_sinks(monkeypatch) -> None:
    sinks = []

    def create_sink(endpoint):
        sink = _Sink()
        sink.endpoint = endpoint
        sinks.append(sink)
        return sink

    monkeypatch.setattr(chat_session, "WSClientSink", create_sink)
    options = SimpleNamespace(
        args=SimpleNamespace(
            stream_endpoint="ws://runtime",
            init_stream_endpoint="ws://init",
        )
    )

    transport = chat_session.create_transport(options)

    assert [sink.endpoint for sink in sinks] == ["ws://runtime", "ws://init"]
    assert transport.stream_sink is sinks[0]
    assert transport.init_sink is sinks[1]
    assert sinks[0].events == [{"type": "status.change", "status": "idle"}]


def test_initialization_transport_uses_bridge_endpoint_before_options_parse(
    monkeypatch,
) -> None:
    sinks = []

    def create_sink(endpoint):
        sink = _Sink()
        sink.endpoint = endpoint
        sinks.append(sink)
        return sink

    monkeypatch.setattr(chat_session, "WSClientSink", create_sink)

    transport = chat_session.create_initialization_transport(
        SimpleNamespace(
            init_stream_endpoint="ws://init",
            stream_endpoint="ws://runtime",
        )
    )

    assert transport.stream_sink is None
    assert transport.init_sink is sinks[0]
    assert sinks[0].endpoint == "ws://init"
    assert sinks[0].events == []


def test_runtime_transport_reuses_early_stream_connection(monkeypatch) -> None:
    bootstrap_sink = _Sink()
    bootstrap_sink.endpoint = "ws://runtime"
    transport = ChatSessionTransport(init_sink=bootstrap_sink)
    create_sink = Mock(side_effect=AssertionError("must reuse bootstrap sink"))
    monkeypatch.setattr(chat_session, "WSClientSink", create_sink)
    options = SimpleNamespace(
        args=SimpleNamespace(
            stream_endpoint="ws://runtime",
            init_stream_endpoint="",
        )
    )

    upgraded = chat_session.create_transport(options, transport)

    assert upgraded is transport
    assert upgraded.stream_sink is bootstrap_sink
    assert upgraded.init_sink is bootstrap_sink
    assert bootstrap_sink.events == [{"type": "status.change", "status": "idle"}]
    create_sink.assert_not_called()
