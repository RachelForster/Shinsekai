from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import secrets
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from sdk.path_contract import (
    runtime_media_reference_is_direct,
    validate_runtime_media_reference,
)
from application.runtime.event_sink import (
    EVENT_PROTOCOL_VERSION,
    build_event,
    fold_event_into_snapshot,
    make_empty_chat_snapshot,
)
from application.runtime.restart_debug import write_restart_debug_log
from frontend_bridge_core.media_paths import (
    is_absolute_local_media_path_text,
    is_supported_media_path_text,
)


def _stream_debug_log(message: str) -> None:
    write_restart_debug_log("chat_stream", message)


_MEDIA_EVENT_TYPES = {
    "background.change",
    "bgm.change",
    "cg.show",
    "effect.loop.start",
    "effect.play",
    "sprite.show",
    "tts.play",
}
_MAX_APPROVED_EXTERNAL_MEDIA_PATHS = 2048
_POLLING_RENDERER_LEASE_SECONDS = 4.0


def _external_host(bind_host: str) -> str:
    host = str(bind_host or "").strip()
    if host in {"", "0.0.0.0", "::", "[::]"}:
        return "127.0.0.1"
    return host


def _http_base(host: str, port: int) -> str:
    return f"http://{_external_host(host)}:{int(port)}"


def _ws_base(host: str, port: int) -> str:
    return f"ws://{_external_host(host)}:{int(port)}/ws"


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
    advertised_ws_url: str = ""
    connected_at: float = field(default_factory=time.time)
    renderer_id: str = ""
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
    producer_token: str = field(
        default_factory=lambda: secrets.token_urlsafe(32),
        repr=False,
    )
    producer: _WebSocketConnection | None = None
    producer_ready: threading.Event = field(default_factory=threading.Event, repr=False)
    renderer_seen_at: dict[str, float] = field(default_factory=dict, repr=False)
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
        self._approved_external_media_paths: dict[str, float] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.base_events.Server | None = None
        self._mobile_server: asyncio.base_events.Server | None = None
        self._mobile_ws_url = ""
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
        self._mobile_server = None
        self._mobile_ws_url = ""
        self._ready.clear()
        self._start_error = None

    def start_mobile_listener(self, advertised_host: str, port: int) -> str:
        loop = self._loop
        if loop is None:
            raise RuntimeError("chat stream service is unavailable")
        host = str(advertised_host or "").strip()
        if not host:
            raise ValueError("advertised mobile host is required")
        websocket_url = f"ws://{host}:{int(port)}/ws"
        future = asyncio.run_coroutine_threadsafe(
            self._start_mobile_listener_async(websocket_url, int(port)),
            loop,
        )
        return str(future.result(timeout=5.0))

    def stop_mobile_listener(self) -> None:
        loop = self._loop
        if loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(
            self._stop_mobile_listener_async(),
            loop,
        )
        try:
            future.result(timeout=5.0)
        except Exception:
            pass

    def create_session(self, initial_snapshot: dict[str, Any] | None = None) -> dict[str, str]:
        session_id = uuid.uuid4().hex
        snapshot = make_empty_chat_snapshot()
        if initial_snapshot:
            snapshot.update(initial_snapshot)
        snapshot["sessionId"] = session_id
        snapshot["wsUrl"] = self.ws_base
        try:
            initial_seq = max(0, int(snapshot.get("eventSeq") or 0))
        except (TypeError, ValueError):
            initial_seq = 0
        snapshot["eventSeq"] = initial_seq
        session = _ChatStreamSession(
            session_id=session_id,
            snapshot=snapshot,
            last_seq=initial_seq,
        )
        with self._lock:
            self._sessions[session_id] = session
        _stream_debug_log(
            f"session_created session={session_id} snapshot_keys={','.join(sorted(str(key) for key in snapshot.keys()))}"
        )
        producer_endpoint = f"{self.ws_base}?sessionId={quote(session_id)}&role=producer"
        producer_endpoint = _append_query(
            producer_endpoint,
            {"shinsekai_producer_token": session.producer_token},
        )
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

    def get_snapshot(
        self,
        session_id: str,
        *,
        renderer_id: str = "",
    ) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if renderer_id:
                self._claim_renderer_locked(session, renderer_id)
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
            try:
                snapshot_seq = max(0, int(next_snapshot.get("eventSeq") or 0))
            except (TypeError, ValueError):
                snapshot_seq = 0
            session.last_seq = max(session.last_seq, snapshot_seq)
            next_snapshot["eventSeq"] = session.last_seq
            session.snapshot = next_snapshot
        _stream_debug_log(
            f"session_snapshot_updated session={session_id} keys={','.join(sorted(str(key) for key in snapshot.keys()))}"
        )

    def publish_event(self, session_id: str, event: dict[str, Any]) -> bool:
        """Publish one trusted bridge-local event to a Chat session."""
        loop = self._loop
        if loop is None:
            return False
        with self._lock:
            if session_id not in self._sessions:
                return False
        local_event = dict(event)
        local_event["v"] = EVENT_PROTOCOL_VERSION
        local_event["ts"] = int(time.time() * 1000)
        future = asyncio.run_coroutine_threadsafe(
            self._publish_event(session_id, local_event),
            loop,
        )
        try:
            future.result(timeout=1.0)
            return True
        except Exception:
            return False

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
        path = validate_runtime_media_reference(raw_path)
        if not path:
            return ""
        if runtime_media_reference_is_direct(path):
            return path
        self.approve_external_media_path(path)
        return _append_query(
            f"{self.http_base}/api/media?path={quote(path)}",
            {"shinsekai_bridge_token": self.auth_token},
        )

    def approve_external_media_path(self, raw_path: str) -> bool:
        try:
            path = validate_runtime_media_reference(
                raw_path,
                allow_empty=False,
            )
        except (TypeError, ValueError):
            return False
        if not (
            is_absolute_local_media_path_text(path)
            and is_supported_media_path_text(path)
        ):
            return False
        with self._lock:
            self._approved_external_media_paths[path] = time.time()
            overflow = (
                len(self._approved_external_media_paths)
                - _MAX_APPROVED_EXTERNAL_MEDIA_PATHS
            )
            if overflow > 0:
                oldest = sorted(
                    self._approved_external_media_paths,
                    key=self._approved_external_media_paths.get,
                )[:overflow]
                for candidate in oldest:
                    self._approved_external_media_paths.pop(candidate, None)
        return True

    def approved_external_media_paths(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._approved_external_media_paths)

    @staticmethod
    def _connected_renderer_ids(session: _ChatStreamSession) -> set[str]:
        return {
            str(getattr(viewer, "renderer_id", "") or "")
            for viewer in session.viewers
            if str(getattr(viewer, "renderer_id", "") or "")
        }

    def _remember_renderer_locked(
        self,
        session: _ChatStreamSession,
        renderer_id: str,
    ) -> str:
        normalized = str(renderer_id or "").strip()[:128]
        if not normalized:
            return ""
        now = time.monotonic()
        session.renderer_seen_at[normalized] = now
        if len(session.renderer_seen_at) > 128:
            stale = sorted(
                session.renderer_seen_at,
                key=session.renderer_seen_at.get,
            )[: len(session.renderer_seen_at) - 128]
            for candidate in stale:
                session.renderer_seen_at.pop(candidate, None)
        return normalized

    def _select_renderer_locked(
        self,
        session: _ChatStreamSession,
        *,
        exclude: str = "",
    ) -> str:
        viewers = sorted(
            (
                viewer
                for viewer in session.viewers
                if str(getattr(viewer, "renderer_id", "") or "")
                and str(getattr(viewer, "renderer_id", "") or "") != exclude
            ),
            key=lambda viewer: (
                bool(getattr(viewer, "advertised_ws_url", "")),
                float(getattr(viewer, "connected_at", 0.0)),
                str(getattr(viewer, "renderer_id", "") or ""),
            ),
        )
        if viewers:
            renderer_id = str(getattr(viewers[0], "renderer_id", "") or "")
            return self._remember_renderer_locked(session, renderer_id)

        cutoff = time.monotonic() - _POLLING_RENDERER_LEASE_SECONDS
        candidates = sorted(
            renderer_id
            for renderer_id, seen_at in session.renderer_seen_at.items()
            if renderer_id != exclude and seen_at >= cutoff
        )
        return candidates[0] if candidates else ""

    def _claim_renderer_locked(
        self,
        session: _ChatStreamSession,
        renderer_id: str,
    ) -> None:
        normalized = self._remember_renderer_locked(session, renderer_id)
        active = session.snapshot.get("activePlayback")
        if not normalized or not isinstance(active, dict):
            return
        owner = str(active.get("rendererId") or "")
        connected = self._connected_renderer_ids(session)
        owner_seen_at = session.renderer_seen_at.get(owner, 0.0)
        owner_is_current = owner in connected or (
            bool(owner)
            and owner_seen_at >= time.monotonic() - _POLLING_RENDERER_LEASE_SECONDS
        )
        if owner_is_current:
            return
        next_active = dict(active)
        next_active["rendererId"] = normalized
        session.snapshot["activePlayback"] = next_active

    def _approve_event_media_path(self, event: dict[str, Any]) -> None:
        if str(event.get("type") or "") not in _MEDIA_EVENT_TYPES:
            return
        media_url = str(event.get("url") or "")
        if not media_url or media_url != media_url.strip():
            return
        parsed = urlparse(media_url)
        if parsed.path != "/api/media":
            return
        query = parse_qs(parsed.query)
        raw_path = str((query.get("path") or [""])[0])
        self.approve_external_media_path(raw_path)

    async def _shutdown_async(self) -> None:
        _stream_debug_log("shutdown_async start")
        await self._stop_mobile_listener_async()
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

    async def _start_mobile_listener_async(self, websocket_url: str, port: int) -> str:
        if self._mobile_server is not None:
            if self._mobile_ws_url == websocket_url:
                return websocket_url
            await self._stop_mobile_listener_async()

        async def handle_mobile_client(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            await self._handle_client(
                reader,
                writer,
                advertised_ws_url=websocket_url,
            )

        server = await asyncio.start_server(handle_mobile_client, "0.0.0.0", port)
        self._mobile_server = server
        self._mobile_ws_url = websocket_url
        return websocket_url

    async def _stop_mobile_listener_async(self) -> None:
        server = self._mobile_server
        self._mobile_server = None
        self._mobile_ws_url = ""
        if server is not None:
            server.close()
            await server.wait_closed()
        with self._lock:
            mobile_viewers = [
                viewer
                for session in self._sessions.values()
                for viewer in session.viewers
                if viewer.advertised_ws_url
            ]
        for viewer in mobile_viewers:
            await viewer.close()
            await self._detach(viewer)

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

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        advertised_ws_url: str = "",
    ) -> None:
        connection: _WebSocketConnection | None = None
        try:
            request_line, headers = await self._read_handshake(reader)
            connection = await self._accept_connection(
                reader,
                writer,
                request_line,
                headers,
                advertised_ws_url=advertised_ws_url,
            )
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
        *,
        advertised_ws_url: str = "",
    ) -> _WebSocketConnection:
        parts = request_line.split()
        if len(parts) < 2 or parts[0].upper() != "GET":
            raise ValueError("invalid websocket request")
        target = parts[1]
        parsed = urlparse(target)
        query = parse_qs(parsed.query)
        session_id = str((query.get("sessionId") or [""])[0]).strip()
        role = str((query.get("role") or ["viewer"])[0]).strip() or "viewer"
        renderer_id = str((query.get("rendererId") or [""])[0]).strip()[:128]
        if role not in {"producer", "viewer"}:
            raise ValueError("invalid websocket role")
        auth_token = str((query.get("shinsekai_bridge_token") or query.get("token") or [""])[0]).strip()
        producer_token = str(
            (query.get("shinsekai_producer_token") or [""])[0]
        ).strip()
        if not session_id:
            raise ValueError("missing sessionId")
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError("unknown session")
            expected_producer_token = session.producer_token
        if role == "producer":
            if not hmac.compare_digest(producer_token, expected_producer_token):
                raise ValueError("invalid websocket producer token")
        elif self.auth_token and not hmac.compare_digest(auth_token, self.auth_token):
            raise ValueError("invalid websocket auth token")
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
        connection = _WebSocketConnection(
            reader=reader,
            writer=writer,
            role=role,
            session_id=session_id,
            advertised_ws_url=advertised_ws_url,
            renderer_id=renderer_id or (uuid.uuid4().hex if role == "viewer" else ""),
        )
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
                self._remember_renderer_locked(session, connection.renderer_id)
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
        self._approve_event_media_path(event)
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            # Producer processes own a local sequence counter that restarts at
            # one after a runtime restart or reconnect. The bridge session is
            # the serialization boundary, so expose one monotonic sequence to
            # viewers instead of forwarding that reset counter. Otherwise the
            # React reducer correctly treats every new event as stale once a
            # newer snapshot has already been hydrated.
            normalized_event = dict(event)
            normalized_event["seq"] = session.last_seq + 1
            if str(normalized_event.get("type") or "") == "tts.play":
                normalized_event["rendererId"] = self._select_renderer_locked(session)
            session.last_seq = int(normalized_event["seq"])
            session.snapshot = fold_event_into_snapshot(session.snapshot, normalized_event)
            session.snapshot["sessionId"] = session_id
            session.snapshot["wsUrl"] = self.ws_base
            viewers = list(session.viewers)
            event_seq = session.last_seq
        _stream_debug_log(
            f"publish_event session={session_id} type={event.get('type', 'unknown')} seq={event_seq} viewers={len(viewers)}"
        )
        stale: list[_WebSocketConnection] = []
        for viewer in viewers:
            try:
                await viewer.send_json(normalized_event)
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
            self._claim_renderer_locked(session, connection.renderer_id)
            snapshot = dict(session.snapshot)
            seq = session.last_seq
        if connection.advertised_ws_url:
            snapshot["wsUrl"] = connection.advertised_ws_url
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
            if session is not None and str(command.get("type") or "") == "audio-playback-signal":
                payload = command.get("payload")
                active = session.snapshot.get("activePlayback")
                if not isinstance(payload, dict) or not isinstance(active, dict):
                    return False
                renderer_id = self._remember_renderer_locked(
                    session,
                    str(payload.get("rendererId") or ""),
                )
                if (
                    not renderer_id
                    or renderer_id != str(active.get("rendererId") or "")
                    or str(payload.get("playbackId") or "")
                    != str(active.get("playbackId") or "")
                ):
                    return False
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
        if str(command.get("type") or "") == "audio-playback-signal":
            payload = command.get("payload")
            state = str(payload.get("state") or "") if isinstance(payload, dict) else ""
            if state in {"failed", "finished", "interrupted"}:
                with self._lock:
                    session = self._sessions.get(session_id)
                    active = session.snapshot.get("activePlayback") if session is not None else None
                    if (
                        session is not None
                        and isinstance(active, dict)
                        and str(active.get("playbackId") or "")
                        == str(payload.get("playbackId") or "")
                        and str(active.get("rendererId") or "")
                        == str(payload.get("rendererId") or "")
                    ):
                        session.snapshot["activePlayback"] = None
        return True

    async def _detach(self, connection: _WebSocketConnection) -> None:
        replacement: _WebSocketConnection | None = None
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
                renderer_id = str(getattr(connection, "renderer_id", "") or "")
                session.renderer_seen_at.pop(renderer_id, None)
                active = session.snapshot.get("activePlayback")
                if (
                    renderer_id
                    and isinstance(active, dict)
                    and str(active.get("rendererId") or "") == renderer_id
                ):
                    next_renderer_id = self._select_renderer_locked(
                        session,
                        exclude=renderer_id,
                    )
                    next_active = dict(active)
                    next_active["rendererId"] = next_renderer_id
                    session.snapshot["activePlayback"] = next_active
                    replacement = next(
                        (
                            viewer
                            for viewer in session.viewers
                            if str(getattr(viewer, "renderer_id", "") or "")
                            == next_renderer_id
                        ),
                        None,
                    )
                _stream_debug_log(
                    f"viewer_detached session={connection.session_id} viewers={len(session.viewers)}"
                )
        if replacement is not None:
            try:
                await self._send_snapshot(replacement)
            except Exception:
                await self._detach(replacement)
