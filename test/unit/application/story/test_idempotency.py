from __future__ import annotations

import pytest

from application.story import (
    StoryCommandConflictError,
    StoryCommandIdempotencyIndex,
)
from core.story import CompleteNode, EnterNode


def test_same_command_and_payload_returns_original_record() -> None:
    command = EnterNode("command-1", 3, "gate")
    index = StoryCommandIdempotencyIndex()
    first = index.record(
        command,
        accepted=True,
        resulting_revision=4,
        event_ids=("event-4-9",),
        ack={"revision": 4},
    )

    duplicate = index.record(
        command,
        accepted=False,
        resulting_revision=99,
        event_ids=(),
        ack={"revision": 99},
    )

    assert duplicate is first
    assert index.lookup(command) is first
    assert duplicate.ack == {"revision": 4}


def test_same_command_id_with_different_payload_is_rejected() -> None:
    index = StoryCommandIdempotencyIndex()
    index.record(
        EnterNode("command-1", 3, "gate"),
        accepted=True,
        resulting_revision=4,
        event_ids=("event-4-9",),
        ack={"revision": 4},
    )

    with pytest.raises(StoryCommandConflictError):
        index.lookup(CompleteNode("command-1", 3, "gate"))


def test_index_evicts_only_after_configured_bound() -> None:
    index = StoryCommandIdempotencyIndex(max_entries=2)
    for number in range(3):
        command = EnterNode(f"command-{number}", number, "gate")
        index.record(
            command,
            accepted=True,
            resulting_revision=number + 1,
            event_ids=(),
            ack={},
        )

    assert set(index.records) == {"command-1", "command-2"}
