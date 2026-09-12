"""Persistent local reminders shared by character tools and the desktop bridge."""

import math
import os
import random
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from config.config_manager import ConfigManager


def manage_character_reminders(request: dict[str, str]) -> dict:
    """Resolve available characters and commit a tool-requested schedule."""
    try:
        return ReminderStore().manage(
            character_names=[character.name for character in ConfigManager().config.characters],
            **request,
        )
    except (ValueError, OSError, sqlite3.Error) as error:
        return {"ok": False, "error": str(error)}


class ReminderStore:
    def __init__(self, project_root=None, clock=time.time):
        root = project_root or os.environ.get("SHINSEKAI_PROJECT_ROOT") or os.environ.get("EASYAI_PROJECT_ROOT") or os.getcwd()
        self.path = Path(root) / "data" / "reminders.sqlite3"
        self.clock = clock

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY, character_name TEXT NOT NULL,
                title TEXT NOT NULL, message TEXT NOT NULL, due_at REAL NOT NULL,
                recurrence TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
                claim_token TEXT, claim_until REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
            db.execute("CREATE TABLE IF NOT EXISTS heartbeat (id INTEGER PRIMARY KEY, seen_at REAL)")
            db.commit()
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def public(row):
        return {key: (datetime.fromtimestamp(row[key]).astimezone().isoformat(timespec="seconds")
                      if key in {"due_at", "created_at", "updated_at"} else row[key])
                for key in row.keys() if key not in {"claim_token", "claim_until"}}

    @staticmethod
    def text(value, name, limit):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
            raise ValueError(f"{name} must contain 1–{limit} characters")
        return value.strip()

    def due_time(self, remind_at="", delay_minutes=""):
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
            raise ValueError("Provide a future ISO datetime (local time unless offset supplied), or delay_minutes > 0") from None
        return due

    def manage(self, action, character_names=(), reminder_id="", character_name="", title="", message="",
               remind_at="", delay_minutes="", recurrence=""):
        now = self.clock()
        if action == "list":
            with self.connect() as db:
                rows = db.execute("SELECT * FROM reminders ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, due_at").fetchall()
                heartbeat = db.execute("SELECT seen_at FROM heartbeat WHERE id=1").fetchone()
            return {"ok": True, "now": datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds"),
                    "desktop_connected": bool(heartbeat and 0 <= now - heartbeat[0] < 60),
                    "reminders": [self.public(row) for row in rows],
                    "delivery_note": "Desktop app must stay running. Reminders over 30 minutes late are missed; recurring schedules advance to the next occurrence."}
        if action not in {"create", "update", "cancel", "delete"}:
            raise ValueError("action must be list, create, update, cancel or delete")
        with self.connect() as db:
            old = None
            if action != "create":
                old = db.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone()
                if not old:
                    raise ValueError("Reminder not found")
                if action == "delete":
                    db.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
                    return {"ok": True}
                if action == "cancel":
                    db.execute("UPDATE reminders SET status='cancelled', claim_token=NULL, claim_until=0, updated_at=? WHERE id=?", (now, reminder_id))
                    return {"ok": True, "reminder": self.public(db.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,)).fetchone())}
                if old["status"] != "active":
                    raise ValueError("Only active reminders can be updated; create a new reminder instead")
            values = dict(old) if old else {"id": uuid.uuid4().hex, "recurrence": "once", "created_at": now}
            for key, value, limit in [("character_name", character_name, 120), ("title", title, 120), ("message", message, 2000)]:
                if value or not old:
                    values[key] = self.text(value, key, limit)
            if values["character_name"] == "*":
                if not character_names:
                    raise ValueError("Random reminders require at least one configured character")
            elif values["character_name"] not in character_names:
                raise ValueError("Unknown character_name; use an existing character's exact name or * for random")
            if recurrence:
                values["recurrence"] = recurrence
            if values["recurrence"] not in {"once", "daily", "weekly"}:
                raise ValueError("recurrence must be once, daily or weekly")
            if remind_at or str(delay_minutes) or not old:
                values["due_at"] = self.due_time(remind_at, delay_minutes)
            db.execute("""INSERT INTO reminders(id,character_name,title,message,due_at,recurrence,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                character_name=excluded.character_name,title=excluded.title,message=excluded.message,
                due_at=excluded.due_at,recurrence=excluded.recurrence,updated_at=excluded.updated_at,
                claim_token=NULL,claim_until=0""",
                tuple(values[k] for k in ["id", "character_name", "title", "message", "due_at", "recurrence", "created_at"]) + (now,))
            return {"ok": True, "reminder": self.public(db.execute("SELECT * FROM reminders WHERE id=?", (values["id"],)).fetchone()),
                    "delivery_note": "Saved. Delivery requires the Shinsekai desktop app to remain running, including in the tray."}

    @staticmethod
    def next_due(due, recurrence, now):
        # Use local wall time across DST changes rather than fixed UTC seconds.
        days = 1 if recurrence == "daily" else 7
        local = datetime.fromtimestamp(due)
        jump = max(1, (datetime.fromtimestamp(now).date() - local.date()).days // days)
        candidate = local + timedelta(days=jump * days)
        while candidate.timestamp() <= now:
            candidate += timedelta(days=days)
        return candidate.timestamp()

    def claim(self, character_names=()):
        now = self.clock()
        result = []
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO heartbeat VALUES(1,?)", (now,))
            rows = db.execute("SELECT * FROM reminders WHERE status='active' AND due_at<=? AND claim_until<=? ORDER BY due_at LIMIT 100", (now, now)).fetchall()
            for row in rows:
                if now - row["due_at"] > 1800:
                    if row["recurrence"] == "once":
                        db.execute("UPDATE reminders SET status='missed',updated_at=?,claim_token=NULL,claim_until=0 WHERE id=?", (now, row["id"]))
                    else:
                        db.execute("UPDATE reminders SET due_at=?,updated_at=?,claim_token=NULL,claim_until=0 WHERE id=?", (self.next_due(row["due_at"], row["recurrence"], now), now, row["id"]))
                    continue
                if len(result) >= 5:
                    break
                character_name = row["character_name"]
                if character_name == "*":
                    if not character_names:
                        continue
                    character_name = random.choice(character_names)
                token = uuid.uuid4().hex
                db.execute("UPDATE reminders SET claim_token=?,claim_until=? WHERE id=?", (token, now + 60, row["id"]))
                result.append({**self.public(row), "character_name": character_name, "claim_token": token})
        return result

    def acknowledge(self, reminder_id, claim_token):
        now = self.clock()
        with self.connect() as db:
            row = db.execute("SELECT * FROM reminders WHERE id=? AND claim_token=? AND status='active'", (reminder_id, claim_token)).fetchone()
            if not row:
                return {"ok": False}
            due = row["due_at"] if row["recurrence"] == "once" else self.next_due(row["due_at"], row["recurrence"], now)
            status = "completed" if row["recurrence"] == "once" else "active"
            db.execute("UPDATE reminders SET status=?,due_at=?,claim_token=NULL,claim_until=0,updated_at=? WHERE id=?", (status, due, now, reminder_id))
        return {"ok": True}
