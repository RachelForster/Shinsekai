"""chat stage 实时事件发射器（M0 占位骨架）。

设计文档《chat_ui_react_migration_and_theme_system.md》"参考接口输出 · D"。

``ChatEventSink`` 是演出输出的抽象出口：``StreamingUIUpdateManager``（见
``core/runtime/ui_update_manager.py``）把每次 UI 更新调用翻译成一个事件 dict 并
``emit`` 到 sink；sink 负责补 ``seq``/``ts`` 并扇出到所有 WebSocket viewer。

M0 仅提供契约 + ``NullEventSink``（丢弃）+ ``WSClientSink``（连回 bridge 的占位）。
真实 WS 连接与重连重放在 M2 补全。
"""

from __future__ import annotations

import base64
import collections
import itertools
import json
import math
import os
import re
import secrets
import socket
import threading
import time
from collections.abc import Callable
from urllib.parse import parse_qs, quote, urlparse
from typing import Any, Dict, List, Protocol, runtime_checkable

#: 事件协议版本，与前端 ``ChatStageEvent`` 的 ``v`` 字段一致。
EVENT_PROTOCOL_VERSION = 1


def _strip_html(value: str) -> str:
    return (
        re.sub(r"<br\s*/?>", "\n", value or "", flags=re.IGNORECASE)
        .replace("</p>", "\n")
        .replace("</div>", "\n")
        .replace("</li>", "\n")
    )


def _plain_text(value: str) -> str:
    return re.sub(r"<[^>]+>", "", _strip_html(value or "")).strip()


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


def make_empty_chat_snapshot() -> Dict[str, Any]:
    return {
        "dialogText": "",
        "eventSeq": 0,
        "historyEntries": [],
        "inputDraft": "",
        "options": [],
        "sprites": [],
        "stats": [],
        "status": "idle",
        "systemMessageText": "",
        "turnState": {
            "enabled": False,
            "pendingCount": 0,
            "remainingSeconds": None,
            "scheduled": False,
            "typing": False,
        },
        "userDisplayName": "你",
    }


def _clear_transient_notification_state(next_snapshot: Dict[str, Any]) -> None:
    if "notificationText" in next_snapshot:
        next_snapshot["notificationText"] = ""
    if "sessionClosedReason" in next_snapshot:
        next_snapshot["sessionClosedReason"] = ""


_CHAT_INIT_TASK_TEXT_FIELDS = (
    "error",
    "errorCode",
    "errorDetail",
    "errorUserMessage",
    "id",
    "kind",
    "message",
    "notice",
    "noticeKind",
    "phase",
    "title",
)


def _fold_chat_init_task(
    current: Any,
    raw_task: Any,
    *,
    event_type: str,
) -> Dict[str, Any]:
    task = dict(current) if isinstance(current, dict) else {}
    payload = raw_task if isinstance(raw_task, dict) else {}

    for field in _CHAT_INIT_TASK_TEXT_FIELDS:
        if field in payload:
            task[field] = str(payload.get(field) or "")[:4000]
    for field in ("createdAt", "httpStatus", "updatedAt"):
        value = payload.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            task[field] = value

    if "progress" in payload:
        progress = payload.get("progress")
        if progress is None:
            task["progress"] = None
        elif isinstance(progress, (int, float)) and not isinstance(progress, bool):
            task["progress"] = max(0.0, min(1.0, float(progress)))

    raw_logs = payload.get("logs")
    if isinstance(raw_logs, list):
        task["logs"] = [str(line)[:4000] for line in raw_logs[-120:] if str(line).strip()]
    if "cancelRequested" in payload:
        task["cancelRequested"] = bool(payload.get("cancelRequested"))

    status_by_event = {
        "chat.init.progress": "running",
        "chat.init.completed": "succeeded",
        "chat.init.failed": "failed",
        "chat.init.cancelled": "cancelled",
    }
    task["status"] = status_by_event[event_type]
    if event_type == "chat.init.completed":
        task["progress"] = 1.0
    return task


def fold_event_into_snapshot(snapshot: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
    """Fold one chat stage event into a ChatSnapshot-like dict."""
    event_type = str(event.get("type") or "").strip()
    next_snapshot = dict(snapshot or make_empty_chat_snapshot())
    next_snapshot.setdefault("dialogText", "")
    next_snapshot.setdefault("eventSeq", 0)
    next_snapshot.setdefault("historyEntries", [])
    next_snapshot.setdefault("inputDraft", "")
    next_snapshot.setdefault("options", [])
    next_snapshot.setdefault("sprites", [])
    next_snapshot.setdefault("stats", [])
    next_snapshot.setdefault("status", "idle")

    if event_type == "snapshot":
        payload = event.get("snapshot")
        if isinstance(payload, dict):
            merged = make_empty_chat_snapshot()
            merged.update(payload)
            if "eventSeq" not in merged:
                try:
                    merged["eventSeq"] = int(event.get("seq") or 0)
                except (TypeError, ValueError):
                    merged["eventSeq"] = 0
            return merged
        return next_snapshot

    try:
        next_snapshot["eventSeq"] = max(int(next_snapshot.get("eventSeq") or 0), int(event.get("seq") or 0))
    except (TypeError, ValueError):
        pass

    if event_type in {
        "chat.init.progress",
        "chat.init.completed",
        "chat.init.failed",
        "chat.init.cancelled",
    }:
        next_snapshot["initTask"] = _fold_chat_init_task(
            next_snapshot.get("initTask"),
            event.get("task"),
            event_type=event_type,
        )
        return next_snapshot

    if event_type == "dialog.end":
        _clear_transient_notification_state(next_snapshot)
        full_html = str(event.get("fullHtml") or "")
        next_snapshot["dialogHtml"] = full_html
        next_snapshot["dialogText"] = _plain_text(full_html)
        is_speakerless_system = bool(event.get("isSystem")) and not str(event.get("speaker") or "").strip()
        if is_speakerless_system:
            next_snapshot["characterName"] = ""
            next_snapshot["systemMessageText"] = _plain_text(full_html)
        else:
            next_snapshot["characterName"] = (
                "" if bool(event.get("isSystem")) else str(event.get("speaker") or "")
            )
            next_snapshot["systemMessageText"] = ""
        if str(event.get("speaker") or "").strip() or not bool(event.get("isSystem")):
            next_snapshot["options"] = []
        return next_snapshot

    if event_type == "user.display_name.change":
        name = str(event.get("name") or "").strip()
        if name:
            next_snapshot["userDisplayName"] = name
        return next_snapshot

    if event_type == "sprite.show":
        _clear_transient_notification_state(next_snapshot)
        character_name = str(event.get("characterName") or "")
        slot = event.get("slot")
        sprite_id = f"{character_name}:{slot}" if slot is not None else character_name
        current = [dict(item) for item in (next_snapshot.get("sprites") or []) if isinstance(item, dict)]
        current = [
            item
            for item in current
            if item.get("id") != sprite_id
            and item.get("label") != character_name
            and item.get("characterName") != character_name
            and (slot is None or item.get("slot") != slot)
        ]
        next_sprite = {
            "id": sprite_id,
            "label": character_name,
            "path": str(event.get("url") or ""),
            "characterName": character_name,
            "scale": event.get("scale"),
            "slot": slot,
        }
        for axis in ("x", "y"):
            if event.get(axis) is not None:
                next_sprite[axis] = event.get(axis)
        current.append(next_sprite)
        next_snapshot["sprites"] = current
        return next_snapshot

    if event_type == "sprite.remove":
        character_name = str(event.get("characterName") or "")
        next_snapshot["sprites"] = [
            item
            for item in (next_snapshot.get("sprites") or [])
            if isinstance(item, dict)
            and item.get("id") != character_name
            and item.get("label") != character_name
            and item.get("characterName") != character_name
        ]
        return next_snapshot

    if event_type == "background.change":
        _clear_transient_notification_state(next_snapshot)
        next_snapshot["backgroundPath"] = str(event.get("url") or "")
        return next_snapshot

    if event_type == "bgm.change":
        next_snapshot["bgmPath"] = str(event.get("url") or "")
        return next_snapshot

    if event_type == "cg.show":
        _clear_transient_notification_state(next_snapshot)
        next_snapshot["cgPath"] = str(event.get("url") or "")
        return next_snapshot

    if event_type == "cg.hide":
        next_snapshot["cgPath"] = ""
        return next_snapshot

    if event_type == "options.show":
        _clear_transient_notification_state(next_snapshot)
        next_snapshot["options"] = [str(item) for item in (event.get("options") or [])]
        return next_snapshot

    if event_type == "options.clear":
        next_snapshot["options"] = []
        return next_snapshot

    if event_type == "history.replace":
        next_snapshot["historyEntries"] = [
            dict(item) for item in (event.get("entries") or []) if isinstance(item, dict)
        ]
        return next_snapshot

    if event_type == "conversation.tree":
        tree = event.get("tree")
        if isinstance(tree, dict):
            next_snapshot["conversationTree"] = dict(tree)
        return next_snapshot

    if event_type == "chat.turn.state":
        state = event.get("state")
        if isinstance(state, dict):
            remaining = state.get("remainingSeconds")
            next_snapshot["turnState"] = {
                "enabled": bool(state.get("enabled")),
                "pendingCount": max(0, int(state.get("pendingCount") or 0)),
                "remainingSeconds": (
                    max(0, int(remaining))
                    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool)
                    else None
                ),
                "scheduled": bool(state.get("scheduled")),
                "typing": bool(state.get("typing")),
            }
        return next_snapshot

    if event_type == "numeric.update":
        next_snapshot["numericInfo"] = _plain_text(str(event.get("html") or ""))
        return next_snapshot

    if event_type == "stats.update":
        stats: list[dict[str, Any]] = []
        for item in event.get("stats") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            value = item.get("value")
            if (
                not label
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
            ):
                continue
            if not math.isfinite(float(value)):
                continue
            stat: dict[str, Any] = {
                "icon": str(item.get("icon") or "gauge"),
                "label": label,
                "value": value,
            }
            maximum = item.get("max")
            if (
                not isinstance(maximum, bool)
                and isinstance(maximum, (int, float))
                and math.isfinite(float(maximum))
                and maximum > 0
            ):
                stat["max"] = maximum
            stats.append(stat)
        next_snapshot["stats"] = stats
        return next_snapshot

    if event_type == "busy.show":
        next_snapshot["busyText"] = str(event.get("text") or "")
        next_snapshot["busyDurationSeconds"] = float(event.get("durationSeconds") or 0.0)
        return next_snapshot

    if event_type == "busy.hide":
        next_snapshot["busyText"] = ""
        next_snapshot["busyDurationSeconds"] = 0.0
        return next_snapshot

    if event_type == "notification.change":
        next_snapshot["notificationText"] = str(event.get("text") or "")
        return next_snapshot

    if event_type == "status.change":
        _clear_transient_notification_state(next_snapshot)
        next_snapshot["status"] = str(event.get("status") or "idle")
        return next_snapshot

    if event_type == "tts.play":
        _clear_transient_notification_state(next_snapshot)
        next_snapshot["status"] = "speaking"
        next_snapshot["characterName"] = str(event.get("characterName") or "")
        return next_snapshot

    if event_type == "tts.skip":
        if str(next_snapshot.get("status") or "") == "speaking":
            next_snapshot["status"] = "idle"
        return next_snapshot

    if event_type == "asr.partial":
        _clear_transient_notification_state(next_snapshot)
        next_snapshot["inputDraft"] = str(event.get("text") or "")
        next_snapshot["status"] = "listening"
        return next_snapshot

    if event_type == "asr.final":
        _clear_transient_notification_state(next_snapshot)
        next_snapshot["inputDraft"] = str(event.get("text") or "")
        return next_snapshot

    if event_type == "asr.state":
        _clear_transient_notification_state(next_snapshot)
        next_snapshot["status"] = "listening" if bool(event.get("running")) else "paused"
        return next_snapshot

    if event_type == "reply.finished":
        _clear_transient_notification_state(next_snapshot)
        next_snapshot["status"] = "idle"
        return next_snapshot

    if event_type == "session.closed":
        next_snapshot["busyText"] = ""
        next_snapshot["busyDurationSeconds"] = 0.0
        next_snapshot["notificationText"] = str(event.get("reason") or "")
        next_snapshot["options"] = []
        next_snapshot["sessionClosedReason"] = str(event.get("reason") or "")
        next_snapshot["status"] = "idle"
        next_snapshot["systemMessageText"] = ""
        return next_snapshot

    return next_snapshot


@runtime_checkable
class ChatEventSink(Protocol):
    """演出事件出口契约。"""

    def emit(self, payload: Dict[str, Any]) -> None:
        """发送一个事件。

        ``payload`` 是业务字段（至少含 ``type``），实现负责补信封 ``v``/``seq``/``ts``
        （见 ``build_event``）。
        """
        ...

    def snapshot(self) -> Dict[str, Any]:
        """返回累积的舞台全量状态，供新连接/重连的 viewer 首帧 hydrate。"""
        ...


def build_event(seq: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    """把业务字段组装成带信封（v/seq/ts）的完整事件。

    ``payload`` 至少包含 ``type``，其余为该事件类型的字段。
    """
    event = {
        "v": EVENT_PROTOCOL_VERSION,
        "seq": seq,
        "ts": int(time.time() * 1000),
    }
    event.update(payload)
    return event


class _BaseEventSink:
    """共享 seq 计数 + 最新快照累积的基类。"""

    def __init__(self) -> None:
        self._seq = itertools.count(1)
        self._snapshot: Dict[str, Any] = make_empty_chat_snapshot()

    def _next(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return build_event(next(self._seq), payload)

    def _remember(self, event: Dict[str, Any]) -> None:
        """把事件折叠进快照，便于 ``snapshot()`` 给新 viewer。"""
        self._snapshot = fold_event_into_snapshot(self._snapshot, event)

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._snapshot)


class NullEventSink(_BaseEventSink):
    """丢弃所有事件的 sink（无 stream 端点时的默认实现，等价 headless）。"""

    def emit(self, payload: Dict[str, Any]) -> None:
        self._remember(self._next(payload))


class WSClientSink(_BaseEventSink):
    """连回 bridge WebSocket server 的生产者 sink（M0 占位）。

    真实实现（M2）：以 ``role=producer`` 连接 ``endpoint``，把 ``emit`` 的事件序列化
    后发送；断线重连；连接前的事件入队缓冲。当前仅缓存事件、不建立连接。
    """

    def __init__(self, endpoint: str) -> None:
        super().__init__()
        self.endpoint = endpoint
        self._buffer: collections.deque[Dict[str, Any]] = collections.deque()
        self._buffer_lock = threading.Lock()
        self._buffer_ready = threading.Event()
        self._command_handler: Callable[[Dict[str, Any]], None] | None = None
        self._closed = False
        self._reader_started = False
        self._reader_lock = threading.Lock()
        self._worker_started = False
        self._worker_lock = threading.Lock()
        self._socket: socket.socket | None = None

    def emit(self, payload: Dict[str, Any]) -> None:
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
        auth_token = str((query.get("shinsekai_bridge_token") or query.get("token") or [""])[0]).strip()
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

    def set_command_handler(self, handler: Callable[[Dict[str, Any]], None] | None) -> None:
        self._command_handler = handler

    def _ensure_worker(self) -> None:
        with self._worker_lock:
            if self._worker_started:
                return
            thread = threading.Thread(target=self._run, name="shinsekai-chat-ws-sink", daemon=True)
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

    def _peek_event(self) -> Dict[str, Any] | None:
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
        status_line = response.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
        if "101" not in status_line:
            raise ConnectionError(f"unexpected websocket handshake response: {status_line}")
        return sock

    def _send_event(self, event: Dict[str, Any]) -> None:
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

    def _dispatch_command(self, command: Dict[str, Any]) -> None:
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
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    @staticmethod
    def _send_control_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
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
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
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
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        sock.sendall(bytes(header) + mask + masked)
