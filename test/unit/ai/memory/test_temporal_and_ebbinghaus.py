"""Unit tests for Phase 3 temporal anchoring and Ebbinghaus dual-granularity retention."""

from __future__ import annotations

from datetime import datetime
import math

import pytest

from ai.memory.ebbinghaus import (
    DEFAULT_MAX_OFFLINE_GAP_SECONDS,
    SECONDS_PER_DAY,
    EbbinghausRetentionPolicy,
)
from ai.memory.temporal import (
    format_event_date_tag,
    parse_iso_or_epoch,
    parse_query_time_range,
    resolve_event_timestamp,
)
from sdk.adapters.memory import (
    SCOPE_CHAR_CANON,
    SCOPE_CHAR_CROSS_SAVE,
    MemoryRecord,
    RetentionPolicy,
)


def _local_ts(year: int, month: int, day: int, hour: int = 14, minute: int = 30) -> float:
    return datetime(year, month, day, hour, minute, 0).timestamp()


def _date_str(ts: float | None) -> str:
    assert ts is not None
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def test_parse_iso_or_epoch_handles_seconds_millis_and_date_formats():
    sec = _local_ts(2026, 11, 15, 12, 0)
    assert parse_iso_or_epoch(sec) == pytest.approx(sec)
    assert parse_iso_or_epoch(int(sec * 1000)) == pytest.approx(sec, abs=1.0)
    assert parse_iso_or_epoch("2026-11-15T12:00:00+08:00") is not None
    assert _date_str(parse_iso_or_epoch("2026年11月15日")) == "2026-11-15"
    assert parse_iso_or_epoch(None) is None
    assert parse_iso_or_epoch(True) is None
    assert parse_iso_or_epoch(-5) is None
    assert parse_iso_or_epoch("not-a-date") is None


def test_parse_query_time_range_across_zh_ja_en_relative_and_explicit_dates():
    # Anchor: Wednesday 2026-11-18 15:00 local time
    now_ts = _local_ts(2026, 11, 18, 15, 0)

    # Yesterday / day before yesterday / tomorrow / day after tomorrow
    s, e = parse_query_time_range("我们昨天聊了什么？", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-11-17", "2026-11-17")

    s, e = parse_query_time_range("昨日なに話したっけ？", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-11-17", "2026-11-17")

    s, e = parse_query_time_range("What did we promise yesterday?", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-11-17", "2026-11-17")

    s, e = parse_query_time_range("前天去的餐厅叫什么", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-11-16", "2026-11-16")

    s, e = parse_query_time_range("大前天那本书", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-11-15", "2026-11-15")

    s, e = parse_query_time_range("明天有什么安排", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-11-19", "2026-11-19")

    s, e = parse_query_time_range("后天的电影票", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-11-20", "2026-11-20")

    # Just now -> 4h window
    s, e = parse_query_time_range("刚才你提到哪首歌？", now_ts=now_ts)
    assert s == pytest.approx(now_ts - 4 * 3600.0)
    assert e == pytest.approx(now_ts)

    # N days ago (Chinese numerals & Arabic digits & English)
    s, e = parse_query_time_range("三天前我给你看的照片", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-11-15", "2026-11-15")

    s, e = parse_query_time_range("5 days ago we met at the station", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-11-13", "2026-11-13")

    # Weeks (2026-11-18 is Wednesday -> this week Mon 11-16..Sun 11-22; last week Mon 11-09..Sun 11-15)
    s, e = parse_query_time_range("上周我们约好去哪里？", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-11-09", "2026-11-15")

    s, e = parse_query_time_range("先週の約束覚えてる？", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-11-09", "2026-11-15")

    s, e = parse_query_time_range("下周的旅行计划", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-11-23", "2026-11-29")

    # Months & Year
    s, e = parse_query_time_range("上个月买的吉他", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-10-01", "2026-10-31")

    s, e = parse_query_time_range("去年的花火大会", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2025-01-01", "2025-12-31")

    # Explicit full date, year-month, and month-day with year-boundary wraparound
    s, e = parse_query_time_range("2026年8月15日那天发生了什么", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-08-15", "2026-08-15")

    s, e = parse_query_time_range("2026-09 的账单", now_ts=now_ts)
    assert (_date_str(s), _date_str(e)) == ("2026-09-01", "2026-09-30")

    jan_anchor = _local_ts(2026, 1, 5, 12, 0)
    s, e = parse_query_time_range("12月24日收到的礼物", now_ts=jan_anchor)
    assert (_date_str(s), _date_str(e)) == ("2025-12-24", "2025-12-24")

    # Non-temporal sentence returns (None, None)
    assert parse_query_time_range("你最喜欢喝什么咖啡？", now_ts=now_ts) == (None, None)


def test_resolve_event_timestamp_and_format_tag():
    anchor_iso = "2026-11-15T10:00:00+08:00"
    tomorrow_ts = resolve_event_timestamp("明天", anchor_iso=anchor_iso)
    assert format_event_date_tag(tomorrow_ts) == "2026-11-16"

    explicit_ts = resolve_event_timestamp("2026-12-01", anchor_iso=anchor_iso)
    assert format_event_date_tag(explicit_ts) == "2026-12-01"

    assert resolve_event_timestamp("", anchor_iso=anchor_iso) is None
    assert resolve_event_timestamp(None, anchor_iso=anchor_iso) is None
    assert format_event_date_tag(None) == ""


def test_ebbinghaus_policy_conforms_to_protocol_and_evaluates_clarity_tiers():
    policy = EbbinghausRetentionPolicy()
    assert isinstance(policy, RetentionPolicy)

    t0 = _local_ts(2026, 11, 1, 12, 0)
    rec = MemoryRecord(
        id="mem-ep-1",
        scope=SCOPE_CHAR_CROSS_SAVE,
        owner_id="Mika",
        detail_text="Mika和用户在代官山茑屋书店二楼买了爵士黑胶《Blue Train》",
        gist_text="曾一起在书店买过爵士黑胶",
        kind="episodic",
        importance=0.5,
        recall_count=0,
        created_at=t0,
        event_at=t0,
        last_recalled_at=t0,
    )

    # Verify exact stability math: S_0 = 4.5d, recall_count = 0 -> factor 1.0, importance = 0.5 -> 0.4 + 1.3 = 1.7
    expected_s = 4.5 * SECONDS_PER_DAY * 1.0 * 1.7
    assert policy.stability_seconds(rec) == pytest.approx(expected_s)

    # 1. Recent (2 days later): R = exp(-2 / 7.65) ≈ 0.770 -> clear (injects exact detail_text)
    state_clear = policy.evaluate(rec, now_ts=t0 + 2 * SECONDS_PER_DAY)
    assert state_clear.tier == "clear"
    assert state_clear.retention == pytest.approx(math.exp(-2.0 / 7.65), rel=1e-4)
    assert state_clear.rendered_text.startswith("[清晰·2026-11-01]")
    assert "代官山茑屋书店" in state_clear.rendered_text
    assert "《Blue Train》" in state_clear.rendered_text

    # 2. Medium age (10 days later): R = exp(-10 / 7.65) ≈ 0.270 -> faded (injects gist_text ONLY)
    state_faded = policy.evaluate(rec, now_ts=t0 + 10 * SECONDS_PER_DAY)
    assert state_faded.tier == "faded"
    assert 0.15 <= state_faded.retention < 0.50
    assert state_faded.rendered_text == "[较久远·印象模糊·2026-11-01] 曾一起在书店买过爵士黑胶"
    assert "《Blue Train》" not in state_faded.rendered_text

    # 3. Long ago (20 days later): R = exp(-20 / 7.65) ≈ 0.073 -> dormant
    state_dormant = policy.evaluate(rec, now_ts=t0 + 20 * SECONDS_PER_DAY)
    assert state_dormant.tier == "dormant"
    assert state_dormant.retention < 0.15
    assert state_dormant.rendered_text == "[唤醒的久远记忆·2026-11-01] 曾一起在书店买过爵士黑胶"


def test_ebbinghaus_recall_reinforcement_and_importance_extend_memory_lifespan():
    policy = EbbinghausRetentionPolicy()
    t0 = _local_ts(2026, 10, 1, 12, 0)
    later = t0 + 20 * SECONDS_PER_DAY

    chatter = MemoryRecord(
        id="low",
        scope=SCOPE_CHAR_CROSS_SAVE,
        owner_id="Mika",
        detail_text="中午随口聊了天气不错",
        gist_text="聊过天气",
        kind="episodic",
        importance=0.2,
        recall_count=0,
        created_at=t0,
        last_recalled_at=t0,
    )
    cherished = MemoryRecord(
        id="high",
        scope=SCOPE_CHAR_CROSS_SAVE,
        owner_id="Mika",
        detail_text="约定圣诞节一起去北海道小樽看雪灯之路",
        gist_text="约定圣诞去北海道看雪",
        kind="promise",
        importance=0.95,
        recall_count=8,
        created_at=t0,
        last_recalled_at=t0,
    )

    assert policy.evaluate(chatter, now_ts=later).tier == "dormant"
    cherished_state = policy.evaluate(cherished, now_ts=later)
    assert cherished_state.tier == "clear"
    assert cherished_state.retention > 0.65


def test_ebbinghaus_canon_and_pinned_memories_never_decay():
    policy = EbbinghausRetentionPolicy()
    t0 = _local_ts(2026, 1, 1, 0, 0)
    ten_years_later = t0 + 3650 * SECONDS_PER_DAY

    variants = [
        MemoryRecord(
            id="c1",
            scope=SCOPE_CHAR_CANON,
            owner_id="Mika",
            detail_text="Mika对花生严重过敏",
            created_at=t0,
        ),
        MemoryRecord(
            id="c2",
            scope=SCOPE_CHAR_CROSS_SAVE,
            owner_id="Mika",
            detail_text="用户生日是7月14日",
            pinned=True,
            created_at=t0,
        ),
        MemoryRecord(
            id="c3",
            scope=SCOPE_CHAR_CROSS_SAVE,
            owner_id="Mika",
            detail_text="Mika的妹妹叫Nanami",
            kind="canon",
            created_at=t0,
        ),
    ]
    for rec in variants:
        state = policy.evaluate(rec, now_ts=ten_years_later)
        assert state.tier == "canon"
        assert state.retention == 1.0
        assert state.rendered_text.startswith("[固有设定]")


def test_ebbinghaus_offline_gap_cap_prevents_instant_amnesia_after_long_hiatus():
    policy = EbbinghausRetentionPolicy()
    assert DEFAULT_MAX_OFFLINE_GAP_SECONDS == pytest.approx(7.0 * SECONDS_PER_DAY)

    t0 = _local_ts(2026, 8, 1, 20, 0)
    rec = MemoryRecord(
        id="pre-vacation",
        scope=SCOPE_CHAR_CROSS_SAVE,
        owner_id="Mika",
        detail_text="下线前约定下次上线继续攻略最终迷宫",
        gist_text="约定继续攻略迷宫",
        kind="promise",
        importance=0.6,
        created_at=t0,
        last_recalled_at=t0,
    )
    # User talked 1 day after creation, then went offline for 60 days (total 61 days elapsed)
    now_ts = t0 + 61 * SECONDS_PER_DAY

    # Without offline gap discount, 61 days would drop retention into dormant
    unadjusted = policy.evaluate(rec, now_ts=now_ts, offline_gap_seconds=0.0)
    assert unadjusted.tier == "dormant"

    # With 60-day single-session idle gap, excess beyond 7 days is discounted -> effective elapsed = 8 days!
    discounted = policy.evaluate(
        rec,
        now_ts=now_ts,
        offline_gap_seconds=60 * SECONDS_PER_DAY,
    )
    assert discounted.tier in {"clear", "faded"}
    assert discounted.retention > 0.45
