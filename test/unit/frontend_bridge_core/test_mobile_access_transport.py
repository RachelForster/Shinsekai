from __future__ import annotations

import base64
import threading

import pytest

from frontend_bridge_core.transport.mobile_access import (
    MobileAccessTransport,
    generate_qr_data_url,
)


class _FakeHttpServer:
    def __init__(self) -> None:
        self.closed = False
        self.shutdown_requested = threading.Event()

    def serve_forever(self) -> None:
        self.shutdown_requested.wait(timeout=5.0)

    def shutdown(self) -> None:
        self.shutdown_requested.set()

    def server_close(self) -> None:
        self.closed = True


def test_mobile_access_transport_starts_adjacent_ports_and_stops(monkeypatch):
    servers: list[tuple[str, int, _FakeHttpServer]] = []
    websocket_starts: list[tuple[str, int]] = []
    websocket_stops: list[bool] = []

    def make_server(host: str, port: int) -> _FakeHttpServer:
        server = _FakeHttpServer()
        servers.append((host, port, server))
        return server

    monkeypatch.setattr(
        "frontend_bridge_core.transport.mobile_access.generate_qr_data_url",
        lambda url: f"data:image/png;base64,{base64.b64encode(url.encode()).decode()}",
    )
    transport = MobileAccessTransport(
        advertised_host_factory=lambda: "192.168.50.7",
        auth_token="launch-token",
        http_server_factory=make_server,
        preferred_http_port=8789,
        start_websocket=lambda host, port: (
            websocket_starts.append((host, port)) or f"ws://{host}:{port}/ws"
        ),
        stop_websocket=lambda: websocket_stops.append(True),
    )

    info = transport.start()

    assert info.http_port == 8789
    assert info.websocket_port == 8790
    assert info.url == (
        "http://192.168.50.7:8789/"
        "?shinsekai_bridge_token=launch-token#/chat"
    )
    assert info.websocket_url == "ws://192.168.50.7:8790/ws"
    assert servers[0][:2] == ("0.0.0.0", 8789)
    assert websocket_starts == [("192.168.50.7", 8790)]
    assert transport.start() is info

    transport.stop()

    assert websocket_stops == [True]
    assert servers[0][2].closed is True
    assert transport.snapshot() is None


def test_mobile_access_transport_tries_the_next_port_pair(monkeypatch):
    attempted_ports: list[int] = []

    def make_server(_host: str, port: int) -> _FakeHttpServer:
        attempted_ports.append(port)
        if len(attempted_ports) == 1:
            raise OSError("busy")
        return _FakeHttpServer()

    monkeypatch.setattr(
        "frontend_bridge_core.transport.mobile_access.generate_qr_data_url",
        lambda _url: "data:image/png;base64,dGVzdA==",
    )
    transport = MobileAccessTransport(
        advertised_host_factory=lambda: "10.0.0.8",
        auth_token="token",
        http_server_factory=make_server,
        preferred_http_port=9000,
        start_websocket=lambda host, port: f"ws://{host}:{port}/ws",
        stop_websocket=lambda: None,
    )
    try:
        info = transport.start()
        assert attempted_ports == [9000, 9002]
        assert info.http_port == 9002
        assert info.websocket_port == 9003
    finally:
        transport.stop()


def test_mobile_access_stop_serializes_with_concurrent_restart(monkeypatch):
    websocket_starts: list[int] = []
    stop_entered = threading.Event()
    allow_stop = threading.Event()
    stop_count = 0

    monkeypatch.setattr(
        "frontend_bridge_core.transport.mobile_access.generate_qr_data_url",
        lambda _url: "data:image/png;base64,dGVzdA==",
    )

    def stop_websocket() -> None:
        nonlocal stop_count
        stop_count += 1
        if stop_count == 1:
            stop_entered.set()
            allow_stop.wait(timeout=5.0)

    transport = MobileAccessTransport(
        advertised_host_factory=lambda: "10.0.0.8",
        auth_token="token",
        http_server_factory=lambda _host, _port: _FakeHttpServer(),
        preferred_http_port=9000,
        start_websocket=lambda host, port: (
            websocket_starts.append(port) or f"ws://{host}:{port}/ws"
        ),
        stop_websocket=stop_websocket,
    )
    transport.start()

    stop_thread = threading.Thread(target=transport.stop)
    restart_thread = threading.Thread(target=transport.start)
    stop_thread.start()
    assert stop_entered.wait(timeout=2.0)
    restart_thread.start()

    assert websocket_starts == [9001]
    allow_stop.set()
    stop_thread.join(timeout=5.0)
    restart_thread.join(timeout=5.0)

    assert not stop_thread.is_alive()
    assert not restart_thread.is_alive()
    assert websocket_starts == [9001, 9001]
    assert transport.snapshot() is not None
    transport.stop()


def test_generate_qr_data_url_returns_png():
    pytest.importorskip("qrcode")

    result = generate_qr_data_url("http://192.168.1.2:8789/#/chat")

    prefix = "data:image/png;base64,"
    assert result.startswith(prefix)
    assert base64.b64decode(result.removeprefix(prefix)).startswith(b"\x89PNG\r\n\x1a\n")
