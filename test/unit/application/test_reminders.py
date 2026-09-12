from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

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
    assert store.claim() == []
    clock[0] += 61
    second = store.claim()[0]
    assert second["claim_token"] != first["claim_token"]
    assert not store.acknowledge(item["id"], first["claim_token"])["ok"]
    assert store.acknowledge(item["id"], second["claim_token"])["ok"]
    assert store.claim() == []
    assert store.manage("list")["reminders"][0]["status"] == "completed"


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
    assert datetime.fromisoformat(next(item for item in items if item["status"] == "active")["due_at"]).timestamp() > clock[0]
