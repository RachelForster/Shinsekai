"""Dialog, player options, tool confirmation, turn state, and stats event handlers."""

from __future__ import annotations

import math
from typing import Any

from .snapshot import EventDict, EventFoldSpec, SnapshotDict, plain_text


def _fold_dialog_end(next_snapshot: SnapshotDict, event: EventDict) -> None:
    full_html = str(event.get("fullHtml") or "")
    speaker = str(event.get("speaker") or "")
    next_snapshot["dialogHtml"] = full_html
    next_snapshot["dialogText"] = plain_text(full_html)
    is_speakerless_system = bool(event.get("isSystem")) and not speaker.strip()
    if is_speakerless_system:
        next_snapshot["characterName"] = ""
        next_snapshot["systemMessageText"] = plain_text(full_html)
    else:
        next_snapshot["characterName"] = speaker
        next_snapshot["systemMessageText"] = ""
    if speaker.strip() or not bool(event.get("isSystem")):
        next_snapshot["options"] = []


def _fold_user_display_name_change(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    name = str(event.get("name") or "").strip()
    if name:
        next_snapshot["userDisplayName"] = name


def _fold_options_show(next_snapshot: SnapshotDict, event: EventDict) -> None:
    next_snapshot["replaySelectedIndex"] = event.get("selectedIndex")
    next_snapshot["options"] = [
        dict(item) if isinstance(item, dict) else str(item)
        for item in (event.get("options") or [])
    ]
    next_snapshot["toolConfirmation"] = None


def _fold_options_clear(
    next_snapshot: SnapshotDict, _event: EventDict
) -> None:
    next_snapshot["options"] = []


def _fold_tool_confirmation_show(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    next_snapshot["options"] = []
    next_snapshot["toolConfirmation"] = {
        "confirmationId": str(event.get("confirmationId") or ""),
        "detail": str(event.get("detail") or ""),
        "risk": str(event.get("risk") or "high"),
        "toolName": str(event.get("toolName") or ""),
    }


def _fold_tool_confirmation_clear(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    current = next_snapshot.get("toolConfirmation")
    confirmation_id = str(event.get("confirmationId") or "")
    if (
        isinstance(current, dict)
        and str(current.get("confirmationId") or "") == confirmation_id
    ):
        next_snapshot["toolConfirmation"] = None


def _fold_history_replace(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    next_snapshot["historyEntries"] = [
        dict(item) for item in (event.get("entries") or []) if isinstance(item, dict)
    ]
    if isinstance(event.get("voiceArchiveEnabled"), bool):
        next_snapshot["voiceArchiveEnabled"] = event["voiceArchiveEnabled"]


def _fold_chat_turn_state(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
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
                message
                for message in (pending_messages or [])
                if isinstance(message, str) and message
            ],
            "remainingSeconds": (
                max(0, int(remaining))
                if isinstance(remaining, (int, float))
                and not isinstance(remaining, bool)
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


def _fold_numeric_update(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    next_snapshot["numericInfo"] = plain_text(str(event.get("html") or ""))


def _fold_stats_update(next_snapshot: SnapshotDict, event: EventDict) -> None:
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


def _fold_busy_show(next_snapshot: SnapshotDict, event: EventDict) -> None:
    next_snapshot["busyText"] = str(event.get("text") or "")
    next_snapshot["busyDurationSeconds"] = float(
        event.get("durationSeconds") or 0.0
    )


def _fold_busy_hide(next_snapshot: SnapshotDict, _event: EventDict) -> None:
    next_snapshot["busyText"] = ""
    next_snapshot["busyDurationSeconds"] = 0.0


HANDLERS: dict[str, EventFoldSpec] = {
    "dialog.end": EventFoldSpec(_fold_dialog_end, clear_transient_notice=True),
    "user.display_name.change": EventFoldSpec(_fold_user_display_name_change),
    "options.show": EventFoldSpec(
        _fold_options_show, clear_transient_notice=True
    ),
    "options.clear": EventFoldSpec(_fold_options_clear),
    "tool.confirmation.show": EventFoldSpec(
        _fold_tool_confirmation_show, clear_transient_notice=True
    ),
    "tool.confirmation.clear": EventFoldSpec(_fold_tool_confirmation_clear),
    "history.replace": EventFoldSpec(_fold_history_replace),
    "chat.turn.state": EventFoldSpec(_fold_chat_turn_state),
    "numeric.update": EventFoldSpec(_fold_numeric_update),
    "stats.update": EventFoldSpec(_fold_stats_update),
    "busy.show": EventFoldSpec(_fold_busy_show),
    "busy.hide": EventFoldSpec(_fold_busy_hide),
}
