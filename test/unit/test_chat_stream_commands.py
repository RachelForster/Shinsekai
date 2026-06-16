import asyncio
import base64
import json
import socket
import threading
import time
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlparse

from frontend_bridge_core.chat import _handle_chat_command
from frontend_bridge_core.chat_stream import ChatStreamService
from core.runtime.event_sink import WSClientSink


class _StubChatStream:
    def __init__(self):
        self.command = None
        self.snapshot = {
            "dialogText": "",
            "inputDraft": "",
            "options": [],
            "sessionId": "session-1",
            "sprites": [],
            "status": "idle",
            "wsUrl": "ws://127.0.0.1:8788/ws",
        }

    def send_command(self, session_id: str, command: dict):
        self.command = (session_id, dict(command))
        return True

    def update_session_snapshot(self, session_id: str, snapshot: dict):
        self.snapshot.update(snapshot)
        self.snapshot["sessionId"] = session_id

    def get_snapshot(self, session_id: str):
        if session_id != "session-1":
            return None
        return dict(self.snapshot)


class _FakeConnection:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(dict(payload))


def _free_bridge_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1] - 1


def _open_ws(url: str, *, session_id: str, role: str) -> socket.socket:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/ws"
    query = parse_qs(parsed.query)
    query["sessionId"] = [session_id]
    query["role"] = [role]
    target = f"{path}?{urlencode({key: values[-1] for key, values in query.items()})}"
    key = base64.b64encode(b"test-key-123456").decode("ascii")
    request = (
        f"GET {target} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    ).encode("utf-8")
    sock = socket.create_connection((host, port), timeout=5.0)
    sock.settimeout(5.0)
    sock.sendall(request)
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("websocket handshake failed")
        response += chunk
    status_line = response.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
    if "101" not in status_line:
        raise ConnectionError(f"unexpected websocket handshake response: {status_line}")
    return sock


def _read_event(sock: socket.socket) -> dict:
    opcode, payload = WSClientSink._read_frame(sock)
    if opcode == 0x8:
        raise ConnectionError("websocket closed")
    return json.loads(payload.decode("utf-8"))


def _wait_for_event(sock: socket.socket, predicate, *, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        event = _read_event(sock)
        if predicate(event):
            return event
    raise AssertionError("timed out waiting for websocket event")


def _wait_until(predicate, *, timeout: float = 5.0, interval: float = 0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("timed out waiting for condition")


def _wait_for_socket_close(sock: socket.socket, *, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            _read_event(sock)
        except (ConnectionError, OSError, TimeoutError, socket.timeout):
            return
    raise AssertionError("timed out waiting for websocket close")


def _close_ws(sock: socket.socket) -> None:
    try:
        WSClientSink._send_control_frame(sock, 0x8, b"")
    except Exception:
        pass
    try:
        sock.close()
    except OSError:
        pass


def _send_json_frame(sock: socket.socket, payload: dict) -> None:
    WSClientSink._send_frame(sock, json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class ChatStreamCommandTests(unittest.TestCase):
    def test_handle_chat_command_wraps_resume_asr_with_cmd_id(self):
        chat_stream = _StubChatStream()
        state = SimpleNamespace(chat_session={"sessionId": "session-1"}, chat_stream=chat_stream)

        snapshot = _handle_chat_command(state, {"type": "resume-asr"})

        self.assertEqual(snapshot["status"], "listening")
        self.assertEqual(snapshot["dialogText"], "语音识别已恢复。")
        self.assertIsNotNone(chat_stream.command)
        session_id, command = chat_stream.command
        self.assertEqual(session_id, "session-1")
        self.assertEqual(command["type"], "resume-asr")
        self.assertIsInstance(command["cmdId"], str)
        self.assertTrue(command["cmdId"])

    def test_handle_chat_command_wraps_dialog_advance_without_clobbering_dialog_text(self):
        chat_stream = _StubChatStream()
        chat_stream.snapshot["dialogText"] = "Current line"
        chat_stream.snapshot["dialogHtml"] = "<p>Current line</p>"
        chat_stream.snapshot["characterName"] = "Mio"
        state = SimpleNamespace(chat_session={"sessionId": "session-1"}, chat_stream=chat_stream)

        snapshot = _handle_chat_command(state, {"type": "dialog-advance"})

        self.assertEqual(snapshot["status"], "idle")
        self.assertEqual(snapshot["dialogText"], "Current line")
        self.assertIsNotNone(chat_stream.command)
        session_id, command = chat_stream.command
        self.assertEqual(session_id, "session-1")
        self.assertEqual(command["type"], "dialog-advance")
        self.assertIsInstance(command["cmdId"], str)
        self.assertTrue(command["cmdId"])

    def test_handle_chat_command_replaces_stale_dialog_html_when_returning_status_text(self):
        chat_stream = _StubChatStream()
        chat_stream.snapshot["dialogHtml"] = "<p>Old rendered line</p>"
        chat_stream.snapshot["dialogText"] = "Old rendered line"
        chat_stream.snapshot["characterName"] = "Nanami"
        state = SimpleNamespace(chat_session={"sessionId": "session-1"}, chat_stream=chat_stream)

        snapshot = _handle_chat_command(state, {"payload": "hello", "type": "send-message"})

        self.assertEqual(snapshot["status"], "generating")
        self.assertEqual(snapshot["dialogText"], "hello")
        self.assertEqual(snapshot["inputDraft"], "")
        self.assertNotIn("dialogHtml", snapshot)
        self.assertEqual(snapshot["characterName"], "你")
        self.assertEqual(chat_stream.snapshot["dialogText"], "hello")
        self.assertEqual(chat_stream.snapshot["inputDraft"], "")
        self.assertIsNone(chat_stream.snapshot["dialogHtml"])
        self.assertEqual(chat_stream.snapshot["characterName"], "你")

    def test_handle_chat_command_updates_voice_language_for_runtime_session(self):
        chat_stream = _StubChatStream()
        state = SimpleNamespace(
            chat_session={"sessionId": "session-1", "voiceLanguage": "ja"},
            chat_stream=chat_stream,
        )

        snapshot = _handle_chat_command(state, {"payload": "en", "type": "change-voice-language"})

        self.assertEqual(snapshot["status"], "idle")
        self.assertEqual(snapshot["voiceLanguage"], "en")
        self.assertEqual(state.chat_session["voiceLanguage"], "en")
        self.assertIsNotNone(chat_stream.command)
        session_id, command = chat_stream.command
        self.assertEqual(session_id, "session-1")
        self.assertEqual(command["type"], "change-voice-language")
        self.assertEqual(command["payload"], "en")
        self.assertIsInstance(command["cmdId"], str)
        self.assertTrue(command["cmdId"])

    def test_handle_chat_command_clears_closed_session_markers_when_restarting_runtime_interaction(self):
        chat_stream = _StubChatStream()
        chat_stream.snapshot["notificationText"] = "聊天会话已结束。"
        chat_stream.snapshot["sessionClosedReason"] = "聊天会话已结束。"
        state = SimpleNamespace(chat_session={"sessionId": "session-1"}, chat_stream=chat_stream)

        snapshot = _handle_chat_command(state, {"payload": "hello again", "type": "send-message"})

        self.assertEqual(snapshot["status"], "generating")
        self.assertEqual(snapshot["dialogText"], "hello again")
        self.assertEqual(snapshot["characterName"], "你")
        self.assertEqual(snapshot["sessionClosedReason"], "")
        self.assertEqual(snapshot["notificationText"], "")
        self.assertEqual(chat_stream.snapshot["sessionClosedReason"], "")
        self.assertEqual(chat_stream.snapshot["notificationText"], "")

    def test_handle_chat_command_wraps_revert_history_with_cmd_id(self):
        chat_stream = _StubChatStream()
        state = SimpleNamespace(chat_session={"sessionId": "session-1"}, chat_stream=chat_stream)

        snapshot = _handle_chat_command(state, {"payload": 1, "type": "revert-history"})

        self.assertEqual(snapshot["status"], "idle")
        self.assertIsNotNone(chat_stream.command)
        session_id, command = chat_stream.command
        self.assertEqual(session_id, "session-1")
        self.assertEqual(command["type"], "revert-history")
        self.assertEqual(command["payload"], 1)
        self.assertIsInstance(command["cmdId"], str)
        self.assertTrue(command["cmdId"])

    def test_handle_chat_command_wraps_fork_history_with_cmd_id(self):
        chat_stream = _StubChatStream()
        state = SimpleNamespace(chat_session={"sessionId": "session-1"}, chat_stream=chat_stream)

        snapshot = _handle_chat_command(state, {"payload": {"userIndex": 2}, "type": "fork-history"})

        self.assertEqual(snapshot["status"], "generating")
        self.assertEqual(snapshot["dialogText"], "正在创建对话分支。")
        self.assertIsNotNone(chat_stream.command)
        session_id, command = chat_stream.command
        self.assertEqual(session_id, "session-1")
        self.assertEqual(command["type"], "fork-history")
        self.assertEqual(command["payload"], {"userIndex": 2})
        self.assertIsInstance(command["cmdId"], str)
        self.assertTrue(command["cmdId"])

    def test_handle_chat_command_wraps_switch_branch_with_cmd_id(self):
        chat_stream = _StubChatStream()
        state = SimpleNamespace(chat_session={"sessionId": "session-1"}, chat_stream=chat_stream)

        snapshot = _handle_chat_command(state, {"payload": "branch-2", "type": "switch-branch"})

        self.assertEqual(snapshot["status"], "idle")
        self.assertEqual(snapshot["dialogText"], "已切换对话分支。")
        self.assertIsNotNone(chat_stream.command)
        session_id, command = chat_stream.command
        self.assertEqual(session_id, "session-1")
        self.assertEqual(command["type"], "switch-branch")
        self.assertEqual(command["payload"], "branch-2")
        self.assertIsInstance(command["cmdId"], str)
        self.assertTrue(command["cmdId"])

    def test_handle_chat_command_wraps_rename_branch_with_cmd_id(self):
        chat_stream = _StubChatStream()
        state = SimpleNamespace(chat_session={"sessionId": "session-1"}, chat_stream=chat_stream)

        snapshot = _handle_chat_command(
            state,
            {"payload": {"branchId": "branch-2", "label": "Side route"}, "type": "rename-branch"},
        )

        self.assertEqual(snapshot["status"], "idle")
        self.assertEqual(snapshot["dialogText"], "已重命名对话分支。")
        self.assertIsNotNone(chat_stream.command)
        session_id, command = chat_stream.command
        self.assertEqual(session_id, "session-1")
        self.assertEqual(command["type"], "rename-branch")
        self.assertEqual(command["payload"], {"branchId": "branch-2", "label": "Side route"})
        self.assertIsInstance(command["cmdId"], str)
        self.assertTrue(command["cmdId"])

    def test_handle_chat_command_clear_history_removes_directory_storage_without_runtime_stream(self):
        class _Config:
            characters = []
            background_list = []
            system_config = SimpleNamespace(chat_ui_runtime_mode="react", voice_language="ja")

        config_manager = SimpleNamespace(
            config=_Config(),
            get_background_by_name=lambda _name: None,
            get_character_by_name=lambda _name: None,
        )

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
            history_path = Path(tmp_dir) / "session-history"
            history_path.mkdir()
            (history_path / "active.json").write_text("[]", encoding="utf-8")
            (history_path / "branches.json").write_text("{}", encoding="utf-8")
            state = SimpleNamespace(
                chat_session={"historyPath": history_path.as_posix()},
                chat_stream=None,
                config_manager=config_manager,
            )

            snapshot = _handle_chat_command(state, {"type": "clear-history"})

            self.assertFalse(history_path.exists())
            self.assertEqual(snapshot["historyEntries"], [])
            self.assertEqual(snapshot["options"], [])
            self.assertEqual(snapshot["dialogText"], "历史记录已经清空。")

    def test_chat_stream_sends_commands_and_broadcasts_ack_events(self):
        service = ChatStreamService(host="127.0.0.1", bridge_port=8787)
        session = service.create_session()
        producer = _FakeConnection()
        viewer = _FakeConnection()
        with service._lock:
            runtime_session = service._sessions[session["sessionId"]]
            runtime_session.producer = producer
            runtime_session.viewers.add(viewer)

        sent = asyncio.run(service._send_command(session["sessionId"], {"cmdId": "cmd-1", "type": "resume-asr"}))
        self.assertTrue(sent)
        self.assertEqual(len(producer.messages), 1)
        self.assertEqual(
            producer.messages[0]["command"],
            {"cmdId": "cmd-1", "type": "resume-asr"},
        )
        self.assertEqual(producer.messages[0]["type"], "command")

        asyncio.run(
            service._publish_event(
                session["sessionId"],
                {"type": "cmd.ack", "cmdId": "cmd-1", "commandType": "resume-asr", "ok": True},
            )
        )

        self.assertEqual(len(viewer.messages), 1)
        self.assertEqual(
            viewer.messages[0],
            {"type": "cmd.ack", "cmdId": "cmd-1", "commandType": "resume-asr", "ok": True},
        )
        snapshot = service.get_snapshot(session["sessionId"])
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["sessionId"], session["sessionId"])

    def test_chat_stream_close_session_broadcasts_closed_event_and_updates_snapshot(self):
        service = ChatStreamService(host="127.0.0.1", bridge_port=8787)
        session = service.create_session()
        viewer = _FakeConnection()
        with service._lock:
            runtime_session = service._sessions[session["sessionId"]]
            runtime_session.viewers.add(viewer)

        class _ImmediateFuture:
            def __init__(self, result):
                self._result = result

            def result(self, timeout=None):
                return self._result

        def run_now(coro, _loop):
            return _ImmediateFuture(asyncio.run(coro))

        service._loop = object()  # type: ignore[assignment]
        with patch("frontend_bridge_core.chat_stream.asyncio.run_coroutine_threadsafe", side_effect=run_now):
            service.close_session(session["sessionId"], reason="closing for test")

        self.assertEqual(len(viewer.messages), 1)
        self.assertEqual(viewer.messages[0]["type"], "session.closed")
        self.assertEqual(viewer.messages[0]["reason"], "closing for test")
        snapshot = service.get_snapshot(session["sessionId"])
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["sessionClosedReason"], "closing for test")
        self.assertEqual(snapshot["status"], "idle")

    def test_chat_stream_requires_auth_token_for_websocket_clients(self):
        service = ChatStreamService(host="127.0.0.1", bridge_port=_free_bridge_port(), auth_token="bridge-secret")
        service.start()
        producer = None
        try:
            session = service.create_session()

            self.assertIn("shinsekai_bridge_token=bridge-secret", session["producerEndpoint"])
            self.assertIn(
                "shinsekai_bridge_token=bridge-secret",
                service.media_url("data/speech/nanami/hello.wav"),
            )
            with self.assertRaises(ConnectionError):
                _open_ws(session["wsUrl"], session_id=session["sessionId"], role="viewer")

            producer = _open_ws(session["producerEndpoint"], session_id=session["sessionId"], role="producer")
            self.assertIsNotNone(producer)
        finally:
            if producer is not None:
                _close_ws(producer)
            service.stop()

    def test_ws_client_sink_transports_events_over_real_socket(self):
        service = ChatStreamService(host="127.0.0.1", bridge_port=_free_bridge_port())
        service.start()
        try:
            session = service.create_session({"dialogText": "boot"})
            sink = WSClientSink(session["producerEndpoint"])
            viewer = _open_ws(session["wsUrl"], session_id=session["sessionId"], role="viewer")
            try:
                snapshot_event = _wait_for_event(viewer, lambda event: event.get("type") == "snapshot")
                self.assertEqual(snapshot_event["snapshot"]["dialogText"], "boot")

                sink.emit({"type": "notification.change", "text": "connected"})
                _wait_until(lambda: service.get_snapshot(session["sessionId"]).get("notificationText") == "connected")
                notify_event = _wait_for_event(viewer, lambda event: event.get("type") == "notification.change")
                self.assertEqual(notify_event["text"], "connected")
            finally:
                sink.close()
                _close_ws(viewer)
        finally:
            service.stop()

    def test_chat_stream_command_roundtrip_over_real_socket(self):
        service = ChatStreamService(host="127.0.0.1", bridge_port=_free_bridge_port())
        service.start()
        try:
            session = service.create_session({"dialogText": "boot"})
            producer = _open_ws(session["wsUrl"], session_id=session["sessionId"], role="producer")
            viewer = _open_ws(session["wsUrl"], session_id=session["sessionId"], role="viewer")
            try:
                snapshot_event = _wait_for_event(viewer, lambda event: event.get("type") == "snapshot")
                self.assertEqual(snapshot_event["snapshot"]["dialogText"], "boot")

                _send_json_frame(
                    producer,
                    {
                        "v": 1,
                        "seq": 1,
                        "ts": int(time.time() * 1000),
                        "type": "notification.change",
                        "text": "connected",
                    },
                )
                notify_event = _wait_for_event(viewer, lambda event: event.get("type") == "notification.change")
                self.assertEqual(notify_event["text"], "connected")

                sent = service.send_command(session["sessionId"], {"cmdId": "cmd-1", "type": "pause-asr"})
                self.assertTrue(sent)
                command_event = _wait_for_event(producer, lambda event: event.get("type") == "command")
                self.assertEqual(command_event["command"], {"cmdId": "cmd-1", "type": "pause-asr"})

                _send_json_frame(
                    producer,
                    {
                        "v": 1,
                        "seq": 2,
                        "ts": int(time.time() * 1000),
                        "type": "asr.state",
                        "running": False,
                    },
                )
                _send_json_frame(
                    producer,
                    {
                        "v": 1,
                        "seq": 3,
                        "ts": int(time.time() * 1000),
                        "type": "cmd.ack",
                        "cmdId": "cmd-1",
                        "commandType": "pause-asr",
                        "ok": True,
                    },
                )

                paused_event = _wait_for_event(
                    viewer,
                    lambda event: event.get("type") == "asr.state" and bool(event.get("running")) is False,
                )
                self.assertEqual(paused_event["type"], "asr.state")
                ack_event = _wait_for_event(
                    viewer,
                    lambda event: event.get("type") == "cmd.ack" and event.get("cmdId") == "cmd-1",
                )
                self.assertTrue(ack_event["ok"])
                self.assertEqual(service.get_snapshot(session["sessionId"]).get("status"), "paused")
            finally:
                _close_ws(producer)
                _close_ws(viewer)
        finally:
            service.stop()

    def test_send_command_waits_for_producer_that_connects_shortly_after(self):
        service = ChatStreamService(host="127.0.0.1", bridge_port=_free_bridge_port())
        service.start()
        try:
            session = service.create_session({"dialogText": "boot"})
            result: dict[str, bool] = {}

            def _send() -> None:
                result["sent"] = service.send_command(session["sessionId"], {"cmdId": "cmd-race", "type": "pause-asr"})

            sender = threading.Thread(target=_send, daemon=True)
            sender.start()
            time.sleep(0.2)

            producer = _open_ws(session["wsUrl"], session_id=session["sessionId"], role="producer")
            try:
                sender.join(timeout=5.0)
                self.assertFalse(sender.is_alive())
                self.assertTrue(result.get("sent"))
                command_event = _wait_for_event(
                    producer,
                    lambda event: event.get("type") == "command" and event.get("command", {}).get("cmdId") == "cmd-race",
                )
                self.assertEqual(command_event["command"], {"cmdId": "cmd-race", "type": "pause-asr"})
            finally:
                _close_ws(producer)
        finally:
            service.stop()

    def test_viewer_reconnect_receives_latest_snapshot_over_real_socket(self):
        service = ChatStreamService(host="127.0.0.1", bridge_port=_free_bridge_port())
        service.start()
        try:
            session = service.create_session()
            sink = WSClientSink(session["producerEndpoint"])
            sink.emit({"type": "dialog.end", "speaker": "Nanami", "color": "#fff", "isSystem": False, "fullHtml": "<p>hello</p>"})
            _wait_until(lambda: service.get_snapshot(session["sessionId"]).get("dialogText") == "hello")

            viewer1 = _open_ws(session["wsUrl"], session_id=session["sessionId"], role="viewer")
            try:
                snapshot1 = _wait_for_event(viewer1, lambda event: event.get("type") == "snapshot")
                self.assertEqual(snapshot1["snapshot"]["dialogText"], "hello")
                self.assertEqual(snapshot1["snapshot"]["characterName"], "Nanami")
            finally:
                _close_ws(viewer1)

            viewer2 = _open_ws(session["wsUrl"], session_id=session["sessionId"], role="viewer")
            try:
                snapshot2 = _wait_for_event(viewer2, lambda event: event.get("type") == "snapshot")
                self.assertEqual(snapshot2["snapshot"]["dialogText"], "hello")
                self.assertEqual(snapshot2["snapshot"]["characterName"], "Nanami")
                self.assertGreaterEqual(int(snapshot2["seq"]), 1)
            finally:
                sink.close()
                _close_ws(viewer2)
        finally:
            service.stop()

    def test_viewer_reconnect_snapshot_matches_control_event_recovery_state(self):
        service = ChatStreamService(host="127.0.0.1", bridge_port=_free_bridge_port())
        service.start()
        try:
            session = service.create_session()
            sink = WSClientSink(session["producerEndpoint"])
            sink.emit({"type": "dialog.end", "speaker": "Nanami", "color": "#fff", "isSystem": False, "fullHtml": "<p>hello</p>"})
            sink.emit({"type": "busy.show", "text": "Loading", "durationSeconds": 3.0})
            sink.emit({"type": "session.closed", "reason": "closing for test"})
            sink.emit(
                {
                    "type": "dialog.end",
                    "speaker": "旁白",
                    "color": "#84C2D5",
                    "isSystem": True,
                    "fullHtml": "<p><b>旁白</b>：系统消息</p>",
                }
            )
            _wait_until(lambda: service.get_snapshot(session["sessionId"]).get("dialogText") == "旁白：系统消息")

            viewer = _open_ws(session["wsUrl"], session_id=session["sessionId"], role="viewer")
            try:
                snapshot = _wait_for_event(viewer, lambda event: event.get("type") == "snapshot")
                hydrated = snapshot["snapshot"]
                self.assertEqual(hydrated["dialogText"], "旁白：系统消息")
                self.assertEqual(hydrated.get("characterName"), "")
                self.assertEqual(hydrated.get("busyText"), "")
                self.assertEqual(hydrated.get("busyDurationSeconds"), 0.0)
                self.assertEqual(hydrated.get("sessionClosedReason"), "")
                self.assertEqual(hydrated.get("notificationText"), "")
                self.assertEqual(hydrated.get("status"), "idle")
            finally:
                sink.close()
                _close_ws(viewer)
        finally:
            service.stop()

    def test_producer_reconnect_replaces_old_socket_and_keeps_commands_flowing(self):
        service = ChatStreamService(host="127.0.0.1", bridge_port=_free_bridge_port())
        service.start()
        try:
            session = service.create_session({"dialogText": "boot"})
            producer1 = _open_ws(session["wsUrl"], session_id=session["sessionId"], role="producer")
            viewer = _open_ws(session["wsUrl"], session_id=session["sessionId"], role="viewer")
            producer2 = None
            try:
                snapshot_event = _wait_for_event(viewer, lambda event: event.get("type") == "snapshot")
                self.assertEqual(snapshot_event["snapshot"]["dialogText"], "boot")

                producer2 = _open_ws(session["wsUrl"], session_id=session["sessionId"], role="producer")
                _wait_for_socket_close(producer1)

                _send_json_frame(
                    producer2,
                    {
                        "v": 1,
                        "seq": 1,
                        "ts": int(time.time() * 1000),
                        "type": "notification.change",
                        "text": "from producer2",
                    },
                )
                notify_event = _wait_for_event(
                    viewer,
                    lambda event: event.get("type") == "notification.change" and event.get("text") == "from producer2",
                )
                self.assertEqual(notify_event["text"], "from producer2")

                sent = service.send_command(session["sessionId"], {"cmdId": "cmd-2", "type": "resume-asr"})
                self.assertTrue(sent)
                command_event = _wait_for_event(
                    producer2,
                    lambda event: event.get("type") == "command" and event.get("command", {}).get("cmdId") == "cmd-2",
                )
                self.assertEqual(command_event["command"], {"cmdId": "cmd-2", "type": "resume-asr"})
            finally:
                _close_ws(viewer)
                if producer2 is not None:
                    _close_ws(producer2)
                _close_ws(producer1)
        finally:
            service.stop()

    def test_service_can_restart_after_stop_and_accept_new_connections(self):
        service = ChatStreamService(host="127.0.0.1", bridge_port=_free_bridge_port())
        service.start()
        viewer = None
        try:
            first = service.create_session({"dialogText": "first"})
            viewer = _open_ws(first["wsUrl"], session_id=first["sessionId"], role="viewer")
            snapshot = _wait_for_event(viewer, lambda event: event.get("type") == "snapshot")
            self.assertEqual(snapshot["snapshot"]["dialogText"], "first")
        finally:
            service.stop()
            if viewer is not None:
                _wait_for_socket_close(viewer)
                _close_ws(viewer)

        service.start()
        viewer2 = None
        try:
            second = service.create_session({"dialogText": "second"})
            viewer2 = _open_ws(second["wsUrl"], session_id=second["sessionId"], role="viewer")
            snapshot2 = _wait_for_event(viewer2, lambda event: event.get("type") == "snapshot")
            self.assertEqual(snapshot2["snapshot"]["dialogText"], "second")
            self.assertFalse(service.send_command(second["sessionId"], {"cmdId": "cmd-3", "type": "pause-asr"}))
        finally:
            service.stop()
            if viewer2 is not None:
                _close_ws(viewer2)


if __name__ == "__main__":
    unittest.main()
