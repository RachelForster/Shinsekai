"""Chat-stage event protocol, snapshot reducer, and application sink contracts.

设计文档《chat_ui_react_migration_and_theme_system.md》"参考接口输出 · D"。

``ChatEventSink`` 是演出输出的抽象出口；具体 HTTP/WebSocket 传输适配器位于
``frontend_bridge_core.transport``，由进程入口注入 application。
"""

from __future__ import annotations

import itertools
import math
import re
import time
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


def make_empty_chat_snapshot() -> Dict[str, Any]:
    return {
        "asrEnabled": False,
        "asrLoading": False,
        "asrRunning": False,
        "dialogText": "",
        "eventSeq": 0,
        "historyEntries": [],
        "inputDraft": "",
        "options": [],
        "pluginPagePresentations": [],
        "sprites": [],
        "stats": [],
        "status": "idle",
        "systemMessageText": "",
        "toolConfirmation": None,
        "turnState": {
            "enabled": False,
            "pendingCount": 0,
            "pendingMessages": [],
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
    next_snapshot.setdefault("pluginPagePresentations", [])
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
        speaker = str(event.get("speaker") or "")
        next_snapshot["dialogHtml"] = full_html
        next_snapshot["dialogText"] = _plain_text(full_html)
        is_speakerless_system = bool(event.get("isSystem")) and not speaker.strip()
        if is_speakerless_system:
            next_snapshot["characterName"] = ""
            next_snapshot["systemMessageText"] = _plain_text(full_html)
        else:
            next_snapshot["characterName"] = speaker
            next_snapshot["systemMessageText"] = ""
        if speaker.strip() or not bool(event.get("isSystem")):
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
        next_snapshot["toolConfirmation"] = None
        return next_snapshot

    if event_type == "options.clear":
        next_snapshot["options"] = []
        return next_snapshot

    if event_type == "tool.confirmation.show":
        _clear_transient_notification_state(next_snapshot)
        next_snapshot["options"] = []
        next_snapshot["toolConfirmation"] = {
            "confirmationId": str(event.get("confirmationId") or ""),
            "detail": str(event.get("detail") or ""),
            "risk": str(event.get("risk") or "high"),
            "toolName": str(event.get("toolName") or ""),
        }
        return next_snapshot

    if event_type == "tool.confirmation.clear":
        current = next_snapshot.get("toolConfirmation")
        confirmation_id = str(event.get("confirmationId") or "")
        if isinstance(current, dict) and str(
            current.get("confirmationId") or ""
        ) == confirmation_id:
            next_snapshot["toolConfirmation"] = None
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

    if event_type == "plugin.page.present":
        plugin_id = str(event.get("pluginId") or "").strip()[:128]
        page_id = str(event.get("pageId") or "").strip()[:128]
        presentation_id = str(event.get("presentationId") or "").strip()[:128]
        if not plugin_id or not page_id or not presentation_id:
            return next_snapshot
        current = [
            dict(item)
            for item in (next_snapshot.get("pluginPagePresentations") or [])
            if isinstance(item, dict)
            and (
                str(item.get("pluginId") or "") != plugin_id
                or str(item.get("presentationId") or "") != presentation_id
            )
        ]
        current.append(
            {
                "mode": "overlay",
                "pageId": page_id,
                "payload": (
                    dict(event.get("payload"))
                    if isinstance(event.get("payload"), dict)
                    else {}
                ),
                "pluginId": plugin_id,
                "presentationId": presentation_id,
            }
        )
        next_snapshot["pluginPagePresentations"] = current[-8:]
        return next_snapshot

    if event_type == "plugin.page.dismiss":
        plugin_id = str(event.get("pluginId") or "").strip()
        presentation_id = str(event.get("presentationId") or "").strip()
        next_snapshot["pluginPagePresentations"] = [
            dict(item)
            for item in (next_snapshot.get("pluginPagePresentations") or [])
            if isinstance(item, dict)
            and (
                str(item.get("pluginId") or "") != plugin_id
                or str(item.get("presentationId") or "") != presentation_id
            )
        ]
        return next_snapshot

    if event_type == "chat.turn.state":
        state = event.get("state")
        if isinstance(state, dict):
            remaining = state.get("remainingSeconds")
            pending_messages = state.get("pendingMessages")
            if not isinstance(pending_messages, list):
                pending_messages = []
            next_snapshot["turnState"] = {
                "enabled": bool(state.get("enabled")),
                "pendingCount": max(0, int(state.get("pendingCount") or 0)),
                "pendingMessages": [
                    message for message in (pending_messages or []) if isinstance(message, str) and message
                ],
                "remainingSeconds": (
                    max(0, int(remaining))
                    if isinstance(remaining, (int, float)) and not isinstance(remaining, bool)
                    else None
                ),
                "scheduled": bool(state.get("scheduled")),
                "typing": bool(state.get("typing")),
            }
        options = event.get("options")
        if isinstance(options, dict):
            interrupt_enabled = options.get("interruptEnabled")
            batch_enabled = options.get("batchEnabled")
            batch_idle_seconds = options.get("batchIdleSeconds")
            if (
                isinstance(interrupt_enabled, bool)
                and isinstance(batch_enabled, bool)
                and not isinstance(batch_idle_seconds, bool)
                and isinstance(batch_idle_seconds, (int, float))
                and math.isfinite(float(batch_idle_seconds))
            ):
                next_snapshot["turnOptions"] = {
                    "interruptEnabled": interrupt_enabled,
                    "batchEnabled": batch_enabled,
                    "batchIdleSeconds": float(batch_idle_seconds),
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
        next_snapshot["asrEnabled"] = True
        next_snapshot["asrLoading"] = False
        next_snapshot["asrRunning"] = True
        next_snapshot["inputDraft"] = str(event.get("text") or "")
        next_snapshot["status"] = "listening"
        return next_snapshot

    if event_type == "asr.final":
        _clear_transient_notification_state(next_snapshot)
        # The final transcript has already entered the chat turn pipeline.
        # Persist its consumed presentation state for reconnect hydration.
        next_snapshot["inputDraft"] = ""
        next_snapshot["options"] = []
        return next_snapshot

    if event_type == "asr.state":
        _clear_transient_notification_state(next_snapshot)
        running = bool(event.get("running"))
        enabled = bool(event.get("enabled", running))
        next_snapshot["asrEnabled"] = enabled
        next_snapshot["asrLoading"] = bool(event.get("loading")) and enabled
        next_snapshot["asrRunning"] = running and enabled
        current_status = str(next_snapshot.get("status") or "idle")
        if running:
            next_snapshot["status"] = "listening"
        elif current_status not in {"generating", "streaming", "speaking"}:
            next_snapshot["status"] = "paused"
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
        next_snapshot["pluginPagePresentations"] = []
        next_snapshot["sessionClosedReason"] = str(event.get("reason") or "")
        next_snapshot["status"] = "idle"
        next_snapshot["systemMessageText"] = ""
        next_snapshot["toolConfirmation"] = None
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


class BaseEventSink:
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


class NullEventSink(BaseEventSink):
    """丢弃所有事件的 sink（无 stream 端点时的默认实现，等价 headless）。"""

    def emit(self, payload: Dict[str, Any]) -> None:
        self._remember(self._next(payload))
