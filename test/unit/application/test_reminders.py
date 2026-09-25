from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from application.reminders import ReminderStore


@pytest.fixture
def scheduler(tmp_path):
    clock = [datetime(2026, 9, 12, 22, 0).timestamp()]
    return ReminderStore(tmp_path, clock=lambda: clock[0]), clock


def create(store, **kwargs):
    return store.manage("create", ["澪"], character_name="澪", title="休息", message="该休息啦。",
                        **({"delay_minutes": "10"} | kwargs))["reminder"]


def test_persists_and_returns_exact_local_time(scheduler):
    store, clock = scheduler
    item = create(store)
    reopened = ReminderStore(store.path.parent.parent, clock=lambda: clock[0])
    assert reopened.manage("list")["reminders"] == [item]
    assert datetime.fromisoformat(item["due_at"]).timestamp() == clock[0] + 600
    assert not reopened.manage("list")["desktop_connected"]
    assert reopened.claim() == []
    assert reopened.manage("list")["desktop_connected"]


@pytest.mark.parametrize("kwargs", [
    {"delay_minutes": "-1"}, {"delay_minutes": "nan"}, {"delay_minutes": "inf"},
    {"delay_minutes": "0"}, {"recurrence": "hourly"},
    {"remind_at": "2026-09-13T23:00:00"},
    {"delay_minutes": "", "remind_at": "2026-09-11T23:00:00"},
    {"delay_minutes": "", "remind_at": "tomorrow"},
])
def test_rejects_invalid_schedule_without_saving(scheduler, kwargs):
    store, _ = scheduler
    with pytest.raises(ValueError):
        create(store, **kwargs)
    assert store.manage("list")["reminders"] == []


def test_offset_time_and_unknown_character(scheduler):
    store, clock = scheduler
    target = datetime.fromtimestamp(clock[0] + 600).astimezone().isoformat()
    item = create(store, delay_minutes="", remind_at=target)
    assert datetime.fromisoformat(item["due_at"]).timestamp() == clock[0] + 600
    with pytest.raises(ValueError, match="Unknown character"):
        store.manage("create", [], character_name="不存在", title="睡觉", message="晚安", delay_minutes="2")


def test_claim_lease_retry_ack_and_restart_deduplication(scheduler):
    store, clock = scheduler
    item = create(store)
    clock[0] += 600
    first = store.claim()[0]
    assert first["delivery_count"] == 0
    assert store.claim() == []
    clock[0] += 61
    second = store.claim()[0]
    assert second["delivery_count"] == 0
    assert second["claim_token"] != first["claim_token"]
    assert not store.acknowledge(item["id"], first["claim_token"])["ok"]
    assert store.acknowledge(item["id"], second["claim_token"])["ok"]
    assert not store.acknowledge(item["id"], second["claim_token"])["ok"]
    assert store.claim() == []
    assert store.manage("list")["reminders"][0]["status"] == "completed"
    assert store.manage("list")["reminders"][0]["delivery_count"] == 1


def test_concurrent_claims_only_deliver_one_batch(scheduler):
    store, clock = scheduler
    create(store)
    clock[0] += 600
    with ThreadPoolExecutor(max_workers=4) as workers:
        assert sum(len(items) for items in workers.map(lambda _: store.claim(), range(4))) == 1


def test_cancel_and_update_invalidate_claim(scheduler):
    store, clock = scheduler
    item = create(store)
    clock[0] += 600
    claim = store.claim()[0]
    updated = store.manage("update", ["澪"], reminder_id=item["id"], delay_minutes="20")["reminder"]
    assert datetime.fromisoformat(updated["due_at"]).timestamp() == clock[0] + 1200
    assert not store.acknowledge(item["id"], claim["claim_token"])["ok"]
    store.manage("cancel", reminder_id=item["id"])
    clock[0] += 1200
    assert store.claim() == []


@pytest.mark.parametrize("action", ["cancel", "update"])
def test_other_store_invalidates_claim_before_delivery_commit(scheduler, action):
    store, clock = scheduler
    item = create(store)
    clock[0] += 600
    claimed = store.claim()[0]
    other = ReminderStore(store.path.parent.parent, clock=lambda: clock[0])
    changes = {"message": "Updated reminder", "delay_minutes": "1"} if action == "update" else {}
    assert other.manage(action, ["澪"], reminder_id=item["id"], **changes)["ok"]
    assert store.acknowledge(item["id"], claimed["claim_token"]) == {"ok": False}
    clock[0] += 60
    if action == "cancel":
        assert store.claim() == []
    else:
        refreshed = store.claim()[0]
        assert refreshed["message"] == "Updated reminder"
        assert refreshed["claim_token"] != claimed["claim_token"]
        assert store.acknowledge(item["id"], refreshed["claim_token"])["ok"]


@pytest.mark.parametrize("recurrence,days", [("daily", 1), ("weekly", 7)])
def test_recurring_schedule_uses_next_local_occurrence(scheduler, recurrence, days):
    store, clock = scheduler
    item = create(store, recurrence=recurrence)
    clock[0] += 600
    claim = store.claim()[0]
    assert store.acknowledge(item["id"], claim["claim_token"])["ok"]
    updated = store.manage("list")["reminders"][0]
    expected = datetime.fromtimestamp(clock[0]) + timedelta(days=days)
    assert datetime.fromisoformat(updated["due_at"]).timestamp() == expected.timestamp()
    assert updated["status"] == "active"


def test_long_offline_does_not_flood_and_keeps_recurring_schedule(scheduler):
    store, clock = scheduler
    create(store)
    create(store, recurrence="daily")
    clock[0] += 86400 * 90
    assert store.claim() == []
    items = store.manage("list")["reminders"]
    assert {item["status"] for item in items} == {"active", "missed"}
    assert all(item["delivery_count"] == 0 for item in items)
    assert datetime.fromisoformat(next(item for item in items if item["status"] == "active")["due_at"]).timestamp() > clock[0]


def test_random_character_is_selected_per_occurrence_without_rewriting_schedule(scheduler):
    store, clock = scheduler
    item = store.manage("create", ["澪"], character_name="*", title="休息", message="休息一下",
                        delay_minutes="1", recurrence="daily")["reminder"]
    clock[0] += 60
    assert store.claim(character_names=[]) == []
    first = store.claim(character_names=["澪"])[0]
    assert first["character_name"] == "澪"
    assert store.acknowledge(item["id"], first["claim_token"])["ok"]
    saved = store.manage("list")["reminders"][0]
    assert saved["character_name"] == "*"
    clock[0] = datetime.fromisoformat(saved["due_at"]).timestamp()
    assert store.claim(character_names=["新角色"])[0]["character_name"] == "新角色"


def test_delete_removes_schedule_and_invalidates_claim(scheduler):
    store, clock = scheduler
    item = create(store)
    clock[0] += 600
    claim = store.claim()[0]
    assert store.manage("delete", reminder_id=item["id"])["ok"]
    assert not store.acknowledge(item["id"], claim["claim_token"])["ok"]
    assert store.manage("list")["reminders"] == []


def test_random_schedule_rejects_an_empty_character_library(scheduler):
    store, _ = scheduler
    with pytest.raises(ValueError, match="at least one"):
        store.manage("create", [], character_name="*", title="休息", message="休息一下", delay_minutes="1")


def test_delivery_count_survives_restarts_edits_and_recurring_occurrences(scheduler):
    store, clock = scheduler
    item = create(store, recurrence="daily")
    clock[0] += 600
    first = store.claim()[0]
    assert first["delivery_count"] == 0
    assert store.acknowledge(item["id"], first["claim_token"])["ok"]
    reopened = ReminderStore(store.path.parent.parent, clock=lambda: clock[0])
    updated = reopened.manage("update", ["澪"], reminder_id=item["id"], message="休息一下。")["reminder"]
    assert updated["delivery_count"] == 1
    clock[0] = datetime.fromisoformat(updated["due_at"]).timestamp()
    second = reopened.claim()[0]
    assert second["delivery_count"] == 1
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: reopened.acknowledge(item["id"], second["claim_token"]), range(2)))
    assert sum(result["ok"] for result in results) == 1
    assert reopened.manage("list")["reminders"][0]["delivery_count"] == 2


def test_legacy_database_adds_count_without_guessing_previous_deliveries(tmp_path):
    store = ReminderStore(tmp_path)
    store.path.parent.mkdir(parents=True)
    with sqlite3.connect(store.path) as db:
        db.execute("""CREATE TABLE reminders (
            id TEXT PRIMARY KEY, character_name TEXT NOT NULL,
            title TEXT NOT NULL, message TEXT NOT NULL, due_at REAL NOT NULL,
            recurrence TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            claim_token TEXT, claim_until REAL NOT NULL DEFAULT 0,
            created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
        db.execute("""INSERT INTO reminders
            (id, character_name, title, message, due_at, recurrence, status, created_at, updated_at)
            VALUES ('old', '澪', '休息', '晚安', 1800000000, 'once', 'completed', 1799990000, 1800000000)""")
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: ReminderStore(tmp_path).manage("list"), range(2)))
    for result in results:
        assert len(result["reminders"]) == 1
        assert result["reminders"][0]["id"] == "old"
        assert result["reminders"][0]["status"] == "completed"
        assert result["reminders"][0]["delivery_count"] == 0


def test_legacy_migration_is_idempotent_even_after_deletion(scheduler):
    from application.reminders.migration import migrate_bedtime

    store, _ = scheduler
    payload = dict(bedtime_time="23:00", title="睡觉", message="晚安")
    assert migrate_bedtime(store, **payload)["ok"]
    assert migrate_bedtime(store, **payload)["ok"]
    items = store.manage("list")["reminders"]
    assert len(items) == 1
    assert items[0]["character_name"] == "*"
    assert items[0]["recurrence"] == "daily"
    store.manage("delete", reminder_id=items[0]["id"])
    assert migrate_bedtime(store, **payload)["ok"]
    assert store.manage("list")["reminders"] == []


@pytest.mark.parametrize("now,last,expected", [
    ("2026-09-12T23:55:00", None, "2026-09-12T23:50:00"),
    ("2026-09-13T00:10:00", None, "2026-09-12T23:50:00"),
    ("2026-09-13T00:10:00", "2026-09-12", "2026-09-13T23:50:00"),
    ("2026-09-13T01:10:00", None, "2026-09-13T23:50:00"),
])
def test_migration_preserves_grace_window_and_last_delivery(scheduler, now, last, expected):
    from application.reminders.migration import migrate_bedtime

    store, clock = scheduler
    clock[0] = datetime.fromisoformat(now).timestamp()
    migrate_bedtime(store, bedtime_time="23:50", last_delivered_date=last, title="睡觉", message="晚安")
    item = store.manage("list")["reminders"][0]
    assert datetime.fromisoformat(item["due_at"]).timestamp() == datetime.fromisoformat(expected).timestamp()
