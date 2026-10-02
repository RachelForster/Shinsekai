"""Registered bridge-side commands and common realtime forwarding.

Worker execution stays in commands.py. Extensions receive request-scoped ports,
not BridgeState or HTTP handlers.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from copy import deepcopy
from typing import Any, Protocol

_RUNTIME_CHAT_COMMANDS = {
    "begin-asr-hold",
    "finish-asr-hold",
    "cancel-asr-hold",
    "audio-playback-signal",
    "cancel-input-batch",
    "change-voice-language",
    "chat-input-state",
    "clear-history",
    "dialog-advance",
    "flush-input-batch",
    "fork-history",
    "pause-asr",
    "rename-branch",
    "resume-asr",
    "reroll",
    "revert-history",
    "send-message",
    "skip-speech",
    "switch-branch",
    "submit-option",
    "update-turn-options",
}


class RuntimeCommandStream(Protocol):
    def get_snapshot(self, session_id: str) -> dict[str, Any] | None: ...

    def send_command(self, session_id: str, command: dict[str, Any]) -> bool: ...

    def update_session_snapshot(self, session_id: str, patch: dict[str, Any]) -> None: ...

    def publish_event(self, session_id: str, event: dict[str, Any]) -> bool: ...


@dataclass(frozen=True)
class RuntimeCommandPorts:
    session_id: str
    stream: RuntimeCommandStream | None
    snapshot: Callable[..., dict[str, Any]]
    update_session: Callable[[dict[str, Any]], None]

    def current_status(self) -> str:
        if self.session_id and self.stream is not None:
            snapshot = self.stream.get_snapshot(self.session_id)
            if isinstance(snapshot, dict):
                status = str(snapshot.get("status") or "").strip()
                if status:
                    return status
        return "idle"

    def forward(
        self, body: dict[str, Any], next_status: str, next_message: str = "", *,
        session_patch: dict[str, Any] | None = None,
        snapshot_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        command = str(body.get("type") or "").strip()
        if command not in _RUNTIME_CHAT_COMMANDS:
            raise ValueError(f"未知实时聊天命令：{command}")
        if not self.session_id or self.stream is None:
            raise RuntimeError("当前聊天会话未连接到实时流。")
        runtime_command = dict(body)
        runtime_command["cmdId"] = str(body.get("cmdId") or uuid.uuid4().hex)
        if not self.stream.send_command(self.session_id, runtime_command):
            raise RuntimeError("实时聊天会话未就绪，无法发送命令。")
        if session_patch:
            self.update_session(session_patch)
        next_snapshot = {
            "numericInfo": next_status, "sessionClosedReason": "", "status": next_status,
        }
        current = self.stream.get_snapshot(self.session_id)
        if isinstance(current, dict) and str(current.get("sessionClosedReason") or "").strip():
            next_snapshot["notificationText"] = ""
        if next_message:
            next_snapshot.update(dialogText=next_message, dialogHtml=None, characterName="")
        if snapshot_patch:
            next_snapshot.update(snapshot_patch)
        self.stream.update_session_snapshot(self.session_id, next_snapshot)
        return self.snapshot(next_status, next_message, extra=snapshot_patch)


@dataclass(frozen=True)
class CommandContext:
    body: dict[str, Any]
    ports: RuntimeCommandPorts

    @property
    def command(self) -> str:
        return str(self.body.get("type") or "").strip()

    def forward(self, status: str, message: str = "", **patches: Any) -> dict[str, Any]:
        return self.ports.forward(self.body, status, message, **patches)


CommandHandler = Callable[[CommandContext], dict[str, Any]]


class CommandRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._handlers: dict[str, CommandHandler] = {}
        self._option_handlers: dict[str, CommandHandler] = {}

    def register(self, command: str, handler: CommandHandler) -> None:
        with self._lock:
            if not command or command in self._handlers:
                raise ValueError(f"Duplicate or empty chat command: {command}")
            self._handlers[command] = handler

    def register_option(self, kind: str, handler: CommandHandler) -> None:
        with self._lock:
            if not kind or kind in self._option_handlers:
                raise ValueError(f"Duplicate or empty option kind: {kind}")
            self._option_handlers[kind] = handler

    def execute(self, context: CommandContext) -> dict[str, Any]:
        with self._lock:
            if context.command == "submit-option" and isinstance(context.body.get("payload"), dict):
                handler = self._option_handlers.get(str(context.body["payload"].get("kind") or ""))
                if handler is None:
                    raise ValueError("Option selection must be a string.")
            else:
                handler = self._handlers.get(context.command)
                if handler is None:
                    raise ValueError(f"未知聊天命令：{context.command}")
        return handler(context)


def dispatch_chat_command(state: Any, body: dict[str, Any]) -> dict[str, Any]:
    from application.bootstrap.chat_runtime import get_chat_runtime

    runtime = get_chat_runtime(state)
    return runtime.commands.execute(runtime.command_context(deepcopy(body)))
