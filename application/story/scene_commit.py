"""Commit a scene reply, its history and optional node advance as one document."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, TYPE_CHECKING

from core.story import AdvanceStoryTurn

from .idempotency import StoryCommandIdempotencyIndex

if TYPE_CHECKING:
    from .session import SceneTurnCommand, StoryBranch, StorySession, StorySessionAck


@dataclass
class SceneTurnCommit:
    command: SceneTurnCommand
    payload: Mapping[str, Any]
    history_entries: Sequence[Mapping[str, Any]] | None
    user_name: str
    committed: bool = False

    def record(self, branch: StoryBranch, ack: StorySessionAck) -> None:
        payload = {
            **self.payload,
            "revision": ack.revision,
            "presentationEvents": [
                *self.payload.get("presentationEvents", ()),
                *[dict(item) for item in ack.presentation_events],
            ],
        }
        entries = self.history_entries
        if entries is None:
            entries = scene_turn_history(
                branch.history_entries, self.command, payload, self.user_name
            )
        branch.history_entries = tuple(MappingProxyType(dict(item)) for item in entries)
        branch.idempotency.record(
            self.command,
            accepted=True,
            resulting_revision=ack.revision,
            event_ids=ack.event_ids,
            ack={"sceneTurn": payload},
        )


def scene_turn_history(
    entries: Sequence[Mapping[str, Any]],
    command: SceneTurnCommand,
    payload: Mapping[str, Any],
    user_name: str,
) -> list[dict[str, Any]]:
    history = [dict(item) for item in entries]
    history.append(
        {
            "id": f"scene:{command.command_id}:user",
            "revertUserIndex": sum(item.get("role") == "user" for item in history),
            "role": "user",
            "text": f"{user_name}: {command.text}",
            "message": {"role": "user", "content": command.text},
        }
    )
    for index, item in enumerate(payload.get("dialogue", ())):
        speaker = item["characterId"]
        history.append(
            {
                "id": f"scene:{command.command_id}:dialog:{index}",
                "role": "system"
                if speaker.upper() in {"NARR", "SYSTEM"}
                else "assistant",
                "text": f"{speaker}: {item['text']}",
                "message": {
                    "role": "assistant",
                    "name": speaker,
                    "content": item["text"],
                },
            }
        )
    return history


def commit_scene_turn(
    session: StorySession,
    command: SceneTurnCommand,
    *,
    result_payload: Mapping[str, Any],
    history_entries: Sequence[Mapping[str, Any]] | None,
    advance_command: AdvanceStoryTurn | None,
    user_name: str,
) -> Mapping[str, Any]:
    """Caller holds the session lock. Only the final snapshot is written."""
    previous = session.active_branch
    existing = previous.idempotency.lookup(command)
    if existing is not None:
        return existing.ack
    result = None
    if advance_command is not None:
        result = session.runtime.execute(
            previous.state,
            advance_command,
            global_variables=session.global_progress.variables,
        )
        result = session._prepare_runtime_result(previous.state, result)
    branch = replace(
        previous,
        events=list(previous.events),
        checkpoints=list(previous.checkpoints),
        idempotency=StoryCommandIdempotencyIndex.from_payload(
            previous.idempotency.to_payload(),
            max_entries=previous.idempotency.max_entries,
        ),
    )
    commit = SceneTurnCommit(command, result_payload, history_entries, user_name)
    previous_outbox = list(session.outbox)
    session.branches[branch.id] = branch
    try:
        session._commit_result(
            branch,
            advance_command or command,
            result.events if result else (),
            result.global_effects if result else (),
            state=result.state if result else branch.state,
            cast_plans=result.cast_plans if result else (),
            scene_turn=commit,
        )
    except BaseException:
        # A failed write must not leave a half-committed in-memory session.
        # Once saved, outbox/callback failures must retain the original reply.
        if not commit.committed:
            session.branches[branch.id] = previous
            session.outbox = previous_outbox
        raise
    return branch.idempotency.lookup(command).ack
