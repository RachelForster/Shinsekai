"""Single-writer SQLite storage and transactions for Agent records."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def encode(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


class AgentStore:
    """Own a database until close; the OS releases the lease after a crash.

    This class provides storage mechanics only. The caller decides transitions
    and commits snapshots, events and deduplication records in one transaction.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._lease = self.path.with_suffix(self.path.suffix + ".owner").open("a+b")
        try:
            self._lease.seek(0, 2)
            if not self._lease.tell():
                self._lease.write(b"0")
                self._lease.flush()
            self._lease.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lease.close()
            raise RuntimeError("Agent database already has an owner") from exc
        try:
            self.connection = sqlite3.connect(
                self.path, check_same_thread=False, isolation_level=None
            )
            self.connection.row_factory = sqlite3.Row
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError(f"Unsupported Agent database schema: {version}")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            self.connection.execute("PRAGMA busy_timeout=5000")
            self.connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL, id TEXT NOT NULL, document TEXT NOT NULL,
                    PRIMARY KEY (kind, id)
                );
                CREATE TABLE IF NOT EXISTS requests (
                    caller TEXT NOT NULL, request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, task_id TEXT NOT NULL,
                    PRIMARY KEY (caller, request_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    task_id TEXT NOT NULL, seq INTEGER NOT NULL, document TEXT NOT NULL,
                    PRIMARY KEY (task_id, seq)
                );
                CREATE TABLE IF NOT EXISTS worker_events (
                    attempt_id TEXT NOT NULL, seq INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                    PRIMARY KEY (attempt_id, seq)
                );
                CREATE TABLE IF NOT EXISTS tool_calls (
                    task_id TEXT NOT NULL, call_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    name TEXT NOT NULL, effect_kind TEXT NOT NULL, result TEXT,
                    PRIMARY KEY (task_id, call_id)
                );
                PRAGMA user_version=1;
                COMMIT;
            """
            )
        except BaseException:
            if hasattr(self, "connection"):
                self.connection.close()
            self._lease.close()
            raise

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.connection.execute("COMMIT")
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise

    def get(self, kind: str, key: str) -> dict | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT document FROM records WHERE kind=? AND id=?", (kind, key)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def put(self, kind: str, key: str, document: dict) -> None:
        with self._lock:
            self.connection.execute(
                "INSERT INTO records VALUES (?,?,?) ON CONFLICT(kind,id) "
                "DO UPDATE SET document=excluded.document",
                (kind, key, encode(document)),
            )

    def records(self, kind: str) -> list[dict]:
        with self._lock:
            return [
                json.loads(row[0])
                for row in self.connection.execute(
                    "SELECT document FROM records WHERE kind=? ORDER BY rowid", (kind,)
                )
            ]

    def find_request(self, caller: str, request_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self.connection.execute(
                "SELECT * FROM requests WHERE caller=? AND request_id=?",
                (caller, request_id),
            ).fetchone()

    def save_request(
        self, caller: str, request_id: str, fingerprint: str, task_id: str
    ) -> None:
        self.connection.execute(
            "INSERT INTO requests VALUES (?,?,?,?)",
            (caller, request_id, fingerprint, task_id),
        )

    def append_event(self, task_id: str, document: dict) -> int:
        seq = self.connection.execute(
            "SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE task_id=?", (task_id,)
        ).fetchone()[0]
        self.connection.execute(
            "INSERT INTO events VALUES (?,?,?)",
            (task_id, seq, encode({**document, "eventSeq": seq})),
        )
        return seq

    def read_events(self, task_id: str, after_seq: int, limit: int) -> list[dict]:
        with self._lock:
            return [
                json.loads(row[0])
                for row in self.connection.execute(
                    "SELECT document FROM events WHERE task_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (task_id, after_seq, limit),
                )
            ]

    def record_worker_event(self, attempt_id: str, seq: int, fingerprint: str) -> bool:
        row = self.connection.execute(
            "SELECT fingerprint FROM worker_events WHERE attempt_id=? AND seq=?",
            (attempt_id, seq),
        ).fetchone()
        if row:
            if row[0] != fingerprint:
                raise ValueError("Worker reused a sequence for different content")
            return False
        last = self.connection.execute(
            "SELECT COALESCE(MAX(seq),0) FROM worker_events WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()[0]
        if seq <= last:
            raise ValueError("Worker event sequence went backwards")
        self.connection.execute(
            "INSERT INTO worker_events VALUES (?,?,?)", (attempt_id, seq, fingerprint)
        )
        return True

    def tool_call(self, task_id: str, call_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self.connection.execute(
                "SELECT * FROM tool_calls WHERE task_id=? AND call_id=?",
                (task_id, call_id),
            ).fetchone()

    def begin_tool(
        self, task_id: str, call_id: str, fingerprint: str, name: str, effect_kind: str
    ) -> None:
        self.connection.execute(
            "INSERT INTO tool_calls VALUES (?,?,?,?,?,NULL)",
            (task_id, call_id, fingerprint, name, effect_kind),
        )

    def finish_tool(self, task_id: str, call_id: str, result: dict) -> None:
        self.connection.execute(
            "UPDATE tool_calls SET result=? WHERE task_id=? AND call_id=?",
            (encode(result), task_id, call_id),
        )

    def tool_calls(self, task_id: str) -> list[sqlite3.Row]:
        with self._lock:
            return self.connection.execute(
                "SELECT * FROM tool_calls WHERE task_id=? ORDER BY rowid", (task_id,)
            ).fetchall()

    def close(self) -> None:
        with self._lock:
            self.connection.close()
            self._lease.close()
