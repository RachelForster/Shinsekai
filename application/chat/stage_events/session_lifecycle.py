"""Session lifecycle, snapshot hydration, chat init task, and replay state handlers."""

from __future__ import annotations

from typing import Any

from .snapshot import (
    EventDict,
    EventFoldSpec,
    EventHandler,
    SnapshotDict,
    make_empty_chat_snapshot,
)

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

_CHAT_INIT_STATUS_BY_EVENT = {
    "chat.init.progress": "running",
    "chat.init.completed": "succeeded",
    "chat.init.failed": "failed",
    "chat.init.cancelled": "cancelled",
}


def fold_chat_init_task(
    current: Any,
    raw_task: Any,
    *,
    event_type: str,
) -> SnapshotDict:
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
        elif isinstance(progress, (int, float)) and not isinstance(
            progress, bool
        ):
            task["progress"] = max(0.0, min(1.0, float(progress)))

    raw_logs = payload.get("logs")
    if isinstance(raw_logs, list):
        task["logs"] = [
            str(line)[:4000] for line in raw_logs[-120:] if str(line).strip()
        ]
    if "cancelRequested" in payload:
        task["cancelRequested"] = bool(payload.get("cancelRequested"))

    task["status"] = _CHAT_INIT_STATUS_BY_EVENT[event_type]
    if event_type == "chat.init.completed":
        task["progress"] = 1.0
    return task


def _make_chat_init_handler(event_type: str) -> EventHandler:
    def _handle(next_snapshot: SnapshotDict, event: EventDict) -> None:
        next_snapshot["initTask"] = fold_chat_init_task(
            next_snapshot.get("initTask"),
            event.get("task"),
            event_type=event_type,
        )

    return _handle


def _fold_snapshot(
    next_snapshot: SnapshotDict, event: EventDict
) -> SnapshotDict:
    payload = event.get("snapshot")
    if not isinstance(payload, dict):
        return next_snapshot
    merged = make_empty_chat_snapshot()
    merged.update(payload)
    if isinstance(merged.get("spriteMotions"), dict):
        merged["spriteMotions"] = dict(merged["spriteMotions"])
    else:
        merged["spriteMotions"] = {}
    if "eventSeq" not in merged:
        try:
            merged["eventSeq"] = int(event.get("seq") or 0)
        except (TypeError, ValueError):
            merged["eventSeq"] = 0
    return merged


def _fold_replay_state(next_snapshot: SnapshotDict, event: EventDict) -> None:
    next_snapshot["replay"] = event.get("replay")
    if event.get("replay"):
        next_snapshot["status"] = "replaying"


def _fold_status_change(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    next_snapshot["status"] = str(event.get("status") or "idle")


def _fold_notification_change(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    next_snapshot["notificationText"] = str(event.get("text") or "")


def _fold_reply_finished(
    next_snapshot: SnapshotDict, _event: EventDict
) -> None:
    next_snapshot["activePlayback"] = None
    next_snapshot["status"] = "idle"


def _fold_session_closed(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    reason = str(event.get("reason") or "")
    next_snapshot["activePlayback"] = None
    next_snapshot["ambientEffects"] = []
    next_snapshot["backgroundTransition"] = None
    next_snapshot["effectImage"] = None
    next_snapshot["busyText"] = ""
    next_snapshot["busyDurationSeconds"] = 0.0
    next_snapshot["loopingEffects"] = []
    next_snapshot["notificationText"] = reason
    next_snapshot["options"] = []
    next_snapshot["perception"] = None
    next_snapshot["pluginPagePresentations"] = []
    next_snapshot["sessionClosedReason"] = reason
    next_snapshot["spriteMotions"] = {}
    next_snapshot["spriteReaction"] = None
    next_snapshot["status"] = "idle"
    next_snapshot["systemMessageText"] = ""
    next_snapshot["toolConfirmation"] = None


HANDLERS: dict[str, EventFoldSpec] = {
    "snapshot": EventFoldSpec(_fold_snapshot, bypass_seq_advance=True),
    **{
        event_type: EventFoldSpec(_make_chat_init_handler(event_type))
        for event_type in _CHAT_INIT_STATUS_BY_EVENT
    },
    "replay.state": EventFoldSpec(_fold_replay_state),
    "status.change": EventFoldSpec(
        _fold_status_change, clear_transient_notice=True
    ),
    "notification.change": EventFoldSpec(_fold_notification_change),
    "reply.finished": EventFoldSpec(
        _fold_reply_finished, clear_transient_notice=True
    ),
    "session.closed": EventFoldSpec(_fold_session_closed),
}
