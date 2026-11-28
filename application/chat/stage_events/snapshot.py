"""Snapshot defaults, text helpers, and fold specification contracts for stage events."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

SnapshotDict = dict[str, Any]
EventDict = Mapping[str, Any]
EventHandler = Callable[[SnapshotDict, EventDict], SnapshotDict | None]

PRESENTATION_KEYS = (
    "backgroundPath",
    "bgmPath",
    "cgPath",
    "ambientEffects",
    "sprites",
    "stats",
    "characterName",
    "dialogHtml",
    "dialogText",
    "options",
    "systemMessageText",
    "playerPortrait",
)


@dataclass(frozen=True, slots=True)
class EventFoldSpec:
    """Declarative specification for folding one chat-stage event into a snapshot."""

    handler: EventHandler
    clear_transient_notice: bool = False
    bypass_seq_advance: bool = False


def strip_html(value: str) -> str:
    return (
        re.sub(r"<br\s*/?>", "\n", value or "", flags=re.IGNORECASE)
        .replace("</p>", "\n")
        .replace("</div>", "\n")
        .replace("</li>", "\n")
    )


def plain_text(value: str) -> str:
    return re.sub(r"<[^>]+>", "", strip_html(value or "")).strip()


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def make_empty_chat_snapshot() -> SnapshotDict:
    return {
        "activePlayback": None,
        "ambientEffects": [],
        "asrEnabled": False,
        "asrLoading": False,
        "asrRunning": False,
        "backgroundTransition": None,
        "dialogText": "",
        "eventSeq": 0,
        "historyEntries": [],
        "inputDraft": "",
        "effectImage": None,
        "loopingEffects": [],
        "options": [],
        "perception": None,
        "pluginBehaviorEvents": [],
        "pluginPagePresentations": [],
        "spriteMotions": {},
        "spriteReaction": None,
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


def normalize_snapshot_defaults(snapshot: Mapping[str, Any] | None) -> SnapshotDict:
    """Return a mutable snapshot copy with all required stage default keys present."""
    next_snapshot = dict(snapshot or make_empty_chat_snapshot())
    next_snapshot.setdefault("dialogText", "")
    next_snapshot.setdefault("eventSeq", 0)
    next_snapshot.setdefault("historyEntries", [])
    next_snapshot.setdefault("backgroundTransition", None)
    next_snapshot.setdefault("effectImage", None)
    next_snapshot.setdefault("ambientEffects", [])
    next_snapshot.setdefault("inputDraft", "")
    next_snapshot.setdefault("activePlayback", None)
    next_snapshot.setdefault("loopingEffects", [])
    next_snapshot.setdefault("options", [])
    next_snapshot.setdefault("pluginBehaviorEvents", [])
    next_snapshot.setdefault("pluginPagePresentations", [])
    next_snapshot.setdefault("spriteMotions", {})
    next_snapshot.setdefault("sprites", [])
    next_snapshot.setdefault("stats", [])
    next_snapshot.setdefault("status", "idle")
    return next_snapshot


def clear_transient_notification_state(next_snapshot: SnapshotDict) -> None:
    if "notificationText" in next_snapshot:
        next_snapshot["notificationText"] = ""
    if "sessionClosedReason" in next_snapshot:
        next_snapshot["sessionClosedReason"] = ""


def advance_event_seq(next_snapshot: SnapshotDict, event: EventDict) -> None:
    try:
        next_snapshot["eventSeq"] = max(
            int(next_snapshot.get("eventSeq") or 0),
            int(event.get("seq") or 0),
        )
    except (TypeError, ValueError):
        pass
