"""Unit & contract tests for HippoRAG 2 scoped bipartite Personalized PageRank (PPR)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time

import pytest

from ai.memory.backends.in_memory import (
    DeterministicHashEmbedder,
    InMemoryMemoryRepository,
)
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
from ai.memory.graph_ppr import run_scoped_bipartite_ppr
from ai.memory.orchestrator import MemoryOrchestrator
from sdk.adapters.memory import (
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SAVE_ISOLATED,
    MemoryDraft,
    MemoryRecord,
    TurnRecallInput,
)
from sdk.adapters.session import MEMORY_MODE_ISOLATED


def _ts(year: int, month: int, day: int, hour: int = 12) -> float:
    return datetime(year, month, day, hour, 0, 0).timestamp()


@pytest.fixture(params=["in_memory", "sqlite_hybrid"])
def repo_backend(request, tmp_path: Path):
    if request.param == "in_memory":
        yield InMemoryMemoryRepository()
    else:
        repo = SqliteHybridMemoryRepo(tmp_path / "ppr_store.db")
        try:
            yield repo
        finally:
            repo.close()


def test_bipartite_ppr_recalls_two_hop_and_three_hop_rare_entity_chains(repo_backend):
    embedder = DeterministicHashEmbedder(dimensions=384)
    orch = MemoryOrchestrator(embedder=embedder, global_repo=repo_backend)
    now_ts = _ts(2026, 11, 16, 10)

    # Chain: Seed (银怀表) -> Hop1 (银怀表, 雾岛灯塔) -> Hop2 (雾岛灯塔, 守塔人老周) -> Hop3 (守塔人老周, 青铜密码筒)
    orch.ingest_drafts(
        [
            MemoryDraft(
                owner_id="Mika",
                scope=SCOPE_CHAR_CROSS_SAVE,
                detail_text="用户在旧书摊买到了一只停在三点十五分的刻花银怀表",
                gist_text="旧书摊买到刻花银怀表",
                entities=("银怀表",),
                importance=0.85,
            ),
            MemoryDraft(
                owner_id="Mika",
                scope=SCOPE_CHAR_CROSS_SAVE,
                detail_text="刻花银怀表内盖镌刻着雾岛灯塔的经纬坐标",
                gist_text="银怀表刻着雾岛灯塔坐标",
                entities=("银怀表", "雾岛灯塔"),
                importance=0.85,
            ),
            MemoryDraft(
                owner_id="Mika",
                scope=SCOPE_CHAR_CROSS_SAVE,
                detail_text="雾岛灯塔地下室一直由独居的守塔人老周照看",
                gist_text="雾岛灯塔由守塔人老周照看",
                entities=("雾岛灯塔", "守塔人老周"),
                importance=0.85,
            ),
            MemoryDraft(
                owner_id="Mika",
                scope=SCOPE_CHAR_CROSS_SAVE,
                detail_text="守塔人老周年轻时曾受托保管一只刻有海鸟纹的青铜密码筒",
                gist_text="老周保管着海鸟纹青铜密码筒",
                entities=("守塔人老周", "青铜密码筒"),
                importance=0.88,
            ),
        ],
        now_ts=now_ts,
    )

    block = orch.recall_for_turn(
        TurnRecallInput(
            user_text="那只停在三点十五分的刻花银怀表有什么线索？",
            active_character_names=("Mika",),
            now_ts=now_ts + 30,
        )
    )
    assert "刻花银怀表" in block.rendered
    assert "雾岛灯塔" in block.rendered  # 1-hop
    assert "守塔人老周" in block.rendered  # 2-hop (impossible with 1-hop expand_entities!)
    assert "青铜密码筒" in block.rendered  # 3-hop


def test_bipartite_ppr_ief_suppresses_ubiquitous_hub_entities_without_blocking_rare_clues(
    repo_backend,
):
    embedder = DeterministicHashEmbedder(dimensions=384)
    orch = MemoryOrchestrator(embedder=embedder, global_repo=repo_backend)
    now_ts = _ts(2026, 11, 16, 11)

    # Create 45 unrelated memories all sharing ubiquitous hub entities ("Mika", "日常学园")
    noise_drafts = [
        MemoryDraft(
            owner_id="Mika",
            scope=SCOPE_CHAR_CROSS_SAVE,
            detail_text=f"支线事件记录 {idx}：独特的背景话题词条 alpha_{idx} beta_{idx * 7}",
            gist_text=f"支线事件 {idx}",
            entities=("Mika", "日常学园"),
            importance=0.5,
        )
        for idx in range(45)
    ]
    clue_drafts = [
        MemoryDraft(
            owner_id="Mika",
            scope=SCOPE_CHAR_CROSS_SAVE,
            detail_text="Mika在音乐教室抽屉里发现了一枚琥珀音叉",
            gist_text="发现琥珀音叉",
            entities=("Mika", "日常学园", "琥珀音叉"),
            importance=0.85,
        ),
        MemoryDraft(
            owner_id="Mika",
            scope=SCOPE_CHAR_CROSS_SAVE,
            detail_text="琥珀音叉是十年前轻音部初代部长留下的信物",
            gist_text="琥珀音叉是初代部长信物",
            entities=("Mika", "日常学园", "琥珀音叉", "初代部长"),
            importance=0.85,
        ),
    ]
    orch.ingest_drafts([*noise_drafts, *clue_drafts], now_ts=now_ts, dedupe_threshold=0.99)

    block = orch.recall_for_turn(
        TurnRecallInput(
            user_text="音乐教室抽屉里那枚琥珀音叉是什么来历？",
            active_character_names=("Mika",),
            now_ts=now_ts + 60,
        )
    )
    assert "初代部长" in block.rendered
    # Hub-only bystanders should be dampened below relevance gate
    assert "支线事件记录" not in block.rendered


def test_bipartite_ppr_strict_anti_telepathy_across_characters_and_isolated_saves(
    tmp_path: Path,
):
    embedder = DeterministicHashEmbedder(dimensions=384)
    global_repo = SqliteHybridMemoryRepo(tmp_path / "global.db")
    save_a = SqliteHybridMemoryRepo(tmp_path / "save_a.db")
    save_b = SqliteHybridMemoryRepo(tmp_path / "save_b.db")
    try:
        orch = MemoryOrchestrator(embedder=embedder, global_repo=global_repo)
        now_ts = _ts(2026, 11, 16, 12)

        orch.ingest_drafts(
            [
                MemoryDraft(
                    owner_id="Mika",
                    scope=SCOPE_CHAR_CROSS_SAVE,
                    detail_text="Mika知道绯红秘钥藏在钟楼顶层",
                    entities=("绯红秘钥", "钟楼"),
                    importance=0.9,
                ),
                # Sakura shares entity "钟楼" + 2-hop "地下暗河", must NEVER leak to Mika!
                MemoryDraft(
                    owner_id="Sakura",
                    scope=SCOPE_CHAR_CROSS_SAVE,
                    detail_text="Sakura发现钟楼暗门通往地下暗河",
                    entities=("钟楼", "地下暗河"),
                    importance=0.9,
                ),
            ],
            now_ts=now_ts,
        )

        # Save A vs Save B isolation
        orch.ingest_drafts(
            [
                MemoryDraft(
                    owner_id="Mika",
                    detail_text="存档A里Mika拿到了星辰罗盘",
                    entities=("星辰罗盘", "迷雾海湾"),
                    source_session_id="save_a",
                ),
                MemoryDraft(
                    owner_id="Mika",
                    detail_text="存档A里迷雾海湾停泊着幽灵帆船",
                    entities=("迷雾海湾", "幽灵帆船"),
                    source_session_id="save_a",
                ),
            ],
            memory_mode=MEMORY_MODE_ISOLATED,
            save_repo=save_a,
            now_ts=now_ts,
        )
        orch.ingest_drafts(
            [
                MemoryDraft(
                    owner_id="Mika",
                    detail_text="存档B里Mika听说过星辰罗盘的传说",
                    entities=("星辰罗盘",),
                    source_session_id="save_b",
                )
            ],
            memory_mode=MEMORY_MODE_ISOLATED,
            save_repo=save_b,
            now_ts=now_ts,
        )

        mika_only = orch.recall_for_turn(
            TurnRecallInput(
                user_text="绯红秘钥藏在钟楼哪里？",
                active_character_names=("Mika",),
                now_ts=now_ts + 10,
            )
        )
        assert "绯红秘钥" in mika_only.rendered
        assert "地下暗河" not in mika_only.rendered

        # Group scene ("Mika", "Sakura"): Mika's seed does NOT jump into Sakura's graph unless Sakura is seeded
        save_b_recall = orch.recall_for_turn(
            TurnRecallInput(
                user_text="星辰罗盘有什么线索？",
                active_character_names=("Mika",),
                session_id="save_b",
                memory_mode=MEMORY_MODE_ISOLATED,
                now_ts=now_ts + 10,
            ),
            save_repo=save_b,
        )
        assert "幽灵帆船" not in save_b_recall.rendered
        assert "绯红秘钥" not in save_b_recall.rendered
    finally:
        save_b.close()
        save_a.close()
        global_repo.close()


def test_bipartite_ppr_300_node_subgraph_latency_under_budget():
    now_ts = _ts(2026, 11, 16, 13)
    records = [
        MemoryRecord(
            id=f"rec-{idx}",
            scope=SCOPE_CHAR_CROSS_SAVE,
            owner_id="Mika",
            detail_text=f"记忆节点 {idx}",
            entities=(f"entity_{idx % 60}", f"chain_{idx // 2}", "Mika"),
            topic_tags=(f"topic_{idx % 25}",),
            importance=0.6,
            created_at=now_ts + idx,
        )
        for idx in range(300)
    ]
    # Warm up numpy once
    run_scoped_bipartite_ppr(records, seed_weights={"rec-0": 0.9}, limit=8)

    t0 = time.perf_counter()
    hits, had_concepts = run_scoped_bipartite_ppr(
        records,
        seed_weights={"rec-0": 0.92, "rec-10": 0.75},
        limit=8,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert had_concepts is True
    assert len(hits) > 0
    assert elapsed_ms < 25.0, f"Expected <25ms for 300-node PPR, took {elapsed_ms:.2f}ms"
