"""Application-owned idempotency records for story commands."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from types import MappingProxyType
from typing import Any

from core.story.compiler import canonical_json
from core.story.state import freeze_mapping


class StoryCommandConflictError(ValueError):
    """Raised when one command ID is reused with a different payload."""


def story_command_payload_hash(command: Any) -> str:
    payload = {
        "type": type(command).__name__,
        "payload": command,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class StoryCommandRecord:
    command_id: str
    payload_hash: str
    accepted: bool
    resulting_revision: int
    event_ids: tuple[str, ...]
    ack: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_ids", tuple(self.event_ids))
        object.__setattr__(self, "ack", freeze_mapping(self.ack))


class StoryCommandIdempotencyIndex:
    """Bounded branch-local command result index persisted by application."""

    def __init__(self, *, max_entries: int = 256) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self._records: dict[str, StoryCommandRecord] = {}
        self._order: list[str] = []

    @property
    def records(self) -> Mapping[str, StoryCommandRecord]:
        return MappingProxyType(dict(self._records))

    def lookup(self, command: Any) -> StoryCommandRecord | None:
        command_id = self._command_id(command)
        existing = self._records.get(command_id)
        if existing is None:
            return None
        self._require_same_payload(existing, story_command_payload_hash(command))
        return existing

    def record(
        self,
        command: Any,
        *,
        accepted: bool,
        resulting_revision: int,
        event_ids: tuple[str, ...],
        ack: Mapping[str, Any],
    ) -> StoryCommandRecord:
        command_id = self._command_id(command)
        payload_hash = story_command_payload_hash(command)
        existing = self._records.get(command_id)
        if existing is not None:
            self._require_same_payload(existing, payload_hash)
            return existing
        record = StoryCommandRecord(
            command_id=command_id,
            payload_hash=payload_hash,
            accepted=accepted,
            resulting_revision=resulting_revision,
            event_ids=event_ids,
            ack=ack,
        )
        self._records[command_id] = record
        self._order.append(command_id)
        while len(self._order) > self.max_entries:
            removed = self._order.pop(0)
            self._records.pop(removed, None)
        return record

    @staticmethod
    def _command_id(command: Any) -> str:
        command_id = getattr(command, "command_id", None)
        if not isinstance(command_id, str) or not command_id:
            raise ValueError("command must have a non-empty command_id")
        return command_id

    @staticmethod
    def _require_same_payload(
        existing: StoryCommandRecord,
        payload_hash: str,
    ) -> None:
        if existing.payload_hash != payload_hash:
            raise StoryCommandConflictError(
                f"command {existing.command_id!r} was reused with another payload"
            )
