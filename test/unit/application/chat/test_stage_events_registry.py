from __future__ import annotations

import re
from pathlib import Path

import pytest

from application.chat.stage_events import (
    REPLAY_OBSERVED_EVENTS,
    STAGE_EVENT_REGISTRY,
    EventFoldSpec,
    build_event_registry,
    fold_event_into_snapshot,
    make_empty_chat_snapshot,
    project_replay_frame,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
CHAT_TYPES_PATH = REPO_ROOT / "frontend" / "src" / "shared" / "platform" / "slices" / "chatTypes.ts"
STAGE_EVENTS_DIR = REPO_ROOT / "application" / "chat" / "stage_events"
EVENT_SINK_PATH = REPO_ROOT / "application" / "runtime" / "event_sink.py"
FRONTEND_ONLY_EVENTS = frozenset({"transport.state", "cmd.ack"})


def _extract_ts_stage_event_types() -> set[str]:
    source = CHAT_TYPES_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"export type ChatStageEvent\s*=(.*?);\s*(?:\n\nexport |\Z)",
        source,
        re.DOTALL,
    )
    assert match is not None, "Could not locate ChatStageEvent union in chatTypes.ts"
    block = match.group(1)
    event_types: set[str] = set()
    for type_expr in re.findall(r'type:\s*((?:"[^"]+"\s*\|\s*)*"[^"]+")', block):
        event_types.update(re.findall(r'"([^"]+)"', type_expr))
    return event_types


def test_build_event_registry_rejects_duplicate_event_types() -> None:
    noop = EventFoldSpec(lambda _snapshot, _event: None)
    with pytest.raises(ValueError, match="Duplicate stage event handler: sprite.show"):
        build_event_registry({"sprite.show": noop}, {"sprite.show": noop})


def test_replay_observed_events_are_registered() -> None:
    assert REPLAY_OBSERVED_EVENTS <= set(STAGE_EVENT_REGISTRY)


def test_backend_registry_matches_frontend_chat_stage_event_union() -> None:
    ts_event_types = _extract_ts_stage_event_types()
    assert len(ts_event_types) >= 58
    assert set(STAGE_EVENT_REGISTRY) == ts_event_types - FRONTEND_ONLY_EVENTS


def test_stage_events_modules_stay_compact() -> None:
    files = [EVENT_SINK_PATH, *sorted(STAGE_EVENTS_DIR.glob("*.py"))]
    assert len(files) >= 10
    for path in files:
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        assert line_count <= 250, f"{path.relative_to(REPO_ROOT)} exceeded 250 lines ({line_count})"


def test_unknown_event_advances_seq_without_mutating_other_fields() -> None:
    snapshot = make_empty_chat_snapshot()
    updated = fold_event_into_snapshot(
        snapshot,
        {"type": "unknown.custom.event", "seq": 17},
    )
    assert updated["eventSeq"] == 17
    assert updated["status"] == "idle"


def test_invalid_snapshot_payload_preserves_seq() -> None:
    snapshot = make_empty_chat_snapshot()
    snapshot["eventSeq"] = 9
    updated = fold_event_into_snapshot(
        snapshot,
        {"type": "snapshot", "seq": 99, "snapshot": "not-a-dict"},
    )
    assert updated["eventSeq"] == 9


def test_project_replay_frame_strips_transitions_and_sets_restore_mode() -> None:
    snapshot = fold_event_into_snapshot(
        make_empty_chat_snapshot(),
        {
            "type": "sprite.show",
            "characterName": "Mio",
            "url": "/api/media?path=mio.png",
            "slot": 1,
            "scale": 1.0,
            "seq": 2,
        },
    )
    snapshot["sprites"][0]["transitions"] = [{"from": "a", "to": "b"}]
    projected = project_replay_frame(snapshot)
    assert projected["sprites"][0]["id"] == "Mio"
    assert projected["sprites"][0]["applyMode"] == "restore"
    assert "transitions" not in projected["sprites"][0]
