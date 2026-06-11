from __future__ import annotations

import base64
import json
import os
import socket
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

import pytest

from core.runtime.event_sink import WSClientSink

pytestmark = pytest.mark.e2e

_API_BASE = os.environ.get("SHINSEKAI_API_BASE", "").strip()
_PROJECT_ROOT = Path(os.environ.get("SHINSEKAI_PROJECT_ROOT", "")).expanduser() if os.environ.get("SHINSEKAI_PROJECT_ROOT") else None
_LIVE_BRIDGE_WORKFLOW = Path("test/e2e/live_bridge_runtime.yaml").as_posix()


def _request_json(method: str, path: str, data: dict | None = None) -> dict | list:
    assert _API_BASE
    payload = None
    headers = {}
    if data is not None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{_API_BASE}{path}", data=payload, headers=headers, method=method.upper())
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _open_viewer_socket(ws_url: str, session_id: str) -> socket.socket:
    parsed = urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path or "/ws"
    query = parse_qs(parsed.query)
    query["sessionId"] = [session_id]
    query["role"] = ["viewer"]
    target = f"{path}?{urlencode({key: values[-1] for key, values in query.items()})}"
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        f"GET {target} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    ).encode("utf-8")
    sock = socket.create_connection((host, port), timeout=10.0)
    sock.settimeout(10.0)
    sock.sendall(request)
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("viewer websocket handshake failed")
        response += chunk
    status_line = response.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
    if "101" not in status_line:
        raise ConnectionError(f"unexpected viewer websocket handshake response: {status_line}")
    return sock


def _read_json_event(sock: socket.socket) -> dict:
    opcode, payload = WSClientSink._read_frame(sock)
    if opcode == 0x8:
        raise ConnectionError("viewer websocket closed")
    return json.loads(payload.decode("utf-8"))


def _wait_for_event(sock: socket.socket, predicate, *, timeout: float = 15.0, backlog: list[dict] | None = None) -> dict:
    if backlog:
        for index, event in enumerate(list(backlog)):
            if predicate(event):
                backlog.pop(index)
                return event
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            event = _read_json_event(sock)
        except TimeoutError:
            continue
        if predicate(event):
            return event
        if backlog is not None:
            backlog.append(event)
    raise AssertionError("timed out waiting for websocket event")


def _close_viewer_socket(sock: socket.socket) -> None:
    try:
        WSClientSink._send_control_frame(sock, 0x8, b"")
    except Exception:
        pass
    try:
        sock.close()
    except OSError:
        pass


@pytest.mark.skipif(not _API_BASE or _PROJECT_ROOT is None, reason="Set SHINSEKAI_API_BASE and SHINSEKAI_PROJECT_ROOT for live bridge smoke tests.")
def test_live_bridge_launch_snapshot_ws_and_close_path():
    config = _request_json("GET", "/api/config")
    runtime_mode = str(config.get("system_config", {}).get("chat_ui_runtime_mode", "")).strip().lower()
    if runtime_mode != "react":
        pytest.skip("Live bridge config is not in react mode.")

    characters = _request_json("GET", "/api/characters")
    assert isinstance(characters, list) and characters, "live bridge must expose at least one character"
    first_character = str(characters[0]["name"])

    _request_json("POST", "/api/chat/close", {})

    history_file = _PROJECT_ROOT / "data" / "chat_history" / f"live-bridge-smoke-{int(time.time() * 1000)}.json"
    history_file.unlink(missing_ok=True)
    history_path = history_file.as_posix()
    launch_snapshot = _request_json(
        "POST",
        "/api/chat/launch",
        {
            "backgroundName": "透明场景",
            "characters": [first_character],
            "historyPath": history_path,
            "resetHistory": False,
            "scenario": "这是一个用于验证 React chat live bridge 的冒烟测试场景。",
            "system": "你是一个简短回应的测试角色。",
            "templateId": "live-bridge-smoke",
            "templateName": "live-bridge-smoke",
            "useCg": False,
            "workflowPath": _LIVE_BRIDGE_WORKFLOW,
        },
    )

    assert launch_snapshot["runtimeMode"] == "react"
    assert str(launch_snapshot.get("sessionId") or "").strip()
    assert str(launch_snapshot.get("wsUrl") or "").strip()

    viewer = _open_viewer_socket(str(launch_snapshot["wsUrl"]), str(launch_snapshot["sessionId"]))
    backlog: list[dict] = []
    try:
        snapshot_event = _wait_for_event(viewer, lambda event: event.get("type") == "snapshot", backlog=backlog)
        assert snapshot_event["snapshot"]["sessionId"] == launch_snapshot["sessionId"]
        assert snapshot_event["snapshot"]["wsUrl"] == launch_snapshot["wsUrl"]

        stage_event = _wait_for_event(
            viewer,
            lambda event: event.get("type") in {"dialog.end", "notification.change", "options.show", "sprite.show"},
            backlog=backlog,
        )
        assert stage_event["type"] in {"dialog.end", "notification.change", "options.show", "sprite.show"}

        sent_snapshot = _request_json("POST", "/api/chat/command", {"type": "send-message", "payload": "第一句测试消息"})
        assert sent_snapshot["status"] == "generating"
        assert sent_snapshot["dialogText"] == "已提交：第一句测试消息"

        sent_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "send-message",
            backlog=backlog,
        )
        assert sent_ack["ok"] is True

        sent_dialog = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "dialog.end" and "收到消息：第一句测试消息" in str(event.get("fullHtml") or ""),
            backlog=backlog,
        )
        assert sent_dialog["speaker"] == "直播桥接测试"

        sent_options = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "options.show" and event.get("options") == ["继续剧情", "结束测试"],
            backlog=backlog,
        )
        assert sent_options["options"] == ["继续剧情", "结束测试"]

        sent_history = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "history.replace"
            and any(item.get("text") == "你: 第一句测试消息" for item in (event.get("entries") or []))
            and any(
                item.get("text") == "直播桥接测试：收到消息：第一句测试消息"
                for item in (event.get("entries") or [])
            ),
            backlog=backlog,
        )
        assert any(item.get("text") == "直播桥接测试：收到消息：第一句测试消息" for item in sent_history["entries"])

        advanced_snapshot = _request_json("POST", "/api/chat/command", {"type": "dialog-advance"})
        assert advanced_snapshot["status"] == "idle"

        advanced_dialog = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "dialog.end" and "下一段已展开。" in str(event.get("fullHtml") or ""),
            backlog=backlog,
        )
        assert advanced_dialog["speaker"] == "直播桥接测试"

        advanced_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "dialog-advance",
            backlog=backlog,
        )
        assert advanced_ack["ok"] is True

        option_snapshot = _request_json("POST", "/api/chat/command", {"type": "submit-option", "payload": "继续剧情"})
        assert option_snapshot["status"] == "generating"
        assert option_snapshot["dialogText"] == "已选择：继续剧情"

        option_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "submit-option",
            backlog=backlog,
        )
        assert option_ack["ok"] is True

        option_cleared = _wait_for_event(viewer, lambda event: event.get("type") == "options.clear", backlog=backlog)
        assert option_cleared["type"] == "options.clear"

        option_dialog = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "dialog.end" and "已选择：继续剧情" in str(event.get("fullHtml") or ""),
            backlog=backlog,
        )
        assert option_dialog["speaker"] == "直播桥接测试"

        speaking_snapshot = _request_json("POST", "/api/chat/command", {"type": "send-message", "payload": "触发打断测试"})
        assert speaking_snapshot["status"] == "generating"
        assert speaking_snapshot["dialogText"] == "已提交：触发打断测试"

        speaking_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "send-message",
            backlog=backlog,
        )
        assert speaking_ack["ok"] is True

        speaking_event = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "tts.play" and event.get("characterName") == "直播桥接测试",
            backlog=backlog,
        )
        assert speaking_event["url"].endswith("test/audio/live-bridge-speaking.wav")

        skip_started_at = time.perf_counter()
        skip_snapshot = _request_json("POST", "/api/chat/command", {"type": "skip-speech"})
        assert skip_snapshot["status"] in {"speaking", "idle"}

        skip_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "skip-speech",
            backlog=backlog,
        )
        assert skip_ack["ok"] is True

        skip_event = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "tts.skip",
            backlog=backlog,
        )
        skip_latency_ms = (time.perf_counter() - skip_started_at) * 1000
        assert skip_event["type"] == "tts.skip"
        assert skip_latency_ms < 100.0

        skipped_dialog = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "dialog.end" and "语音已打断：触发打断测试" in str(event.get("fullHtml") or ""),
            backlog=backlog,
        )
        assert skipped_dialog["speaker"] == "直播桥接测试"

        paused_snapshot = _request_json("POST", "/api/chat/command", {"type": "pause-asr"})
        assert paused_snapshot["status"] == "paused"

        paused_event = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "asr.state" and bool(event.get("running")) is False,
            backlog=backlog,
        )
        assert paused_event["type"] == "asr.state"

        paused_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "pause-asr",
            backlog=backlog,
        )
        assert paused_ack["ok"] is True

        resumed_snapshot = _request_json("POST", "/api/chat/command", {"type": "resume-asr"})
        assert resumed_snapshot["status"] == "listening"

        resumed_event = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "asr.state" and bool(event.get("running")) is True,
            backlog=backlog,
        )
        assert resumed_event["type"] == "asr.state"

        resumed_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "resume-asr",
            backlog=backlog,
        )
        assert resumed_ack["ok"] is True

        close_snapshot = _request_json("POST", "/api/chat/close", {})
        assert close_snapshot["status"] == "idle"
        assert close_snapshot.get("busyText") in {"", None}
        assert float(close_snapshot.get("busyDurationSeconds") or 0.0) == 0.0
        assert close_snapshot["notificationText"] == "聊天会话已结束。"

        closed_event = _wait_for_event(viewer, lambda event: event.get("type") == "session.closed", backlog=backlog)
        assert closed_event["reason"] == "聊天会话已结束。"

        assert history_file.is_file()
        saved_history = json.loads(history_file.read_text(encoding="utf-8"))
        assert isinstance(saved_history, list)
        assert any(
            item.get("role") == "user" and item.get("content") == "第一句测试消息"
            for item in saved_history
            if isinstance(item, dict)
        )
        assert any(
            item.get("role") == "assistant" and "已选择：继续剧情" in str(item.get("content") or "")
            for item in saved_history
            if isinstance(item, dict)
        )

        final_snapshot = _request_json("GET", "/api/chat/snapshot")
        assert final_snapshot["sessionId"] == launch_snapshot["sessionId"]
        assert final_snapshot["sessionClosedReason"] == "聊天会话已结束。"
        assert final_snapshot["notificationText"] == "聊天会话已结束。"
        assert final_snapshot.get("busyText") in {"", None}
        assert float(final_snapshot.get("busyDurationSeconds") or 0.0) == 0.0
        assert final_snapshot["runtimeMode"] == "react"
        assert any(item["text"] == "你: 第一句测试消息" for item in final_snapshot["historyEntries"])
        assert final_snapshot["options"] == []
    finally:
        _close_viewer_socket(viewer)
        _request_json("POST", "/api/chat/close", {})


@pytest.mark.skipif(not _API_BASE or _PROJECT_ROOT is None, reason="Set SHINSEKAI_API_BASE and SHINSEKAI_PROJECT_ROOT for live bridge smoke tests.")
def test_live_bridge_reroll_clear_history_voice_language_and_revert_history():
    config = _request_json("GET", "/api/config")
    runtime_mode = str(config.get("system_config", {}).get("chat_ui_runtime_mode", "")).strip().lower()
    if runtime_mode != "react":
        pytest.skip("Live bridge config is not in react mode.")

    characters = _request_json("GET", "/api/characters")
    assert isinstance(characters, list) and characters, "live bridge must expose at least one character"
    first_character = str(characters[0]["name"])

    _request_json("POST", "/api/chat/close", {})

    history_file = _PROJECT_ROOT / "data" / "chat_history" / f"live-bridge-admin-{int(time.time() * 1000)}.json"
    history_file.unlink(missing_ok=True)
    launch_snapshot = _request_json(
        "POST",
        "/api/chat/launch",
        {
            "backgroundName": "透明场景",
            "characters": [first_character],
            "historyPath": history_file.as_posix(),
            "resetHistory": False,
            "scenario": "这是一个用于验证 React chat live bridge 其余命令链路的冒烟测试场景。",
            "system": "你是一个简短回应的测试角色。",
            "templateId": "live-bridge-admin",
            "templateName": "live-bridge-admin",
            "useCg": False,
            "workflowPath": _LIVE_BRIDGE_WORKFLOW,
        },
    )

    viewer = _open_viewer_socket(str(launch_snapshot["wsUrl"]), str(launch_snapshot["sessionId"]))
    backlog: list[dict] = []
    try:
        _wait_for_event(viewer, lambda event: event.get("type") == "snapshot", backlog=backlog)
        _wait_for_event(
            viewer,
            lambda event: event.get("type") in {"dialog.end", "notification.change", "options.show", "sprite.show"},
            backlog=backlog,
        )

        reroll_seed = _request_json("POST", "/api/chat/command", {"type": "send-message", "payload": "触发重试测试"})
        assert reroll_seed["status"] == "generating"
        reroll_seed_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "send-message",
            backlog=backlog,
        )
        assert reroll_seed_ack["ok"] is True
        first_retry_dialog = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "dialog.end" and "触发重试测试（第1次）" in str(event.get("fullHtml") or ""),
            backlog=backlog,
        )
        assert first_retry_dialog["speaker"] == "直播桥接测试"

        reroll_snapshot = _request_json("POST", "/api/chat/command", {"type": "reroll"})
        assert reroll_snapshot["status"] == "generating"

        reroll_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "reroll",
            backlog=backlog,
        )
        assert reroll_ack["ok"] is True
        rerolled_dialog = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "dialog.end" and "触发重试测试（第2次）" in str(event.get("fullHtml") or ""),
            backlog=backlog,
        )
        assert rerolled_dialog["speaker"] == "直播桥接测试"
        rerolled_history = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "history.replace"
            and any(item.get("text") == "直播桥接测试：收到消息：触发重试测试（第2次）" for item in (event.get("entries") or [])),
            backlog=backlog,
        )
        assert not any("第1次" in str(item.get("text") or "") for item in rerolled_history["entries"])

        second_turn_snapshot = _request_json("POST", "/api/chat/command", {"type": "send-message", "payload": "第二句回溯测试"})
        assert second_turn_snapshot["status"] == "generating"
        second_turn_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "send-message",
            backlog=backlog,
        )
        assert second_turn_ack["ok"] is True
        second_turn_dialog = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "dialog.end" and "收到消息：第二句回溯测试" in str(event.get("fullHtml") or ""),
            backlog=backlog,
        )
        assert second_turn_dialog["speaker"] == "直播桥接测试"

        runtime_history = _request_json("GET", "/api/chat/history")
        revert_indexes = [int(item["revertUserIndex"]) for item in runtime_history if isinstance(item, dict) and "revertUserIndex" in item]
        assert revert_indexes, "live bridge history should expose revertUserIndex"
        revert_index = max(revert_indexes)

        revert_snapshot = _request_json("POST", "/api/chat/command", {"type": "revert-history", "payload": revert_index})
        assert revert_snapshot["status"] == "idle"
        revert_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "revert-history",
            backlog=backlog,
        )
        assert revert_ack["ok"] is True
        reverted_dialog = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "dialog.end" and "触发重试测试（第2次）" in str(event.get("fullHtml") or ""),
            backlog=backlog,
        )
        assert reverted_dialog["speaker"] == "直播桥接测试"
        reverted_history = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "history.replace"
            and any("触发重试测试（第2次）" in str(item.get("text") or "") for item in (event.get("entries") or []))
            and not any("第二句回溯测试" in str(item.get("text") or "") for item in (event.get("entries") or [])),
            backlog=backlog,
        )
        assert not any("第二句回溯测试" in str(item.get("text") or "") for item in reverted_history["entries"])

        voice_snapshot = _request_json("POST", "/api/chat/command", {"type": "change-voice-language", "payload": "en"})
        assert voice_snapshot["voiceLanguage"] == "en"
        voice_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "change-voice-language",
            backlog=backlog,
        )
        assert voice_ack["ok"] is True
        final_voice_snapshot = _request_json("GET", "/api/chat/snapshot")
        assert final_voice_snapshot["voiceLanguage"] == "en"

        clear_snapshot = _request_json("POST", "/api/chat/command", {"type": "clear-history"})
        assert clear_snapshot["status"] == "idle"
        assert clear_snapshot["historyEntries"] == []
        clear_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "clear-history",
            backlog=backlog,
        )
        assert clear_ack["ok"] is True
        cleared_history = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "history.replace" and event.get("entries") == [],
            backlog=backlog,
        )
        assert cleared_history["entries"] == []
        assert _request_json("GET", "/api/chat/history") == []
        assert not history_file.exists()
    finally:
        _close_viewer_socket(viewer)
        _request_json("POST", "/api/chat/close", {})


@pytest.mark.skipif(not _API_BASE or _PROJECT_ROOT is None, reason="Set SHINSEKAI_API_BASE and SHINSEKAI_PROJECT_ROOT for live bridge smoke tests.")
def test_live_bridge_closed_marker_can_be_cleared_by_followup_runtime_command():
    config = _request_json("GET", "/api/config")
    runtime_mode = str(config.get("system_config", {}).get("chat_ui_runtime_mode", "")).strip().lower()
    if runtime_mode != "react":
        pytest.skip("Live bridge config is not in react mode.")

    characters = _request_json("GET", "/api/characters")
    assert isinstance(characters, list) and characters, "live bridge must expose at least one character"
    first_character = str(characters[0]["name"])

    _request_json("POST", "/api/chat/close", {})

    history_file = _PROJECT_ROOT / "data" / "chat_history" / f"live-bridge-closed-marker-{int(time.time() * 1000)}.json"
    history_file.unlink(missing_ok=True)
    launch_snapshot = _request_json(
        "POST",
        "/api/chat/launch",
        {
            "backgroundName": "透明场景",
            "characters": [first_character],
            "historyPath": history_file.as_posix(),
            "resetHistory": False,
            "scenario": "这是一个用于验证 React chat closed marker 恢复链路的受控测试场景。",
            "system": "你是一个简短回应的测试角色。",
            "templateId": "live-bridge-closed-marker",
            "templateName": "live-bridge-closed-marker",
            "useCg": False,
            "workflowPath": _LIVE_BRIDGE_WORKFLOW,
        },
    )

    viewer = _open_viewer_socket(str(launch_snapshot["wsUrl"]), str(launch_snapshot["sessionId"]))
    backlog: list[dict] = []
    try:
        _wait_for_event(viewer, lambda event: event.get("type") == "snapshot", backlog=backlog)
        _wait_for_event(
            viewer,
            lambda event: event.get("type") in {"dialog.end", "notification.change", "options.show", "sprite.show"},
            backlog=backlog,
        )

        closed_trigger_snapshot = _request_json(
            "POST",
            "/api/chat/command",
            {"type": "send-message", "payload": "触发关闭恢复测试"},
        )
        assert closed_trigger_snapshot["status"] == "generating"
        assert closed_trigger_snapshot["dialogText"] == "已提交：触发关闭恢复测试"

        closed_trigger_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "send-message",
            backlog=backlog,
        )
        assert closed_trigger_ack["ok"] is True

        closed_event = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "session.closed" and event.get("reason") == "聊天会话已结束。",
            backlog=backlog,
        )
        assert closed_event["reason"] == "聊天会话已结束。"

        closed_snapshot = _request_json("GET", "/api/chat/snapshot")
        assert closed_snapshot["sessionClosedReason"] == "聊天会话已结束。"
        assert closed_snapshot["notificationText"] == "聊天会话已结束。"

        reopened_snapshot = _request_json("POST", "/api/chat/command", {"type": "pause-asr"})
        assert reopened_snapshot["status"] == "paused"
        assert reopened_snapshot["sessionClosedReason"] == ""
        assert reopened_snapshot["notificationText"] == ""

        reopened_state = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "asr.state" and bool(event.get("running")) is False,
            backlog=backlog,
        )
        assert reopened_state["type"] == "asr.state"

        reopened_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "pause-asr",
            backlog=backlog,
        )
        assert reopened_ack["ok"] is True

        recovered_turn_snapshot = _request_json(
            "POST",
            "/api/chat/command",
            {"type": "send-message", "payload": "恢复后继续"},
        )
        assert recovered_turn_snapshot["status"] == "generating"
        assert recovered_turn_snapshot["sessionClosedReason"] == ""
        assert recovered_turn_snapshot["notificationText"] == ""

        recovered_turn_ack = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "cmd.ack" and event.get("commandType") == "send-message",
            backlog=backlog,
        )
        assert recovered_turn_ack["ok"] is True

        recovered_turn_dialog = _wait_for_event(
            viewer,
            lambda event: event.get("type") == "dialog.end" and "收到消息：恢复后继续" in str(event.get("fullHtml") or ""),
            backlog=backlog,
        )
        assert recovered_turn_dialog["speaker"] == "直播桥接测试"

        final_snapshot = _request_json("GET", "/api/chat/snapshot")
        assert final_snapshot["sessionClosedReason"] == ""
        assert final_snapshot["notificationText"] == ""
        assert final_snapshot["status"] in {"generating", "speaking", "idle"}
        assert any("恢复后继续" in str(item.get("text") or "") for item in (final_snapshot.get("historyEntries") or []))
    finally:
        _close_viewer_socket(viewer)
        _request_json("POST", "/api/chat/close", {})
