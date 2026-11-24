"""Data models, DDL, and journal codecs for session behavior state snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Literal

from sdk.file_io import durable_rename

BEHAVIOR_TURN_JOURNAL_FILENAME = "behavior-turn-journal.json"

_BEHAVIOR_STATE_DDL = """
CREATE TABLE IF NOT EXISTS session_state_snapshots (
    branch_id      TEXT NOT NULL,
    turn_seq       INTEGER NOT NULL,
    behavior_id    TEXT NOT NULL,
    state_version  INTEGER NOT NULL,
    state_json     TEXT NOT NULL,
    created_at_ms  INTEGER NOT NULL,
    PRIMARY KEY (branch_id, turn_seq)
);

CREATE INDEX IF NOT EXISTS idx_state_snapshots_branch_ver
    ON session_state_snapshots (branch_id, state_version DESC);
"""


def ensure_behavior_state_schema(conn: sqlite3.Connection) -> None:
    """Create session behavior snapshot tables and indexes if missing."""
    conn.executescript(_BEHAVIOR_STATE_DDL)


class BehaviorVersionConflictError(RuntimeError):
    """Raised when optimistic concurrency control detects a stale state version."""

    def __init__(
        self,
        expected_version: int,
        actual_version: int | None,
        *,
        branch_id: str = "main",
    ) -> None:
        self.expected_version = expected_version
        self.actual_version = actual_version
        self.branch_id = branch_id
        super().__init__(
            f"State version conflict on branch {branch_id!r}: "
            f"expected {expected_version}, got {actual_version}"
        )


@dataclass(frozen=True)
class BehaviorStateSnapshot:
    branch_id: str
    turn_seq: int
    behavior_id: str
    state_version: int
    state: dict[str, Any]
    created_at_ms: int


@dataclass(frozen=True)
class BehaviorCommitResult:
    snapshot: BehaviorStateSnapshot
    appended_turn_seqs: tuple[int, ...] = ()


@dataclass(frozen=True)
class BehaviorTurnJournalRecord:
    journal_id: str
    branch_id: str
    behavior_id: str
    base_turn_seq: int
    base_state_version: int
    next_state_version: int
    created_at_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "journalId": self.journal_id,
            "branchId": self.branch_id,
            "behaviorId": self.behavior_id,
            "baseTurnSeq": self.base_turn_seq,
            "baseStateVersion": self.base_state_version,
            "nextStateVersion": self.next_state_version,
            "createdAtMs": self.created_at_ms,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BehaviorTurnJournalRecord:
        return cls(
            journal_id=str(data["journalId"]),
            branch_id=str(data["branchId"]),
            behavior_id=str(data["behaviorId"]),
            base_turn_seq=int(data["baseTurnSeq"]),
            base_state_version=int(data["baseStateVersion"]),
            next_state_version=int(data["nextStateVersion"]),
            created_at_ms=int(data["createdAtMs"]),
        )


@dataclass(frozen=True)
class BehaviorRecoveryReport:
    action: Literal["none", "finalized", "rolled_back", "cleaned_noop"]
    branch_id: str | None = None
    restored_snapshot: BehaviorStateSnapshot | None = None


def normalize_branch_id(branch_id: str) -> str:
    return str(branch_id or "main").strip() or "main"


def row_to_behavior_snapshot(row: Any) -> BehaviorStateSnapshot:
    raw = str(row["state_json"] or "{}")
    parsed = json.loads(raw)
    state = dict(parsed) if isinstance(parsed, Mapping) else {}
    return BehaviorStateSnapshot(
        branch_id=str(row["branch_id"]),
        turn_seq=int(row["turn_seq"]),
        behavior_id=str(row["behavior_id"]),
        state_version=int(row["state_version"]),
        state=state,
        created_at_ms=int(row["created_at_ms"]),
    )


def atomic_write_journal(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".behavior-journal-", suffix=".tmp", dir=path.parent
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        durable_rename(tmp_path, path, replace=True)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


__all__ = [
    "BEHAVIOR_TURN_JOURNAL_FILENAME",
    "BehaviorCommitResult",
    "BehaviorRecoveryReport",
    "BehaviorStateSnapshot",
    "BehaviorTurnJournalRecord",
    "BehaviorVersionConflictError",
    "atomic_write_journal",
    "ensure_behavior_state_schema",
    "normalize_branch_id",
    "row_to_behavior_snapshot",
]
