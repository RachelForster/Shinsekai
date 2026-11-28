"""ASR and perception event handlers."""

from __future__ import annotations

from .snapshot import EventDict, EventFoldSpec, SnapshotDict


def _fold_asr_partial(next_snapshot: SnapshotDict, event: EventDict) -> None:
    next_snapshot["asrEnabled"] = True
    next_snapshot["asrLoading"] = False
    next_snapshot["asrRunning"] = True
    next_snapshot["inputDraft"] = str(event.get("text") or "")
    next_snapshot["status"] = "listening"


def _fold_asr_final(next_snapshot: SnapshotDict, event: EventDict) -> None:
    # The final transcript has already entered the chat turn pipeline.
    # Persist that accepted user turn so polling and reconnect hydration
    # expose the same presentation as the live event stream.
    next_snapshot["characterName"] = (
        str(next_snapshot.get("userDisplayName") or "").strip() or "你"
    )
    next_snapshot["dialogHtml"] = None
    next_snapshot["dialogText"] = str(event.get("text") or "").strip()
    next_snapshot["inputDraft"] = ""
    next_snapshot["options"] = []


def _fold_asr_state(next_snapshot: SnapshotDict, event: EventDict) -> None:
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


def _fold_perception_state(
    next_snapshot: SnapshotDict, event: EventDict
) -> None:
    perception = event.get("perception")
    if isinstance(perception, dict):
        next_snapshot["perception"] = dict(perception)


def _fold_perception_capture_request(
    _next_snapshot: SnapshotDict, _event: EventDict
) -> None:
    return None


HANDLERS: dict[str, EventFoldSpec] = {
    "asr.partial": EventFoldSpec(_fold_asr_partial, clear_transient_notice=True),
    "asr.final": EventFoldSpec(_fold_asr_final, clear_transient_notice=True),
    "asr.state": EventFoldSpec(_fold_asr_state, clear_transient_notice=True),
    "perception.state": EventFoldSpec(_fold_perception_state),
    "perception.capture_request": EventFoldSpec(_fold_perception_capture_request),
}
