"""Unit & contract tests for RuleRecallPlanner and MemoryOrchestrator."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ai.memory.backends.in_memory import (
    DeterministicHashEmbedder,
    InMemoryMemoryRepository,
)
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
from ai.memory.ebbinghaus import SECONDS_PER_DAY
from ai.memory.engine import HybridMemoryEngine
from ai.memory.orchestrator import MemoryOrchestrator
from ai.memory.ports import (
    RecallPlannerContribution,
    RetentionPolicyContribution,
    clear_memory_adapter_registrations,
    register_recall_planner,
    register_retention_policy,
)
from ai.memory.rule_recall_planner import RuleRecallPlanner
from core.chat_history.sqlite_session_store import SqliteSessionStore
from sdk.adapters.memory import (
    SCOPE_CHAR_CANON,
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SAVE_ISOLATED,
    SCOPE_SELF_PUBLIC,
    MemoryDraft,
    MemoryRecord,
    MemoryScopeFilter,
    RecallPlan,
    RecallPlanner,
    RetentionPolicy,
    RetentionState,
    TurnRecallInput,
)
from sdk.adapters.session import (
    MEMORY_MODE_INHERIT_READONLY,
    MEMORY_MODE_ISOLATED,
    MEMORY_MODE_SHARED,
)


def _ts(year: int, month: int, day: int, hour: int = 12) -> float:
    return datetime(year, month, day, hour, 0, 0).timestamp()


@pytest.fixture(params=["in_memory", "sqlite_hybrid"])
def repo_pair(request, tmp_path: Path):
    if request.param == "in_memory":
        yield InMemoryMemoryRepository(), InMemoryMemoryRepository()
    else:
        global_repo = SqliteHybridMemoryRepo(tmp_path / "global_store.db")
        save_repo = SqliteHybridMemoryRepo(tmp_path / "save_store.db")
        try:
            yield global_repo, save_repo
        finally:
            save_repo.close()
            global_repo.close()


def test_rule_recall_planner_mutes_fillers_but_wakes_after_four_hours():
    planner = RuleRecallPlanner()
    assert isinstance(planner, RecallPlanner)

    for filler in ("嗯", "好的！", "ok", "哈哈哈", "なるほど", "[本地时间 2026-11-15 12:00:00]\n嗯嗯"):
        plan = planner.plan(
            TurnRecallInput(
                user_text=filler,
                seconds_since_last_turn=120.0,
            )
        )
        assert plan.should_recall is False

    # Same filler after 5 hours (>= 4h wakeup threshold) triggers wakeup recall!
    wakeup_plan = planner.plan(
        TurnRecallInput(
            user_text="早",
            seconds_since_last_turn=5.0 * 3600.0,
        )
    )
    assert wakeup_plan.should_recall is True
    assert wakeup_plan.is_session_wakeup is True
    assert any("约定" in clause for clause in wakeup_plan.query_clauses)


def test_rule_recall_planner_stitches_short_or_anaphoric_turns_and_splits_clauses():
    planner = RuleRecallPlanner(max_clauses=4)

    # Short utterance (<12 chars) stitches previous assistant utterance
    short_plan = planner.plan(
        TurnRecallInput(
            user_text="那件事呢？",
            previous_assistant_text="Mika: 上次你提到想去镰仓海边拍照。",
            active_character_names=("Mika",),
        )
    )
    assert short_plan.should_recall is True
    assert any("镰仓海边拍照" in c and "那件事呢" in c for c in short_plan.query_clauses)

    # Longer sentence (>12 chars) containing anaphoric cue ("之前" / "那个") also stitches context
    anaphora_plan = planner.plan(
        TurnRecallInput(
            user_text="我今天考虑了一下你之前提到的那个社团文化祭提案",
            previous_assistant_text="Nanami: 我们轻音部想在秋叶原办联合演出。",
        )
    )
    assert any("秋叶原办联合演出" in c for c in anaphora_plan.query_clauses)

    # Multi-clause long turn splits into <= 4 clauses while preserving final tail topic
    long_text = (
        "今天早上我去便利店买了热牛奶。"
        "中午在图书馆借了三本推理小说！"
        "下午和朋友去练了吉他和弦？"
        "晚上想吃豚骨拉面；"
        "顺便问一下周末露营要带什么装备？"
    )
    multi_plan = planner.plan(TurnRecallInput(user_text=long_text))
    assert multi_plan.should_recall is True
    assert len(multi_plan.query_clauses) == 4
    assert "周末露营" in multi_plan.query_clauses[-1]


def test_rule_recall_planner_handles_proactive_perception_turns():
    planner = RuleRecallPlanner()

    # Bare proactive instruction without attached game digest -> muted
    bare = planner.plan(
        TurnRecallInput(
            user_text="[系统事件：玩家并未打字发言。以下是近期画面与屏幕台词的观察记录，请自然搭话]",
            source="perception",
        )
    )
    assert bare.should_recall is False

    # Proactive turn after PerceptionAutoHooks appended game observations -> extracts clean scene clauses
    enriched = (
        "[系统事件：玩家并未打字发言。]\n\n"
        "[Shinsekai realtime game perception cache]\n"
        "（当前游戏/来源：艾尔登法环）\n"
        "- 前情纪要：玩家进入了史东薇尔城\n"
        "- [画面 12:01] 玩家在风暴山丘挑战Boss恶兆妖鬼玛尔基特不幸落败\n"
        "- [台词 12:02] 玛尔基特：将这愚昧的野心付之一炬吧"
    )
    obs_plan = planner.plan(
        TurnRecallInput(
            user_text=enriched,
            previous_assistant_text="Mika: 小心他的延迟斩！",
            source="perception",
        )
    )
    assert obs_plan.should_recall is True
    assert any("恶兆妖鬼玛尔基特" in c for c in obs_plan.query_clauses)
    assert all("系统事件" not in c for c in obs_plan.query_clauses)


def test_orchestrator_dormant_hiding_awakening_and_reinforcement(repo_pair):
    global_repo, _save_repo = repo_pair
    embedder = DeterministicHashEmbedder(dimensions=384)
    orch = MemoryOrchestrator(embedder=embedder, global_repo=global_repo)

    t0 = _ts(2026, 9, 1, 12)
    dormant_detail = "Mika和用户在箱根雕刻之森美术馆避雨时分享了蓝莓芝士塔"
    dormant_gist = "曾在箱根美术馆避雨分享甜点"
    dormant_id = global_repo.upsert(
        MemoryRecord(
            id="",
            scope=SCOPE_CHAR_CROSS_SAVE,
            owner_id="Mika",
            detail_text=dormant_detail,
            gist_text=dormant_gist,
            kind="episodic",
            importance=0.35,
            created_at=t0,
            event_at=t0,
            last_recalled_at=t0,
            embedding=embedder.embed_query(dormant_detail),
        )
    )

    now_ts = t0 + 35 * SECONDS_PER_DAY  # Well past dormant threshold (< 0.15)

    # 1. Casual low-similarity chat does NOT surface dormant memory and NEVER deletes it
    casual_block = orch.recall_for_turn(
        TurnRecallInput(
            user_text="今天午饭去美术馆附近吃什么好呢？",
            active_character_names=("Mika",),
            now_ts=now_ts,
        )
    )
    assert dormant_id not in casual_block.recalled_ids
    assert global_repo.get(dormant_id) is not None  # Still preserved in DB!

    # 2. Direct high-precision mention awakens dormant memory as `[唤醒的久远记忆] gist`
    awaken_block = orch.recall_for_turn(
        TurnRecallInput(
            user_text="你还记得我们在箱根雕刻之森美术馆避雨时分享了蓝莓芝士塔吗？",
            active_character_names=("Mika",),
            now_ts=now_ts,
        )
    )
    assert dormant_id in awaken_block.recalled_ids
    assert "[唤醒的久远记忆·2026-09-01] 曾在箱根美术馆避雨分享甜点" in awaken_block.rendered

    # 3. Awakening reinforced recall_count & last_recalled_at -> retention recovers to `clear`!
    updated = global_repo.get(dormant_id)
    assert updated is not None
    assert updated.recall_count == 1
    assert updated.last_recalled_at == pytest.approx(now_ts)


def test_orchestrator_gates_relevance_window_seqs_and_three_turn_cooldown(repo_pair):
    global_repo, _ = repo_pair
    embedder = DeterministicHashEmbedder(dimensions=384)
    orch = MemoryOrchestrator(embedder=embedder, global_repo=global_repo)

    now_ts = _ts(2026, 11, 15, 14)
    report = orch.ingest_drafts(
        [
            MemoryDraft(
                owner_id="Mika",
                detail_text="Mika最喜欢的乐器是芬达天蓝色电吉他",
                gist_text="喜欢天蓝色电吉他",
                kind="profile",
                importance=0.8,
                source_session_id="sess-1",
                source_turn_seq=12,
            )
        ],
        now_ts=now_ts,
    )
    mem_id = report.added_ids[0]

    # 1. Unrelated query below relevance gate (< 0.38) returns empty block
    unrelated = orch.recall_for_turn(
        TurnRecallInput(
            user_text="量子力学薛定谔方程的波函数推导",
            active_character_names=("Mika",),
            session_id="sess-1",
            now_ts=now_ts + 60,
        )
    )
    assert unrelated.rendered == ""
    assert unrelated.recalled_ids == ()

    # 2. Deduplicated when `source_turn_seq=12` is still inside the active prompt window
    in_window = orch.recall_for_turn(
        TurnRecallInput(
            user_text="Mika最喜欢的乐器是什么电吉他？",
            active_character_names=("Mika",),
            session_id="sess-1",
            in_window_turn_seqs=frozenset({11, 12, 13}),
            now_ts=now_ts + 60,
        )
    )
    assert mem_id not in in_window.recalled_ids

    # 3. Deduplicated when `mem_id` is in `recently_injected_ids` (3-turn cooldown)
    in_cooldown = orch.recall_for_turn(
        TurnRecallInput(
            user_text="Mika最喜欢的乐器是什么电吉他？",
            active_character_names=("Mika",),
            session_id="sess-1",
            recently_injected_ids=frozenset({mem_id}),
            now_ts=now_ts + 60,
        )
    )
    assert mem_id not in in_cooldown.recalled_ids

    # 4. Once out of prompt window and cooldown, recalled as `[清晰]`!
    recalled = orch.recall_for_turn(
        TurnRecallInput(
            user_text="Mika最喜欢的乐器是什么电吉他？",
            active_character_names=("Mika",),
            session_id="sess-1",
            in_window_turn_seqs=frozenset({40, 41}),
            now_ts=now_ts + 60,
        )
    )
    assert mem_id in recalled.recalled_ids
    assert "[清晰] Mika最喜欢的乐器是芬达天蓝色电吉他" in recalled.rendered


def test_orchestrator_entity_expansion_and_strict_character_anti_telepathy(repo_pair):
    global_repo, _ = repo_pair
    embedder = DeterministicHashEmbedder(dimensions=384)
    orch = MemoryOrchestrator(embedder=embedder, global_repo=global_repo)
    now_ts = _ts(2026, 11, 15, 18)

    orch.ingest_drafts(
        [
            # Public user profile (readable by all characters in shared mode)
            MemoryDraft(
                owner_id="__self__",
                scope=SCOPE_SELF_PUBLIC,
                detail_text="用户喝咖啡从不加糖",
                gist_text="喝咖啡不加糖",
                kind="profile",
                importance=0.8,
            ),
            # Mika's private cross-save memory + entity-linked background memory
            MemoryDraft(
                owner_id="Mika",
                scope=SCOPE_CHAR_CROSS_SAVE,
                detail_text="Mika把秘密曲谱藏在了星见天文台的旧钢琴下",
                gist_text="把曲谱藏在星见天文台",
                entities=("星见天文台",),
                importance=0.85,
            ),
            MemoryDraft(
                owner_id="Mika",
                scope=SCOPE_CHAR_CROSS_SAVE,
                detail_text="星见天文台顶楼的钥匙由退休校工老陈保管",
                gist_text="天文台钥匙在老陈手里",
                entities=("星见天文台", "老陈"),
                importance=0.75,
            ),
            # Sakura's private cross-save memory sharing the SAME entity ("星见天文台")
            MemoryDraft(
                owner_id="Sakura",
                scope=SCOPE_CHAR_CROSS_SAVE,
                detail_text="Sakura曾在星见天文台独自许下毕业心愿",
                gist_text="Sakura在天文台许愿",
                entities=("星见天文台",),
                importance=0.9,
            ),
        ],
        now_ts=now_ts,
    )

    # 1. Talking to Mika recalls Mika's direct hit + 1-hop entity expansion ("老陈"),
    #    while NEVER leaking Sakura's memory even though Sakura shares entity "星见天文台"!
    mika_block = orch.recall_for_turn(
        TurnRecallInput(
            user_text="Mika把秘密曲谱藏在了哪里？",
            active_character_names=("Mika",),
            now_ts=now_ts + 30,
        )
    )
    assert "旧钢琴" in mika_block.rendered
    assert "退休校工老陈" in mika_block.rendered  # Pulled via 1-hop entity expansion!
    assert "Sakura" not in mika_block.rendered

    # 2. Talking to Nanami NEVER leaks Mika's or Sakura's private memories,
    #    even when explicitly asking about Mika's secret score!
    nanami_block = orch.recall_for_turn(
        TurnRecallInput(
            user_text="你知道秘密曲谱藏在星见天文台的旧钢琴哪里吗？",
            active_character_names=("Nanami",),
            now_ts=now_ts + 30,
        )
    )
    assert "旧钢琴" not in nanami_block.rendered
    assert "老陈" not in nanami_block.rendered
    assert "Sakura" not in nanami_block.rendered

    # 3. Nanami CAN read the user's `self_public` profile in `shared` mode
    nanami_coffee = orch.recall_for_turn(
        TurnRecallInput(
            user_text="帮我点一杯我平时常喝的不加糖咖啡吧",
            active_character_names=("Nanami",),
            now_ts=now_ts + 30,
        )
    )
    assert "用户喝咖啡从不加糖" in nanami_coffee.rendered

    # 4. Multi-character scene ("Mika", "Sakura") tags owner names `（Mika）` / `（Sakura）`
    group_block = orch.recall_for_turn(
        TurnRecallInput(
            user_text="星见天文台有什么回忆？",
            active_character_names=("Mika", "Sakura"),
            now_ts=now_ts + 30,
        )
    )
    assert "（Mika）" in group_block.rendered
    assert "（Sakura）" in group_block.rendered


def test_orchestrator_enforces_three_save_memory_modes_and_roleplay_persona_protection(
    tmp_path: Path,
):
    embedder = DeterministicHashEmbedder(dimensions=384)
    global_repo = SqliteHybridMemoryRepo(tmp_path / "global.db")
    save_iso_store = SqliteSessionStore(tmp_path / "saves" / "save_iso", session_id="save_iso")
    save_ro_store = SqliteSessionStore(tmp_path / "saves" / "save_ro", session_id="save_ro")
    save_rp_store = SqliteSessionStore(tmp_path / "saves" / "save_rp", session_id="save_rp")
    # Story mode directory with story-v2.json auto-defaults to `isolated`!
    story_dir = tmp_path / "saves" / "story_save"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "story-v2.json").write_text("{}", encoding="utf-8")
    story_store = SqliteSessionStore(story_dir, session_id="story_save")

    try:
        assert story_store.get_memory_mode() == MEMORY_MODE_ISOLATED

        orch = MemoryOrchestrator(embedder=embedder, global_repo=global_repo)
        now_ts = _ts(2026, 11, 15, 19)

        # Seed global repo: canon lore + cross-save episode + public user profile
        orch.ingest_drafts(
            [
                MemoryDraft(
                    owner_id="Mika",
                    scope=SCOPE_CHAR_CANON,
                    kind="canon",
                    detail_text="Mika出身于京都茶道世家",
                ),
                MemoryDraft(
                    owner_id="Mika",
                    scope=SCOPE_CHAR_CROSS_SAVE,
                    detail_text="Mika在日常存档学会了做抹茶提拉米苏",
                ),
                MemoryDraft(
                    owner_id="user",
                    scope=SCOPE_SELF_PUBLIC,
                    detail_text="真人用户是一名软件工程师",
                ),
            ],
            memory_mode=MEMORY_MODE_SHARED,
            now_ts=now_ts,
        )

        # --- Mode 1: `isolated` ---
        orch.ingest_drafts(
            [
                MemoryDraft(
                    owner_id="Mika",
                    detail_text="在这个平行世界存档里Mika是蒸汽飞艇船长",
                    source_session_id="save_iso",
                    source_turn_seq=3,
                )
            ],
            memory_mode=MEMORY_MODE_ISOLATED,
            save_repo=save_iso_store.save_memory_repo,
            now_ts=now_ts,
        )
        # Global cross-save was NOT polluted by isolated save
        global_mika = global_repo.list_by_scope(
            MemoryScopeFilter(scopes=(SCOPE_CHAR_CROSS_SAVE,), owner_ids=("Mika",))
        )
        assert all("蒸汽飞艇船长" not in r.detail_text for r in global_mika)

        # Isolated recall reads save_repo + global char_canon, NEVER global cross-save or self_public
        iso_canon = orch.recall_for_turn(
            TurnRecallInput(
                user_text="Mika出身于京都茶道世家吗？还有蒸汽飞艇船长的事",
                active_character_names=("Mika",),
                session_id="save_iso",
                memory_mode=MEMORY_MODE_ISOLATED,
                now_ts=now_ts + 10,
            ),
            save_repo=save_iso_store.save_memory_repo,
        )
        assert "[固有设定] Mika出身于京都茶道世家" in iso_canon.rendered
        assert "蒸汽飞艇船长" in iso_canon.rendered

        iso_leak_check = orch.recall_for_turn(
            TurnRecallInput(
                user_text="抹茶提拉米苏和软件工程师",
                active_character_names=("Mika",),
                session_id="save_iso",
                memory_mode=MEMORY_MODE_ISOLATED,
                now_ts=now_ts + 10,
            ),
            save_repo=save_iso_store.save_memory_repo,
        )
        assert "抹茶提拉米苏" not in iso_leak_check.rendered
        assert "软件工程师" not in iso_leak_check.rendered

        # --- Mode 2: `inherit_readonly` ---
        orch.ingest_drafts(
            [
                MemoryDraft(
                    owner_id="Mika",
                    detail_text="只读继承分支里Mika捡到了一只橘猫团子",
                    source_session_id="save_ro",
                    source_turn_seq=2,
                )
            ],
            memory_mode=MEMORY_MODE_INHERIT_READONLY,
            save_repo=save_ro_store.save_memory_repo,
            now_ts=now_ts,
        )
        # Global repo still untouched by inherit_readonly write!
        global_mika_after_ro = global_repo.list_by_scope(
            MemoryScopeFilter(scopes=(SCOPE_CHAR_CROSS_SAVE,), owner_ids=("Mika",))
        )
        assert all("橘猫团子" not in r.detail_text for r in global_mika_after_ro)

        # inherit_readonly CAN read BOTH global (`抹茶提拉米苏`) AND its own save (`橘猫团子`)
        ro_recall = orch.recall_for_turn(
            TurnRecallInput(
                user_text="抹茶提拉米苏；还有橘猫团子",
                active_character_names=("Mika",),
                session_id="save_ro",
                memory_mode=MEMORY_MODE_INHERIT_READONLY,
                now_ts=now_ts + 10,
            ),
            save_repo=save_ro_store.save_memory_repo,
        )
        assert "抹茶提拉米苏" in ro_recall.rendered
        assert "橘猫团子" in ro_recall.rendered

        # --- Mode 3: `shared` WITH Roleplay `player_character="侦探亚瑟"` ---
        orch.ingest_drafts(
            [
                MemoryDraft(
                    owner_id="侦探亚瑟",
                    detail_text="侦探亚瑟住在贝克街并抽烟斗",
                    source_session_id="save_rp",
                    source_turn_seq=5,
                ),
                MemoryDraft(
                    owner_id="Mika",
                    detail_text="Mika协助侦探亚瑟破获了蓝宝石失窃案",
                    source_session_id="save_rp",
                    source_turn_seq=5,
                ),
            ],
            memory_mode=MEMORY_MODE_SHARED,
            save_repo=save_rp_store.save_memory_repo,
            player_character="侦探亚瑟",
            now_ts=now_ts,
        )
        # Human `self_public` AND Mika's `char_cross_save` in global_repo are 100% UNPOLLUTED!
        self_public_rows = global_repo.list_by_scope(
            MemoryScopeFilter(scopes=(SCOPE_SELF_PUBLIC,), owner_ids=("__self__",))
        )
        assert [r.detail_text for r in self_public_rows] == ["真人用户是一名软件工程师"]
        global_mika_rows = global_repo.list_by_scope(
            MemoryScopeFilter(scopes=(SCOPE_CHAR_CROSS_SAVE,), owner_ids=("Mika",))
        )
        assert all("蓝宝石失窃案" not in r.detail_text for r in global_mika_rows)

        # Inside `save_rp`, both roleplay memories ARE recalled cleanly!
        rp_recall = orch.recall_for_turn(
            TurnRecallInput(
                user_text="贝克街的侦探亚瑟和蓝宝石失窃案",
                active_character_names=("Mika",),
                session_id="save_rp",
                memory_mode=MEMORY_MODE_SHARED,
                now_ts=now_ts + 10,
            ),
            save_repo=save_rp_store.save_memory_repo,
        )
        assert "贝克街" in rp_recall.rendered
        assert "蓝宝石失窃案" in rp_recall.rendered
    finally:
        story_store.close()
        save_rp_store.close()
        save_ro_store.close()
        save_iso_store.close()
        global_repo.close()


def test_orchestrator_slot_key_conflict_superseding_and_rollback_restoration(repo_pair):
    global_repo, _ = repo_pair
    embedder = DeterministicHashEmbedder(dimensions=384)
    orch = MemoryOrchestrator(embedder=embedder, global_repo=global_repo)
    now_ts = _ts(2026, 11, 15, 20)

    r1 = orch.ingest_drafts(
        [
            MemoryDraft(
                owner_id="__self__",
                scope=SCOPE_SELF_PUBLIC,
                slot_key="profile:favorite_drink",
                kind="profile",
                detail_text="用户最喜欢喝冰美式咖啡",
                gist_text="喜欢喝冰美式",
                source_session_id="sess-slot",
                source_turn_seq=4,
            )
        ],
        now_ts=now_ts,
    )
    old_id = r1.added_ids[0]
    assert r1.superseded_ids == ()

    # Turn 9 updates the same slot_key -> supersedes old_id
    r2 = orch.ingest_drafts(
        [
            MemoryDraft(
                owner_id="__self__",
                scope=SCOPE_SELF_PUBLIC,
                slot_key="profile:favorite_drink",
                kind="profile",
                detail_text="用户改喝温热的宇治抹茶拿铁了",
                gist_text="改喝宇治抹茶拿铁",
                source_session_id="sess-slot",
                source_turn_seq=9,
            )
        ],
        now_ts=now_ts + 60,
    )
    assert r2.superseded_ids == (old_id,)
    superseded_rec = global_repo.get(old_id)
    assert superseded_rec is not None and superseded_rec.superseded_by == r2.added_ids[0]

    # Active recall & tool search only return the updated slot value
    tool_hits = orch.search_for_tool("用户喜欢喝什么饮品抹茶咖啡", now_ts=now_ts + 120)
    texts = [row["detail"] for row in tool_hits]
    assert "用户改喝温热的宇治抹茶拿铁了" in texts
    assert "用户最喜欢喝冰美式咖啡" not in texts

    # Rolling back session `sess-slot` to turn 5 deletes turn 9 update AND restores `old_id`!
    rolled = global_repo.rollback_after_turn("sess-slot", 5)
    assert rolled == 1
    restored = global_repo.get(old_id)
    assert restored is not None and restored.superseded_by is None


def test_pluggable_retention_policy_and_recall_planner_contributions(tmp_path: Path):
    class CustomPolicy:
        def evaluate(self, record: MemoryRecord, *, now_ts: float) -> RetentionState:
            del now_ts
            return RetentionState(
                retention=0.88,
                tier="clear",
                rendered_text=f"[自定义策略] {record.detail_text}",
            )

    class CustomPlanner:
        def plan(self, turn_input: TurnRecallInput) -> RecallPlan:
            return RecallPlan(
                should_recall=True,
                query_clauses=(turn_input.user_text,),
                keyword_query=turn_input.user_text,
                limit=3,
            )

    clear_memory_adapter_registrations()
    repo = InMemoryMemoryRepository()
    try:
        register_retention_policy(
            RetentionPolicyContribution(provider="custom_ret", factory=CustomPolicy, priority=10)
        )
        register_recall_planner(
            RecallPlannerContribution(provider="custom_plan", factory=CustomPlanner, priority=10)
        )
        engine = HybridMemoryEngine(
            embedder=DeterministicHashEmbedder(dimensions=64),
            repo=repo,
        )
        assert isinstance(engine.orchestrator.retention_policy, CustomPolicy)
        assert isinstance(engine.orchestrator.recall_planner, CustomPlanner)
    finally:
        clear_memory_adapter_registrations()


def test_orchestrator_enforces_canon_score_threshold_across_turn_wakeup_hop_and_tool(
    repo_pair,
):
    global_repo, _ = repo_pair
    embedder = DeterministicHashEmbedder(dimensions=384)
    orch = MemoryOrchestrator(embedder=embedder, global_repo=global_repo)
    now_ts = _ts(2026, 11, 15, 21)

    report = orch.ingest_drafts(
        [
            MemoryDraft(
                owner_id="Mika",
                scope=SCOPE_CHAR_CANON,
                kind="canon",
                pinned=True,
                importance=0.95,
                detail_text="Mika十二岁那年在暴风雨的海边失去了相依为命的姐姐",
                gist_text="十二岁在海边暴风雨失去姐姐",
                entities=("海边", "老馆"),
            ),
            MemoryDraft(
                owner_id="Mika",
                scope=SCOPE_CHAR_CANON,
                kind="canon",
                pinned=True,
                importance=0.85,
                detail_text="Mika左手腕上有一道小时候救流浪猫留下的浅浅疤痕",
                gist_text="左手腕有救猫留下的疤痕",
            ),
            MemoryDraft(
                owner_id="Mika",
                scope=SCOPE_CHAR_CROSS_SAVE,
                kind="promise",
                importance=0.80,
                detail_text="Mika答应明天傍晚和用户一起去老馆天台看彗星",
                gist_text="答应一起去老馆天台看彗星",
                entities=("老馆",),
            ),
        ],
        now_ts=now_ts,
    )
    storm_canon_id, scar_canon_id, promise_id = report.added_ids

    # 1. Unrelated chat & single incidental keyword ("海边") fall below canon threshold -> blocked!
    casual_beach = orch.recall_for_turn(
        TurnRecallInput(
            user_text="周末我们去海边游泳玩水吧！",
            active_character_names=("Mika",),
            now_ts=now_ts + 30,
        )
    )
    assert storm_canon_id not in casual_beach.recalled_ids
    assert scar_canon_id not in casual_beach.recalled_ids

    # 2. >4h session wakeup surfaces dynamic promise, NEVER unprompted canon backstory!
    wakeup_block = orch.recall_for_turn(
        TurnRecallInput(
            user_text="早安",
            active_character_names=("Mika",),
            seconds_since_last_turn=6.0 * 3600.0,
            now_ts=now_ts + 6.0 * 3600.0,
        )
    )
    assert promise_id in wakeup_block.recalled_ids
    assert storm_canon_id not in wakeup_block.recalled_ids
    assert scar_canon_id not in wakeup_block.recalled_ids

    # 3. 1-hop entity expansion on "老馆" does NOT bypass canon score threshold!
    comet_block = orch.recall_for_turn(
        TurnRecallInput(
            user_text="明天傍晚去老馆天台看彗星要带望远镜吗？",
            active_character_names=("Mika",),
            now_ts=now_ts + 60,
        )
    )
    assert promise_id in comet_block.recalled_ids
    assert storm_canon_id not in comet_block.recalled_ids

    # 4. Tool search (`search_for_tool`) also blocks low-score canon hits while allowing genuine matches
    unrelated_tool_hits = orch.search_for_tool(
        "今天晚饭吃什么好呢？",
        character_name="Mika",
        now_ts=now_ts + 90,
    )
    unrelated_ids = {row["id"] for row in unrelated_tool_hits}
    assert storm_canon_id not in unrelated_ids
    assert scar_canon_id not in unrelated_ids

    relevant_tool_hits = orch.search_for_tool(
        "你左手腕上那道疤痕是怎么留下的？",
        character_name="Mika",
        now_ts=now_ts + 90,
    )
    assert any(row["id"] == scar_canon_id for row in relevant_tool_hits)

    # 5. Direct topic mention above threshold recalls canon memory cleanly as `[固有设定]`
    direct_canon_block = orch.recall_for_turn(
        TurnRecallInput(
            user_text="跟我讲讲你姐姐和那场海边暴风雨的事吧",
            active_character_names=("Mika",),
            now_ts=now_ts + 120,
        )
    )
    assert storm_canon_id in direct_canon_block.recalled_ids
    assert "[固有设定] Mika十二岁那年在暴风雨的海边失去了相依为命的姐姐" in direct_canon_block.rendered
