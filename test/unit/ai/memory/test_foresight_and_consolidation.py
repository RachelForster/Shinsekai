"""Unit tests for EverMemOS Bi-Temporal Foresight TTL, DREAM relational tier, and MemScenes consolidation."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pytest

from ai.memory import operations
from ai.memory.backends.in_memory import DeterministicHashEmbedder
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
from ai.memory.ebbinghaus import (
    EbbinghausRetentionPolicy,
    SECONDS_PER_DAY,
    is_foresight_expired,
)
from ai.memory.engine import HybridMemoryEngine
from ai.memory.extraction import parse_memory_drafts
from ai.memory.hooks import MemoryAutoHooks
from ai.memory.metadata_tags import pack_system_tags, unpack_system_tags
from ai.memory.orchestrator import MemoryOrchestrator
from ai.memory.queue import MemoryWriteQueue
from ai.memory.temporal import format_event_date_tag, resolve_valid_until_timestamp
from sdk.adapters.memory import (
    SCOPE_CHAR_CROSS_SAVE,
    MemoryDraft,
    MemoryRecord,
    TurnRecallInput,
)
from sdk.hooks import BeforeCompactContext
from test.mocks import MockLLMAdapter


def _ts(year: int, month: int, day: int, hour: int = 12) -> float:
    return datetime(year, month, day, hour, 0, 0).timestamp()


def test_foresight_valid_until_parsing_wakeup_gating_and_accelerated_overdue_decay(
    tmp_path: Path,
):
    anchor_iso = "2026-11-16T10:00:00+08:00"
    deadline_ts = resolve_valid_until_timestamp("明天", anchor_iso=anchor_iso)
    assert format_event_date_tag(deadline_ts) == "2026-11-17"

    drafts = parse_memory_drafts(
        json.dumps(
            [
                {
                    "character_name": "Mika",
                    "detail": "Mika和用户约定明天下午三点去银座看画展",
                    "gist": "约定去银座看画展",
                    "kind": "promise",
                    "topics": ["画展", "约定"],
                    "entities": ["银座"],
                    "importance": 0.85,
                    "event_time": "明天",
                    "valid_until": "明天",
                }
            ],
            ensure_ascii=False,
        ),
        character_names=("Mika",),
        now_iso=anchor_iso,
    )
    assert len(drafts) == 1
    meta = unpack_system_tags(drafts[0].topic_tags)
    assert meta.public_tags == ("画展", "约定")
    assert meta.valid_until == pytest.approx(deadline_ts, abs=2.0)

    repo = SqliteHybridMemoryRepo(tmp_path / "foresight.db")
    try:
        embedder = DeterministicHashEmbedder(dimensions=384)
        orch = MemoryOrchestrator(embedder=embedder, global_repo=repo)
        t_created = _ts(2026, 11, 16, 10)
        orch.ingest_drafts(drafts, now_ts=t_created)

        # 1. Before deadline (6 hours later -> >4h session wakeup): surfaced cleanly!
        wakeup_active = orch.recall_for_turn(
            TurnRecallInput(
                user_text="晚上好",
                active_character_names=("Mika",),
                seconds_since_last_turn=6.0 * 3600.0,
                now_ts=t_created + 6.0 * 3600.0,
            )
        )
        assert "银座看画展" in wakeup_active.rendered

        # 2. Five days AFTER deadline (`2026-11-23`): expired promise is NOT surfaced on `"早安"` wakeup!
        t_expired = _ts(2026, 11, 23, 9)
        stored_rec = repo.list_by_scope(
            operations.resolve_memory_read_filter("Mika"),
            limit=5,
        )[0]
        assert is_foresight_expired(stored_rec, now_ts=t_expired) is True

        wakeup_expired = orch.recall_for_turn(
            TurnRecallInput(
                user_text="早安",
                active_character_names=("Mika",),
                seconds_since_last_turn=8.0 * 3600.0,
                now_ts=t_expired,
            )
        )
        assert "银座看画展" not in wakeup_expired.rendered

        # 3. Overdue foresight decays much faster than an unbounded memory of the same age
        policy = EbbinghausRetentionPolicy()
        unbounded_rec = MemoryRecord(
            id="u1",
            scope=SCOPE_CHAR_CROSS_SAVE,
            owner_id="Mika",
            detail_text="约定以后有机会一起去银座看画展",
            kind="promise",
            importance=0.5,
            created_at=t_created,
            last_recalled_at=t_created,
        )
        bounded_rec = MemoryRecord(
            id="b1",
            scope=SCOPE_CHAR_CROSS_SAVE,
            owner_id="Mika",
            detail_text="明天下午临时去取干洗衣服",
            kind="promise",
            topic_tags=pack_system_tags(valid_until=t_created + SECONDS_PER_DAY),
            importance=0.5,
            created_at=t_created,
            last_recalled_at=t_created,
        )
        eval_ts = t_created + 7 * SECONDS_PER_DAY
        assert (
            policy.evaluate(bounded_rec, now_ts=eval_ts).retention
            < policy.evaluate(unbounded_rec, now_ts=eval_ts).retention
        )
    finally:
        repo.close()


def test_dream_relational_and_scene_ebbinghaus_clarity_tiers():
    policy = EbbinghausRetentionPolicy()
    t0 = _ts(2026, 10, 1, 12)

    rel_rec = MemoryRecord(
        id="rel-1",
        scope=SCOPE_CHAR_CROSS_SAVE,
        owner_id="Mika",
        detail_text="因用户在暴雨夜撑伞接送，Mika放下了对陌生人的戒备并主动分享童年往事",
        gist_text="暴雨夜接送后Mika放下戒备",
        kind="relational",
        importance=0.5,
        created_at=t0,
        last_recalled_at=t0,
    )
    scene_rec = MemoryRecord(
        id="scn-1",
        scope=SCOPE_CHAR_CROSS_SAVE,
        owner_id="Mika",
        detail_text="文化祭筹备周：Mika与用户克服吉他断弦危机，顺利完成轻音部压轴演出",
        gist_text="共同克服危机完成文化祭演出",
        kind="scene",
        importance=0.6,
        created_at=t0,
        last_recalled_at=t0,
    )

    assert policy.evaluate(rel_rec, now_ts=t0 + 3 * SECONDS_PER_DAY).rendered_text.startswith(
        "[心境与关系]"
    )
    assert policy.evaluate(rel_rec, now_ts=t0 + 40 * SECONDS_PER_DAY).rendered_text.startswith(
        "[过往心绪·印象模糊]"
    )
    assert policy.evaluate(scene_rec, now_ts=t0 + 10 * SECONDS_PER_DAY).rendered_text.startswith(
        "[阶段回忆]"
    )


def test_sleep_time_scene_consolidation_on_before_compact_creates_hub_without_deleting_episodes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    embedder = DeterministicHashEmbedder(dimensions=384)
    global_repo = SqliteHybridMemoryRepo(tmp_path / "consolidate.db")
    engine = HybridMemoryEngine(embedder=embedder, repo=global_repo)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)
    monkeypatch.setattr(operations, "_memory_service_url", lambda: "")

    try:
        t0 = _ts(2026, 11, 16, 9)
        seeded_texts = [
            ("清晨两人在京都车站集合搭乘电车前往东山", "清晨在京都站集合", ("京都车站",)),
            ("上午在清水寺木造舞台俯瞰红叶并抽到大吉御神签", "清水寺看红叶抽大吉签", ("清水寺",)),
            ("午后漫步二年坂老街分享焙茶芭菲甜点", "二年坂分享焙茶芭菲", ("二年坂",)),
            ("傍晚穿过伏见稻荷大社连绵的朱红千本鸟居", "穿过伏见稻荷千本鸟居", ("伏见稻荷大社",)),
        ]
        engine.orchestrator.ingest_drafts(
            [
                MemoryDraft(
                    owner_id="Mika",
                    scope=SCOPE_CHAR_CROSS_SAVE,
                    kind="episodic",
                    detail_text=detail,
                    gist_text=gist,
                    entities=("京都", *ents),
                    source_session_id="sess-arc",
                    source_turn_seq=idx,
                )
                for idx, (detail, gist, ents) in enumerate(seeded_texts, start=1)
            ],
            now_ts=t0,
        )

        # `before_compact` extracts 1 more episode (reaching min_scene_episodes=5) AND consolidates 1 `scene`!
        compact_extract_json = json.dumps(
            [
                {
                    "character_name": "Mika",
                    "detail": "入夜后两人在鸭川河畔吹晚风并互赠手工护身符",
                    "gist": "鸭川吹晚风互赠护身符",
                    "kind": "episodic",
                    "entities": ["京都", "鸭川", "护身符"],
                    "importance": 0.85,
                }
            ],
            ensure_ascii=False,
        )
        scene_synth_json = json.dumps(
            {
                "detail": "京都修学旅行篇章：Mika与用户游览清水寺与千本鸟居，夜晚在鸭川互赠护身符，关系显著升温",
                "gist": "京都修学旅行互赠护身符",
                "topics": ["修学旅行", "京都"],
                "entities": ["京都", "清水寺", "鸭川", "护身符"],
                "importance": 0.88,
            },
            ensure_ascii=False,
        )
        llm = MockLLMAdapter(responses=[compact_extract_json, scene_synth_json])
        hooks = MemoryAutoHooks(
            llm_adapter=llm,
            character_names=["Mika"],
            session_id="sess-arc",
            memory_mode="shared",
            queue=MemoryWriteQueue(path=tmp_path / "q_scene.json"),
            min_scene_episodes=5,
            clock_func=lambda: t0 + 300,
        )

        older = [
            {"role": "user", "content": "鸭川的夕阳真美，这个护身符送给你", "_turn_seq": 9},
            {"role": "assistant", "content": "谢谢你，我会一直带在身边的！", "_turn_seq": 10},
        ]
        hooks.before_compact(
            BeforeCompactContext(
                messages=older,
                older_messages=older,
                recent_messages=[],
                session_id="sess-arc",
                up_to_seq=10,
            )
        )

        listed = operations.memory_list("Mika")["memories"]
        scenes = [m for m in listed if m["kind"] == "scene"]
        episodes = [m for m in listed if m["kind"] == "episodic"]
        assert len(scenes) == 1
        assert "京都修学旅行篇章" in scenes[0]["detail"]
        assert "护身符" in scenes[0]["entities"]
        # Underlying 5 episodic details remain intact (never destructively deleted!)
        assert len(episodes) == 5
        assert len(llm.call_history) == 2

        # Subsequent shutdown without new episodes respects the scene watermark (0 extra LLM calls!)
        hooks.shutdown()
        assert len(llm.call_history) == 2
    finally:
        global_repo.close()
