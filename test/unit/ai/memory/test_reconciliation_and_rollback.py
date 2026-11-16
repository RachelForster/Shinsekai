"""Unit tests for Memory-R1 candidate reconciliation and timeline-rollback reversibility."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pytest

from ai.memory import operations
from ai.memory.backends.in_memory import (
    DeterministicHashEmbedder,
    InMemoryMemoryRepository,
)
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
from ai.memory.engine import HybridMemoryEngine
from ai.memory.hooks import MemoryAutoHooks
from ai.memory.metadata_tags import pack_system_tags
from ai.memory.orchestrator import MemoryOrchestrator
from ai.memory.queue import MemoryWriteQueue
from ai.memory.reconciliation import CandidateReconciler
from sdk.adapters.memory import (
    SCOPE_CHAR_CANON,
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SELF_PUBLIC,
    MemoryDraft,
    TurnRecallInput,
)
from sdk.hooks import MessageAddedContext
from test.mocks import MockLLMAdapter


def _ts(year: int, month: int, day: int, hour: int = 12) -> float:
    return datetime(year, month, day, hour, 0, 0).timestamp()


@pytest.fixture(params=["in_memory", "sqlite_hybrid"])
def repo_backend(request, tmp_path: Path):
    if request.param == "in_memory":
        yield InMemoryMemoryRepository()
    else:
        repo = SqliteHybridMemoryRepo(tmp_path / "reconcile_store.db")
        try:
            yield repo
        finally:
            repo.close()


def test_reconciler_fast_path_gating_avoids_llm_calls_for_novel_and_duplicate_drafts():
    llm = MockLLMAdapter(responses=['[{"index":0,"action":"ADD","target_ids":[]}]'])

    def fetcher(draft: MemoryDraft, _limit: int):
        if "天体物理" in draft.detail_text:
            return [{"id": "old-1", "detail": "用户养了一只柯基犬", "score": 0.18}]
        if "一模一样" in draft.detail_text:
            return [{"id": "old-2", "detail": "用户每天早上喝一杯热豆浆（一模一样）", "score": 0.96}]
        return []

    reconciler = CandidateReconciler(llm, candidate_fetcher=fetcher)
    out = reconciler.reconcile(
        [
            MemoryDraft(owner_id="__self__", detail_text="用户最近在旁听天体物理公开课"),
            MemoryDraft(owner_id="__self__", detail_text="用户每天早上喝一杯热豆浆（一模一样）"),
        ],
        dialogue_text="user: 我最近在旁听天体物理公开课。",
    )
    assert len(out) == 1
    assert "天体物理" in out[0].detail_text
    # Fast-path handled both (< 0.52 ADD and >= 0.92 NOOP) with ZERO LLM invocations!
    assert llm.call_history == []


def test_cross_slot_supersede_and_retraction_tombstone_restore_cleanly_on_rollback(
    repo_backend,
):
    embedder = DeterministicHashEmbedder(dimensions=384)
    orch = MemoryOrchestrator(embedder=embedder, global_repo=repo_backend)
    now_ts = _ts(2026, 11, 16, 14)

    # Turn 2: Initial preferences & facts with drifted/empty slot_keys
    r_init = orch.ingest_drafts(
        [
            MemoryDraft(
                owner_id="__self__",
                scope=SCOPE_SELF_PUBLIC,
                slot_key="profile:drink",
                kind="profile",
                detail_text="用户最常喝全糖焦糖玛奇朵",
                gist_text="常喝全糖焦糖玛奇朵",
                source_session_id="sess-rev",
                source_turn_seq=2,
            ),
            MemoryDraft(
                owner_id="Mika",
                scope=SCOPE_CHAR_CROSS_SAVE,
                kind="episodic",
                detail_text="用户说自己大学时去过北海道札幌看雪祭",
                gist_text="去过北海道看雪祭",
                entities=("北海道",),
                source_session_id="sess-rev",
                source_turn_seq=2,
            ),
        ],
        now_ts=now_ts,
    )
    drink_old_id, hokkaido_old_id = r_init.added_ids

    # Turn 6:
    # 1) Cross-slot SUPERSEDE (`profile:favorite_beverage` != `profile:drink`)
    # 2) Explicit INVALIDATE (`kind="retraction"` tombstone) for the false Hokkaido claim
    r_update = orch.ingest_drafts(
        [
            MemoryDraft(
                owner_id="__self__",
                scope=SCOPE_SELF_PUBLIC,
                slot_key="profile:favorite_beverage",
                kind="profile",
                detail_text="用户戒糖后改喝冰萃黑咖啡了",
                gist_text="改喝冰萃黑咖啡",
                topic_tags=pack_system_tags(("饮品",), supersedes_ids=(drink_old_id,)),
                source_session_id="sess-rev",
                source_turn_seq=6,
            ),
            MemoryDraft(
                owner_id="Mika",
                scope=SCOPE_CHAR_CROSS_SAVE,
                kind="retraction",
                detail_text="撤回：用户澄清之前没去过北海道",
                gist_text="撤回北海道经历",
                topic_tags=pack_system_tags(supersedes_ids=(hokkaido_old_id,)),
                importance=0.1,
                source_session_id="sess-rev",
                source_turn_seq=6,
            ),
        ],
        now_ts=now_ts + 120,
    )
    assert set(r_update.superseded_ids) == {drink_old_id, hokkaido_old_id}

    # Verify outdated drink AND retracted Hokkaido claim are BOTH hidden from recall & tool search!
    turn_recall = orch.recall_for_turn(
        TurnRecallInput(
            user_text="我戒糖后平时改喝什么黑咖啡？还有北海道札幌雪祭的事",
            active_character_names=("Mika",),
            session_id="sess-rev",
            now_ts=now_ts + 180,
        )
    )
    assert "冰萃黑咖啡" in turn_recall.rendered
    assert "焦糖玛奇朵" not in turn_recall.rendered
    assert "北海道" not in turn_recall.rendered
    assert "撤回：" not in turn_recall.rendered

    tool_hits = orch.search_for_tool(
        "北海道札幌雪祭",
        character_name="Mika",
        now_ts=now_ts + 180,
    )
    assert all("北海道" not in row["detail"] for row in tool_hits)
    assert all(row["kind"] != "retraction" for row in tool_hits)

    # Now player clicks Revert / Reroll back to Turn 4 (`rollback_after_turn("sess-rev", 4)`):
    # BOTH the cross-slot update AND the retraction tombstone are deleted, and BOTH original
    # Turn 2 memories revive with their original embeddings intact!
    deleted = repo_backend.rollback_after_turn("sess-rev", 4)
    assert deleted == 2

    restored_drink = repo_backend.get(drink_old_id)
    restored_hokkaido = repo_backend.get(hokkaido_old_id)
    assert restored_drink is not None and restored_drink.superseded_by is None
    assert restored_drink.embedding is not None
    assert restored_hokkaido is not None and restored_hokkaido.superseded_by is None
    assert restored_hokkaido.embedding is not None

    post_rollback = orch.recall_for_turn(
        TurnRecallInput(
            user_text="我平时最常喝什么玛奇朵？还有北海道札幌雪祭",
            active_character_names=("Mika",),
            session_id="sess-rev",
            now_ts=now_ts + 240,
        )
    )
    assert "全糖焦糖玛奇朵" in post_rollback.rendered
    assert "北海道札幌看雪祭" in post_rollback.rendered


def test_ingest_blocks_cross_owner_or_canon_supersede_attempts(repo_backend):
    embedder = DeterministicHashEmbedder(dimensions=384)
    orch = MemoryOrchestrator(embedder=embedder, global_repo=repo_backend)
    now_ts = _ts(2026, 11, 16, 15)

    seeded = orch.ingest_drafts(
        [
            MemoryDraft(
                owner_id="Mika",
                scope=SCOPE_CHAR_CANON,
                kind="canon",
                pinned=True,
                detail_text="Mika天生拥有绝对音感",
            ),
            MemoryDraft(
                owner_id="Sakura",
                scope=SCOPE_CHAR_CROSS_SAVE,
                detail_text="Sakura的秘密日记锁在樱花木盒里",
            ),
        ],
        now_ts=now_ts,
    )
    canon_id, sakura_id = seeded.added_ids

    # A dialogue draft for Mika tries to supersede Mika's canon AND Sakura's private memory -> blocked!
    attempt = orch.ingest_drafts(
        [
            MemoryDraft(
                owner_id="Mika",
                scope=SCOPE_CHAR_CROSS_SAVE,
                kind="retraction",
                detail_text="非法撤回尝试",
                topic_tags=pack_system_tags(supersedes_ids=(canon_id, sakura_id)),
            )
        ],
        now_ts=now_ts + 30,
    )
    assert attempt.added_ids == ()
    assert attempt.superseded_ids == ()
    assert repo_backend.get(canon_id).superseded_by is None
    assert repo_backend.get(sakura_id).superseded_by is None


def test_end_to_end_hooks_reconcile_drifted_slot_conflict_via_queue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    embedder = DeterministicHashEmbedder(dimensions=384)
    global_repo = SqliteHybridMemoryRepo(tmp_path / "e2e_reconcile.db")
    engine = HybridMemoryEngine(embedder=embedder, repo=global_repo)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)
    monkeypatch.setattr(operations, "_memory_service_url", lambda: "")

    try:
        # Seed initial preference under `slot_key="hobby:weekend"`
        r0 = engine.orchestrator.ingest_drafts(
            [
                MemoryDraft(
                    owner_id="Mika",
                    scope=SCOPE_CHAR_CROSS_SAVE,
                    slot_key="hobby:weekend",
                    kind="profile",
                    detail_text="用户每个周六都会去室内攀岩馆训练",
                    gist_text="周六常去室内攀岩",
                    source_session_id="sess-h",
                    source_turn_seq=1,
                )
            ]
        )
        old_id = r0.added_ids[0]

        extraction_resp = json.dumps(
            [
                {
                    "character_name": "Mika",
                    "detail": "用户手腕受伤后不再去室内攀岩馆，周六改去游泳馆蛙泳了",
                    "gist": "周六改去游泳馆",
                    "kind": "profile",
                    "slot_key": "activity:saturday_sport",  # Drifted slot_key!
                    "importance": 0.8,
                }
            ],
            ensure_ascii=False,
        )
        reconcile_resp = json.dumps(
            [
                {
                    "index": 0,
                    "action": "SUPERSEDE",
                    "target_ids": [old_id],
                }
            ]
        )
        llm = MockLLMAdapter(responses=[extraction_resp, reconcile_resp])
        hooks = MemoryAutoHooks(
            llm_adapter=llm,
            character_names=["Mika"],
            session_id="sess-h",
            memory_mode="shared",
            queue=MemoryWriteQueue(path=tmp_path / "q.json"),
            extract_interval_turns=1,
        )

        hooks.message_added(
            MessageAddedContext(
                role="user",
                message={"role": "user", "content": "我手腕伤了，以后不去室内攀岩馆了，改去游泳馆"},
                messages=[],
                session_id="sess-h",
                turn_seq=5,
            )
        )
        hooks.message_added(
            MessageAddedContext(
                role="assistant",
                message={"role": "assistant", "content": "那要注意护腕恢复哦！"},
                messages=[],
                session_id="sess-h",
                turn_seq=6,
            )
        )
        hooks.wait_for_idle()

        old_rec = global_repo.get(old_id)
        assert old_rec is not None and old_rec.superseded_by is not None
        listed = operations.memory_list("Mika")
        assert len(listed["memories"]) == 1
        assert "改去游泳馆" in listed["memories"][0]["detail"]
        # Ensure `__sys:*` tags never leak into serialized `topicTags`
        assert all(not t.startswith("__sys:") for t in listed["memories"][0]["topicTags"])
    finally:
        global_repo.close()
