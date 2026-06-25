from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from core.runtime.event_sink import build_event, fold_event_into_snapshot, make_empty_chat_snapshot
from core.runtime.restart_debug import write_restart_debug_log


def _stream_debug_log(message: str) -> None:
    write_restart_debug_log("chat_stream", message)


def _external_host(bind_host: str) -> str:
    host = str(bind_host or "").strip()
    if host in {"", "0.0.0.0", "::", "[::]"}:
        return "127.0.0.1"
    return host


def _http_base(host: str, port: int) -> str:
    return f"http://{_external_host(host)}:{int(port)}"


def _ws_base(host: str, port: int) -> str:
    return f"ws://{_external_host(host)}:{int(port)}/ws"


def _is_direct_media_path(raw_path: str) -> bool:
    return raw_path.startswith(("http://", "https://", "blob:", "data:", "/assets/"))


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


@dataclass(eq=False)
class _WebSocketConnection:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    role: str
    session_id: str
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        async with self.send_lock:
            await _send_ws_frame(self.writer, 0x1, data)

    async def close(self) -> None:
        try:
            async with self.send_lock:
                await _send_ws_frame(self.writer, 0x8, b"")
        except Exception:
            pass
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass


@dataclass
class _ChatStreamSession:
    session_id: str
    snapshot: dict[str, Any]
    last_seq: int = 0
    producer: _WebSocketConnection | None = None
    producer_ready: threading.Event = field(default_factory=threading.Event, repr=False)
    viewers: set[_WebSocketConnection] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)


async def _send_ws_frame(writer: asyncio.StreamWriter, opcode: int, payload: bytes) -> None:
    header = bytearray([0x80 | (opcode & 0x0F)])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(length.to_bytes(2, "big"))
    else:
        header.append(127)
        header.extend(length.to_bytes(8, "big"))
    writer.write(bytes(header) + payload)
    await writer.drain()


async def _read_ws_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    header = await reader.readexactly(2)
    opcode = header[0] & 0x0F
    masked = bool(header[1] & 0x80)
    length = header[1] & 0x7F
    if length == 126:
        length = int.from_bytes(await reader.readexactly(2), "big")
    elif length == 127:
        length = int.from_bytes(await reader.readexactly(8), "big")
    mask = await reader.readexactly(4) if masked else b""
    payload = await reader.readexactly(length)
    if masked:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return opcode, payload


class ChatStreamService:
    def __init__(self, *, host: str, bridge_port: int, auth_token: str = "") -> None:
        self.host = host
        self.bridge_port = int(bridge_port)
        self.ws_port = self.bridge_port + 1
        self.http_base = _http_base(host, bridge_port)
        self.ws_base = _ws_base(host, self.ws_port)
        self.auth_token = str(auth_token or "").strip()
        self._sessions: dict[str, _ChatStreamSession] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.base_events.Server | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_error: Exception | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            _stream_debug_log("start skipped reason=already_running")
            return
        _stream_debug_log(f"start requested host={self.host} bridge_port={self.bridge_port} ws_port={self.ws_port}")
        self._ready.clear()
        self._start_error = None
        self._thread = threading.Thread(target=self._run_loop, name="shinsekai-chat-stream", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        if self._start_error is not None:
            _stream_debug_log(f"start failed error_type={self._start_error.__class__.__name__} error={self._start_error}")
            raise self._start_error
        _stream_debug_log(f"start ready thread_alive={self._thread.is_alive() if self._thread else False}")

    def stop(self) -> None:
        loop = self._loop
        if loop is None:
            _stream_debug_log("stop skipped reason=no_loop")
            return
        _stream_debug_log("stop requested")
        try:
            future = asyncio.run_coroutine_threadsafe(self._shutdown_async(), loop)
            future.result(timeout=5.0)
            _stream_debug_log("shutdown_async completed")
        except Exception as exc:
            _stream_debug_log(f"shutdown_async failed error_type={exc.__class__.__name__} error={exc}")
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            _stream_debug_log(f"thread joined alive={self._thread.is_alive()}")
        self._loop = None
        self._thread = None
        self._server = None
        self._ready.clear()
        self._start_error = None

    def create_session(self, initial_snapshot: dict[str, Any] | None = None) -> dict[str, str]:
        session_id = uuid.uuid4().hex
        snapshot = make_empty_chat_snapshot()
        if initial_snapshot:
            snapshot.update(initial_snapshot)
        snapshot["sessionId"] = session_id
        snapshot["wsUrl"] = self.ws_base
        with self._lock:
            self._sessions[session_id] = _ChatStreamSession(session_id=session_id, snapshot=snapshot)
        _stream_debug_log(
            f"session_created session={session_id} snapshot_keys={','.join(sorted(str(key) for key in snapshot.keys()))}"
        )
        producer_endpoint = f"{self.ws_base}?sessionId={quote(session_id)}&role=producer"
        if self.auth_token:
            producer_endpoint = _append_query(
                producer_endpoint,
                {"shinsekai_bridge_token": self.auth_token},
            )
        return {
            "producerEndpoint": producer_endpoint,
            "sessionId": session_id,
            "wsUrl": self.ws_base,
        }

    def get_snapshot(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            return dict(session.snapshot)

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            removed = self._sessions.pop(session_id, None) is not None
        _stream_debug_log(f"session_deleted session={session_id} removed={removed}")

    def wait_for_producer(self, session_id: str, *, timeout: float = 5.0) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                _stream_debug_log(f"producer_wait skipped session={session_id} reason=missing_session")
                return False
            if session.producer is not None:
                _stream_debug_log(f"producer_wait ready session={session_id} reason=already_connected")
                return True
            ready = session.producer_ready
        _stream_debug_log(f"producer_wait start session={session_id} timeout={timeout:.3f}")
        result = ready.wait(timeout=max(float(timeout), 0.0))
        _stream_debug_log(f"producer_wait done session={session_id} ready={result}")
        return result

    def close_session(self, session_id: str, *, reason: str = "聊天会话已结束。") -> None:
        event: dict[str, Any] | None = None
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            event = build_event(session.last_seq + 1, {"type": "session.closed", "reason": reason})
        _stream_debug_log(f"close_session publish session={session_id} reason={reason}")

        loop = self._loop
        if loop is None:
            with self._lock:
                session = self._sessions.get(session_id)
                if session is None or event is None:
                    return
                session.last_seq = max(session.last_seq, int(event.get("seq") or 0))
                session.snapshot = fold_event_into_snapshot(session.snapshot, event)
                session.snapshot["sessionId"] = session_id
                session.snapshot["wsUrl"] = self.ws_base
            return

        future = asyncio.run_coroutine_threadsafe(self._publish_event(session_id, event), loop)
        try:
            future.result(timeout=0.35)
        except Exception as exc:
            _stream_debug_log(
                f"close_session publish fallback session={session_id} error_type={exc.__class__.__name__} error={exc}"
            )
            with self._lock:
                session = self._sessions.get(session_id)
                if session is None:
                    return
                session.last_seq = max(session.last_seq, int(event.get("seq") or 0))
                session.snapshot = fold_event_into_snapshot(session.snapshot, event)
                session.snapshot["sessionId"] = session_id
                session.snapshot["wsUrl"] = self.ws_base

    def update_session_snapshot(self, session_id: str, snapshot: dict[str, Any]) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            next_snapshot = make_empty_chat_snapshot()
            next_snapshot.update(session.snapshot)
            next_snapshot.update(snapshot)
            next_snapshot["sessionId"] = session_id
            next_snapshot["wsUrl"] = self.ws_base
            session.snapshot = next_snapshot
        _stream_debug_log(
            f"session_snapshot_updated session={session_id} keys={','.join(sorted(str(key) for key in snapshot.keys()))}"
        )

    def send_command(self, session_id: str, command: dict[str, Any]) -> bool:
        loop = self._loop
        if loop is None:
            return False
        deadline = time.time() + 2.0
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            if not self.wait_for_producer(session_id, timeout=min(0.25, remaining)):
                continue
            future = asyncio.run_coroutine_threadsafe(self._send_command(session_id, command), loop)
            try:
                if bool(future.result(timeout=0.5)):
                    _stream_debug_log(
                        f"command_sent session={session_id} type={command.get('type', 'unknown')} cmd_id={command.get('cmdId', '')}"
                    )
                    return True
            except Exception as exc:
                _stream_debug_log(
                    f"command_send_failed session={session_id} type={command.get('type', 'unknown')} error_type={exc.__class__.__name__} error={exc}"
                )
            time.sleep(0.1)
        _stream_debug_log(f"command_send_timeout session={session_id} type={command.get('type', 'unknown')}")
        return False

    def media_url(self, raw_path: str) -> str:
        path = str(raw_path or "").strip()
        if not path:
            return ""
        if _is_direct_media_path(path):
            return path
        return _append_query(
            f"{self.http_base}/api/media?path={quote(path)}",
            {"shinsekai_bridge_token": self.auth_token},
        )

    async def _shutdown_async(self) -> None:
        _stream_debug_log("shutdown_async start")
        server = self._server
        if server is not None:
            server.close()
            await server.wait_closed()

        with self._lock:
            sessions = list(self._sessions.values())

        for session in sessions:
            viewers = list(session.viewers)
            producer = session.producer
            for viewer in viewers:
                await viewer.close()
            if producer is not None:
                await producer.close()

        with self._lock:
            for session in self._sessions.values():
                session.viewers.clear()
                session.producer = None
                session.producer_ready.clear()
        _stream_debug_log(f"shutdown_async done sessions={len(sessions)}")

    def _run_loop(self) -> None:
        if sys.platform == "win32":
            default_loop = asyncio.new_event_loop()
            default_loop_type = type(default_loop).__name__
            default_loop.close()
            loop = asyncio.SelectorEventLoop()
            loop_strategy = "selector"
        else:
            loop = asyncio.new_event_loop()
            default_loop_type = type(loop).__name__
            loop_strategy = "default"
        _stream_debug_log(
            f"event_loop_created platform={sys.platform} default_loop_type={default_loop_type} active_loop_type={type(loop).__name__} strategy={loop_strategy}"
        )
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            _stream_debug_log(f"binding ws://{self.host}:{self.ws_port}")
            self._server = loop.run_until_complete(asyncio.start_server(self._handle_client, self.host, self.ws_port))
            _stream_debug_log("server_bound ok")
        except Exception as exc:  # pragma: no cover - startup failure path
            self._start_error = exc
            self._ready.set()
            _stream_debug_log(f"server_bound failed error_type={exc.__class__.__name__} error={exc}")
            return
        self._ready.set()
        _stream_debug_log("run_forever enter")
        try:
            loop.run_forever()
        finally:  # pragma: no cover - shutdown path
            _stream_debug_log("run_forever exit")
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                with contextlib.suppress(Exception):
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            _stream_debug_log(f"event_loop_closed pending_tasks={len(pending)}")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connection: _WebSocketConnection | None = None
        try:
            request_line, headers = await self._read_handshake(reader)
            connection = await self._accept_connection(reader, writer, request_line, headers)
            if connection.role == "viewer":
                await self._send_snapshot(connection)
            await self._receive_loop(connection)
        except asyncio.IncompleteReadError:
            _stream_debug_log("client_disconnected reason=incomplete_read")
        except Exception as exc:
            _stream_debug_log(f"client_error error_type={exc.__class__.__name__} error={exc}")
        finally:
            if connection is not None:
                await self._detach(connection)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _read_handshake(self, reader: asyncio.StreamReader) -> tuple[str, dict[str, str]]:
        raw = await reader.readuntil(b"\r\n\r\n")
        text = raw.decode("utf-8", errors="replace")
        lines = text.split("\r\n")
        request_line = lines[0]
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        return request_line, headers

    async def _accept_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        request_line: str,
        headers: dict[str, str],
    ) -> _WebSocketConnection:
        parts = request_line.split()
        if len(parts) < 2 or parts[0].upper() != "GET":
            raise ValueError("invalid websocket request")
        target = parts[1]
        parsed = urlparse(target)
        query = parse_qs(parsed.query)
        session_id = str((query.get("sessionId") or [""])[0]).strip()
        role = str((query.get("role") or ["viewer"])[0]).strip() or "viewer"
        auth_token = str((query.get("shinsekai_bridge_token") or query.get("token") or [""])[0]).strip()
        if not session_id:
            raise ValueError("missing sessionId")
        if self.auth_token and not hmac.compare_digest(auth_token, self.auth_token):
            raise ValueError("invalid websocket auth token")
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError("unknown session")
        key = headers.get("sec-websocket-key", "")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("utf-8")).digest()
        ).decode("ascii")
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "\r\n"
        ).encode("utf-8")
        writer.write(response)
        await writer.drain()
        connection = _WebSocketConnection(reader=reader, writer=writer, role=role, session_id=session_id)
        old_producer: _WebSocketConnection | None = None
        with self._lock:
            session = self._sessions[session_id]
            if role == "producer":
                if session.producer is not None and session.producer is not connection:
                    old_producer = session.producer
                session.producer = connection
                session.producer_ready.set()
                producer_count = 1
                viewer_count = len(session.viewers)
            else:
                session.viewers.add(connection)
                producer_count = 1 if session.producer is not None else 0
                viewer_count = len(session.viewers)
        _stream_debug_log(f"{role}_connected session={session_id} producers={producer_count} viewers={viewer_count}")
        if old_producer is not None:
            await old_producer.close()
            _stream_debug_log(f"producer_replaced session={session_id}")
        return connection

    async def _receive_loop(self, connection: _WebSocketConnection) -> None:
        while True:
            opcode, payload = await _read_ws_frame(connection.reader)
            if opcode == 0x8:
                return
            if opcode == 0x9:
                async with connection.send_lock:
                    await _send_ws_frame(connection.writer, 0xA, payload)
                continue
            if opcode != 0x1:
                continue
            if connection.role != "producer":
                continue
            event = json.loads(payload.decode("utf-8"))
            if isinstance(event, dict):
                _stream_debug_log(
                    f"producer_event_received session={connection.session_id} type={event.get('type', 'unknown')} seq={event.get('seq', 0)}"
                )
                await self._publish_event(connection.session_id, event)

    async def _publish_event(self, session_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            try:
                session.last_seq = max(session.last_seq, int(event.get("seq") or 0))
            except (TypeError, ValueError):
                pass
            session.snapshot = fold_event_into_snapshot(session.snapshot, event)
            session.snapshot["sessionId"] = session_id
            session.snapshot["wsUrl"] = self.ws_base
            viewers = list(session.viewers)
            event_seq = session.last_seq
        _stream_debug_log(
            f"publish_event session={session_id} type={event.get('type', 'unknown')} seq={event.get('seq', event_seq)} viewers={len(viewers)}"
        )
        stale: list[_WebSocketConnection] = []
        for viewer in viewers:
            try:
                await viewer.send_json(event)
            except Exception as exc:
                _stream_debug_log(
                    f"viewer_send_failed session={session_id} type={event.get('type', 'unknown')} error_type={exc.__class__.__name__} error={exc}"
                )
                stale.append(viewer)
        for viewer in stale:
            await self._detach(viewer)

    async def _send_snapshot(self, connection: _WebSocketConnection) -> None:
        with self._lock:
            session = self._sessions.get(connection.session_id)
            if session is None:
                return
            snapshot = dict(session.snapshot)
            seq = session.last_seq
        _stream_debug_log(f"snapshot_sent session={connection.session_id} seq={seq}")
        await connection.send_json(
            {
                "v": 1,
                "seq": seq,
                "ts": int(time.time() * 1000),
                "type": "snapshot",
                "snapshot": snapshot,
            }
        )

    async def _send_command(self, session_id: str, command: dict[str, Any]) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            producer = session.producer if session is not None else None
        if producer is None:
            return False
        await producer.send_json(
            {
                "v": 1,
                "ts": int(time.time() * 1000),
                "type": "command",
                "command": command,
            }
        )
        return True

    async def _detach(self, connection: _WebSocketConnection) -> None:
        with self._lock:
            session = self._sessions.get(connection.session_id)
            if session is None:
                return
            if connection.role == "producer":
                if session.producer is connection:
                    session.producer = None
                    session.producer_ready.clear()
                    _stream_debug_log(f"producer_detached session={connection.session_id}")
            else:
                session.viewers.discard(connection)
                _stream_debug_log(f"viewer_detached session={connection.session_id} viewers={len(session.viewers)}")
