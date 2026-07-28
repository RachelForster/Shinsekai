"""WebSocket producer transport used by chat runtime processes."""

from __future__ import annotations

import base64
import collections
import json
import os
import secrets
import socket
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from application.runtime.event_sink import BaseEventSink


def _append_query(url: str, params: dict[str, str]) -> str:
    pairs = [
        f"{quote(str(key), safe='')}={quote(str(value), safe='')}"
        for key, value in params.items()
        if str(value)
    ]
    if not pairs:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{'&'.join(pairs)}"


class WSClientSink(BaseEventSink):
    """Send application events to the bridge producer WebSocket endpoint."""

    def __init__(self, endpoint: str) -> None:
        super().__init__()
        self.endpoint = endpoint
        self._buffer: collections.deque[dict[str, Any]] = collections.deque()
        self._buffer_lock = threading.Lock()
        self._buffer_ready = threading.Event()
        self._command_handler: Callable[[dict[str, Any]], None] | None = None
        self._closed = False
        self._reader_started = False
        self._reader_lock = threading.Lock()
        self._worker_started = False
        self._worker_lock = threading.Lock()
        self._socket: socket.socket | None = None

    def emit(self, payload: dict[str, Any]) -> None:
        event = self._next(payload)
        self._remember(event)
        with self._buffer_lock:
            self._buffer.append(event)
            self._buffer_ready.set()
        self._ensure_worker()

    def media_url(self, raw_path: str) -> str:
        path = str(raw_path or "").strip()
        if not path:
            return ""
        if path.startswith(("http://", "https://", "blob:", "data:", "/assets/")):
            return path
        parsed = urlparse(self.endpoint)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 0
        http_port = port - 1 if port > 0 else port
        query = parse_qs(parsed.query)
        auth_token = str(
            (
                query.get("shinsekai_bridge_token")
                or query.get("token")
                or [""]
            )[0]
        ).strip()
        return _append_query(
            f"http://{host}:{http_port}/api/media?path={quote(path)}",
            {"shinsekai_bridge_token": auth_token},
        )

    def close(self) -> None:
        deadline = time.time() + 1.5
        self._closed = True
        self._buffer_ready.set()
        while time.time() < deadline:
            with self._buffer_lock:
                if not self._buffer:
                    break
            time.sleep(0.05)
        self._disconnect()

    def set_command_handler(
        self,
        handler: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        self._command_handler = handler

    def _ensure_worker(self) -> None:
        with self._worker_lock:
            if self._worker_started:
                return
            thread = threading.Thread(
                target=self._run,
                name="shinsekai-chat-ws-sink",
                daemon=True,
            )
            thread.start()
            self._worker_started = True

    def _run(self) -> None:
        while True:
            self._buffer_ready.wait(timeout=1.0)
            event = self._peek_event()
            if event is None:
                self._buffer_ready.clear()
                if self._closed:
                    return
                continue
            try:
                self._send_event(event)
                self._pop_event()
            except Exception:
                if self._closed:
                    self._clear_buffer()
                    self._disconnect()
                    return
                self._disconnect()
                time.sleep(0.5)

    def _peek_event(self) -> dict[str, Any] | None:
        with self._buffer_lock:
            return self._buffer[0] if self._buffer else None

    def _pop_event(self) -> None:
        with self._buffer_lock:
            if self._buffer:
                self._buffer.popleft()
            if not self._buffer:
                self._buffer_ready.clear()

    def _clear_buffer(self) -> None:
        with self._buffer_lock:
            self._buffer.clear()
            self._buffer_ready.clear()

    def _connect(self) -> socket.socket:
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "ws":
            raise ValueError(f"unsupported websocket endpoint: {self.endpoint}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        sock = socket.create_connection((host, port), timeout=5.0)
        sock.settimeout(5.0)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("utf-8")
        sock.sendall(request)
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake failed")
            response += chunk
        status_line = response.split(b"\r\n", 1)[0].decode(
            "utf-8",
            errors="replace",
        )
        if "101" not in status_line:
            raise ConnectionError(
                f"unexpected websocket handshake response: {status_line}"
            )
        return sock

    def _send_event(self, event: dict[str, Any]) -> None:
        if self._socket is None:
            self._socket = self._connect()
            self._ensure_reader(self._socket)
        data = json.dumps(event, ensure_ascii=False).encode("utf-8")
        self._send_frame(self._socket, data)

    def _disconnect(self) -> None:
        if self._socket is None:
            return
        try:
            self._socket.close()
        except OSError:
            pass
        self._socket = None
        with self._reader_lock:
            self._reader_started = False

    def _ensure_reader(self, sock: socket.socket) -> None:
        with self._reader_lock:
            if self._reader_started:
                return
            thread = threading.Thread(
                target=self._read_loop,
                args=(sock,),
                name="shinsekai-chat-ws-sink-reader",
                daemon=True,
            )
            thread.start()
            self._reader_started = True

    def _read_loop(self, sock: socket.socket) -> None:
        try:
            while not self._closed and self._socket is sock:
                try:
                    opcode, payload = self._read_frame(sock)
                except socket.timeout:
                    continue
                if opcode == 0x8:
                    return
                if opcode == 0x9:
                    self._send_control_frame(sock, 0xA, payload)
                    continue
                if opcode != 0x1:
                    continue
                message = json.loads(payload.decode("utf-8"))
                if not isinstance(message, dict):
                    continue
                if str(message.get("type") or "") != "command":
                    continue
                command = message.get("command")
                if isinstance(command, dict):
                    self._dispatch_command(command)
        except Exception:
            pass
        finally:
            if self._socket is sock:
                self._disconnect()

    def _dispatch_command(self, command: dict[str, Any]) -> None:
        handler = self._command_handler
        if handler is None:
            return
        try:
            handler(command)
        except Exception:
            pass

    @staticmethod
    def _read_exact(sock: socket.socket, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ConnectionError("websocket connection closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @classmethod
    def _read_frame(cls, sock: socket.socket) -> tuple[int, bytes]:
        header = cls._read_exact(sock, 2)
        opcode = header[0] & 0x0F
        masked = bool(header[1] & 0x80)
        length = header[1] & 0x7F
        if length == 126:
            length = int.from_bytes(cls._read_exact(sock, 2), "big")
        elif length == 127:
            length = int.from_bytes(cls._read_exact(sock, 8), "big")
        mask = cls._read_exact(sock, 4) if masked else b""
        payload = cls._read_exact(sock, length)
        if masked:
            payload = bytes(
                byte ^ mask[index % 4] for index, byte in enumerate(payload)
            )
        return opcode, payload

    @staticmethod
    def _send_control_frame(
        sock: socket.socket,
        opcode: int,
        payload: bytes,
    ) -> None:
        header = bytearray([0x80 | (opcode & 0x0F)])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(0x80 | 127)
            header.extend(length.to_bytes(8, "big"))
        mask = os.urandom(4)
        masked = bytes(
            byte ^ mask[index % 4] for index, byte in enumerate(payload)
        )
        sock.sendall(bytes(header) + mask + masked)

    @staticmethod
    def _send_frame(sock: socket.socket, payload: bytes) -> None:
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(0x80 | 127)
            header.extend(length.to_bytes(8, "big"))
        mask = secrets.token_bytes(4)
        masked = bytes(
            byte ^ mask[index % 4] for index, byte in enumerate(payload)
        )
        sock.sendall(bytes(header) + mask + masked)
