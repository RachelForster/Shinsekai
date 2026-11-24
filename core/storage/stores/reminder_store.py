"""Unified SQLite reminder repository backed by ``data/shinsekai.db``."""

from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta
import math
import random
import sqlite3
import time
import uuid

from core.storage.sqlite_engine import SqliteEngine
from sdk.adapters.storage import BackendStatus


class UnifiedReminderStore:
    """Manage scheduled character reminders in ``data/shinsekai.db``."""

    def __init__(
        self,
        engine: SqliteEngine,
        *,
        clock=time.time,
        name: str = "reminders.main",
    ) -> None:
        self._engine = engine
        self.clock = clock
        self._name = name
        self.path = engine.path

    @property
    def name(self) -> str:
        return self._name

    def migrate(self) -> None:
        with self._engine.write_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id             TEXT PRIMARY KEY,
                    character_id   TEXT NOT NULL,
                    title          TEXT NOT NULL,
                    message        TEXT NOT NULL,
                    due_at         REAL NOT NULL,
                    recurrence     TEXT NOT NULL,
                    status         TEXT NOT NULL DEFAULT 'active',
                    claim_token    TEXT,
                    claim_until    REAL NOT NULL DEFAULT 0,
                    delivery_count INTEGER NOT NULL DEFAULT 0,
                    created_at     REAL NOT NULL,
                    updated_at     REAL NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON reminders(status, due_at)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS reminder_heartbeat (id INTEGER PRIMARY KEY, seen_at REAL)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS storage_migrations (
                    name        TEXT PRIMARY KEY,
                    applied_at  REAL NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )

    def status(self) -> BackendStatus:
        engine_status = self._engine.status()
        if not engine_status.healthy:
            return BackendStatus(
                name=self._name,
                kind="sqlite",
                location=engine_status.location,
                healthy=False,
                schema_version=engine_status.schema_version,
                detail=engine_status.detail,
            )
        try:
            with self._engine.read_connection() as connection:
                count = int(connection.execute("SELECT COUNT(*) FROM reminders").fetchone()[0])
        except sqlite3.OperationalError as exc:
            return BackendStatus(
                name=self._name,
                kind="sqlite",
                location=engine_status.location,
                healthy=False,
                schema_version=engine_status.schema_version,
                detail=str(exc),
            )
        return BackendStatus(
            name=self._name,
            kind="sqlite",
            location=engine_status.location,
            healthy=True,
            schema_version=engine_status.schema_version,
            detail=f"table=reminders rows={count}",
        )

    def close(self) -> None:
        return None

    @staticmethod
    def public(row: sqlite3.Row) -> dict:
        return {
            key: (
                datetime.fromtimestamp(row[key]).astimezone().isoformat(timespec="seconds")
                if key in {"due_at", "created_at", "updated_at"}
                else row[key]
            )
            for key in row.keys()
            if key not in {"claim_token", "claim_until"}
        }

    @staticmethod
    def text(value: str, name: str, limit: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
            raise ValueError(f"{name} must contain 1–{limit} characters")
        return value.strip()

    def due_time(self, remind_at: str = "", delay_minutes: str = "") -> float:
        if remind_at and str(delay_minutes):
            raise ValueError("Use either remind_at or delay_minutes, not both")
        try:
            if str(delay_minutes):
                minutes = float(delay_minutes)
                if not math.isfinite(minutes) or minutes <= 0 or minutes > 525600:
                    raise ValueError()
                due = self.clock() + minutes * 60
            else:
                if not isinstance(remind_at, str) or ("T" not in remind_at and " " not in remind_at):
                    raise ValueError()
                due = datetime.fromisoformat(remind_at).timestamp()
            if not math.isfinite(due) or due <= self.clock():
                raise ValueError()
        except (ValueError, TypeError, OverflowError, OSError):
            raise ValueError(
                "Provide a future ISO datetime (local time unless offset supplied), or delay_minutes > 0"
            ) from None
        return due

    @staticmethod
    def next_due(due: float, recurrence: str, now: float) -> float:
        days = 1 if recurrence == "daily" else 7
        local = datetime.fromtimestamp(due)
        jump = max(1, (datetime.fromtimestamp(now).date() - local.date()).days // days)
        candidate = local + timedelta(days=jump * days)
        while candidate.timestamp() <= now:
            candidate += timedelta(days=days)
        return candidate.timestamp()

    @staticmethod
    def _select_base_sql(where_clause: str = "", order_clause: str = "") -> str:
        return (
            "SELECT r.*, COALESCE(c.name, r.character_id) AS character_name "
            "FROM reminders r "
            "LEFT JOIN characters c ON c.id = r.character_id "
            f"{where_clause} {order_clause}"
        )

    @staticmethod
    def _resolve_character_id(db: sqlite3.Connection, character_name: str) -> str:
        if character_name == "*":
            return "*"
        row = db.execute(
            "SELECT id FROM characters WHERE name = ? COLLATE NOCASE LIMIT 1",
            (character_name,),
        ).fetchone()
        if row is not None:
            return str(row["id"])
        return character_name

    def manage(
        self,
        action: str,
        character_names=(),
        reminder_id: str = "",
        character_name: str = "",
        title: str = "",
        message: str = "",
        remind_at: str = "",
        delay_minutes: str = "",
        recurrence: str = "",
    ) -> dict:
        now = self.clock()
        if action == "list":
            with self._engine.read_connection() as db:
                rows = db.execute(
                    self._select_base_sql(
                        order_clause="ORDER BY CASE r.status WHEN 'active' THEN 0 ELSE 1 END, r.due_at"
                    )
                ).fetchall()
                heartbeat = db.execute(
                    "SELECT seen_at FROM reminder_heartbeat WHERE id=1"
                ).fetchone()
            return {
                "ok": True,
                "now": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"),
                "desktop_connected": bool(heartbeat and 0 <= now - heartbeat[0] < 60),
                "reminders": [self.public(row) for row in rows],
                "delivery_note": (
                    "Desktop app must stay running. Reminders over 30 minutes late are missed; "
                    "recurring schedules advance to the next occurrence."
                ),
            }
        if action not in {"create", "update", "cancel", "delete"}:
            raise ValueError("action must be list, create, update, cancel or delete")
        with self._engine.write_connection() as db:
            old = None
            if action != "create":
                old = db.execute(
                    self._select_base_sql(where_clause="WHERE r.id = ?"),
                    (reminder_id,),
                ).fetchone()
                if not old:
                    raise ValueError("Reminder not found")
                if action == "delete":
                    db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
                    return {"ok": True}
                if action == "cancel":
                    db.execute(
                        "UPDATE reminders SET status='cancelled', claim_token=NULL, claim_until=0, updated_at=? WHERE id=?",
                        (now, reminder_id),
                    )
                    refreshed = db.execute(
                        self._select_base_sql(where_clause="WHERE r.id = ?"),
                        (reminder_id,),
                    ).fetchone()
                    return {"ok": True, "reminder": self.public(refreshed)}
                if old["status"] != "active":
                    raise ValueError("Only active reminders can be updated; create a new reminder instead")
            values = dict(old) if old else {"id": uuid.uuid4().hex, "recurrence": "once", "created_at": now}
            for key, value, limit in [
                ("character_name", character_name, 120),
                ("title", title, 120),
                ("message", message, 2000),
            ]:
                if value or not old:
                    values[key] = self.text(value, key, limit)
            if values["character_name"] == "*":
                if not character_names:
                    raise ValueError("Random reminders require at least one configured character")
            elif values["character_name"] not in character_names:
                raise ValueError(
                    "Unknown character_name; use an existing character's exact name or * for random"
                )
            if recurrence:
                values["recurrence"] = recurrence
            if values["recurrence"] not in {"once", "daily", "weekly"}:
                raise ValueError("recurrence must be once, daily or weekly")
            if remind_at or str(delay_minutes) or not old:
                values["due_at"] = self.due_time(remind_at, delay_minutes)
            char_id = self._resolve_character_id(db, values["character_name"])
            db.execute(
                """
                INSERT INTO reminders(
                    id, character_id, title, message, due_at, recurrence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    character_id=excluded.character_id,
                    title=excluded.title,
                    message=excluded.message,
                    due_at=excluded.due_at,
                    recurrence=excluded.recurrence,
                    updated_at=excluded.updated_at,
                    claim_token=NULL,
                    claim_until=0
                """,
                (
                    values["id"],
                    char_id,
                    values["title"],
                    values["message"],
                    values["due_at"],
                    values["recurrence"],
                    values["created_at"],
                    now,
                ),
            )
            saved = db.execute(
                self._select_base_sql(where_clause="WHERE r.id = ?"),
                (values["id"],),
            ).fetchone()
            return {
                "ok": True,
                "reminder": self.public(saved),
                "delivery_note": "Saved. Delivery requires the Shinsekai desktop app to remain running, including in the tray.",
            }

    def claim(self, character_names=()) -> list[dict]:
        now = self.clock()
        result: list[dict] = []
        with self._engine.write_connection() as db:
            db.execute("INSERT OR REPLACE INTO reminder_heartbeat VALUES(1, ?)", (now,))
            rows = db.execute(
                self._select_base_sql(
                    where_clause="WHERE r.status='active' AND r.due_at<=? AND r.claim_until<=?",
                    order_clause="ORDER BY r.due_at LIMIT 100",
                ),
                (now, now),
            ).fetchall()
            for row in rows:
                if now - row["due_at"] > 1800:
                    if row["recurrence"] == "once":
                        db.execute(
                            "UPDATE reminders SET status='missed', updated_at=?, claim_token=NULL, claim_until=0 WHERE id=?",
                            (now, row["id"]),
                        )
                    else:
                        db.execute(
                            "UPDATE reminders SET due_at=?, updated_at=?, claim_token=NULL, claim_until=0 WHERE id=?",
                            (self.next_due(row["due_at"], row["recurrence"], now), now, row["id"]),
                        )
                    continue
                if len(result) >= 5:
                    break
                resolved_name = row["character_name"]
                if row["character_id"] == "*" or resolved_name == "*":
                    if not character_names:
                        continue
                    resolved_name = random.choice(character_names)
                token = uuid.uuid4().hex
                db.execute(
                    "UPDATE reminders SET claim_token=?, claim_until=? WHERE id=?",
                    (token, now + 60, row["id"]),
                )
                result.append({**self.public(row), "character_name": resolved_name, "claim_token": token})
        return result

    def acknowledge(self, reminder_id: str, claim_token: str) -> dict:
        now = self.clock()
        with self._engine.write_connection() as db:
            row = db.execute(
                "SELECT * FROM reminders WHERE id=? AND claim_token=? AND status='active'",
                (reminder_id, claim_token),
            ).fetchone()
            if not row:
                return {"ok": False}
            due = (
                row["due_at"]
                if row["recurrence"] == "once"
                else self.next_due(row["due_at"], row["recurrence"], now)
            )
            status = "completed" if row["recurrence"] == "once" else "active"
            db.execute(
                "UPDATE reminders SET status=?, due_at=?, claim_token=NULL, claim_until=0, "
                "updated_at=?, delivery_count=delivery_count+1 WHERE id=?",
                (status, due, now, reminder_id),
            )
        return {"ok": True}

    def migrate_bedtime(
        self,
        *,
        bedtime_time: str,
        last_delivered_date: str | None = None,
        title: str,
        message: str,
    ) -> dict:
        if not isinstance(bedtime_time, str) or len(bedtime_time) != 5:
            raise ValueError("Invalid legacy bedtime")
        scheduled_time = dt_time.fromisoformat(bedtime_time)
        last = date.fromisoformat(last_delivered_date) if last_delivered_date else None
        cleaned_title = self.text(title, "title", 120)
        cleaned_message = self.text(message, "message", 2000)
        now = self.clock()
        today = datetime.fromtimestamp(now).date()
        due = datetime.combine(today, scheduled_time)
        yesterday = due - timedelta(days=1)
        if 0 <= now - yesterday.timestamp() <= 1800:
            due = yesterday
        if last and last >= due.date():
            due = datetime.combine(last + timedelta(days=1), scheduled_time)
        if now - due.timestamp() > 1800:
            due = datetime.combine(today, scheduled_time)
            if now - due.timestamp() > 1800:
                due += timedelta(days=1)
        with self._engine.write_connection() as db:
            done = db.execute(
                "SELECT 1 FROM storage_migrations WHERE name IN ('reminder_native_bedtime', 'native-bedtime') LIMIT 1"
            ).fetchone()
            if done is not None:
                return {"ok": True}
            db.execute(
                """
                INSERT OR IGNORE INTO reminders(
                    id, character_id, title, message, due_at, recurrence, created_at, updated_at
                ) VALUES ('legacy-bedtime', '*', ?, ?, ?, 'daily', ?, ?)
                """,
                (cleaned_title, cleaned_message, due.timestamp(), now, now),
            )
            db.execute(
                "INSERT OR IGNORE INTO storage_migrations(name, applied_at, detail_json) VALUES ('reminder_native_bedtime', ?, '{}')",
                (now,),
            )
        return {"ok": True}


__all__ = ["UnifiedReminderStore"]
