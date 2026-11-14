"""Contract test suite for SOLID memory ports, hybrid SQLite engine, and pluggable adapters."""

from __future__ import annotations

from pathlib import Path
import pytest

from ai.knowledge.config import HybridKnowledgeStore
from ai.knowledge.operations import (
    add_knowledge_entry,
    search_knowledge,
    search_local_knowledge_entries,
)
from ai.memory import media_assets, operations
from ai.memory.backends.in_memory import (
    DeterministicHashEmbedder,
    InMemoryMemoryRepository,
    InMemoryStaticVectorStore,
)
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
from ai.memory.engine import HybridMemoryEngine, clear_shared_onnx_embedders
from ai.memory.ports import (
    EmbeddingProviderContribution,
    MemoryRepositoryContribution,
    clear_memory_adapter_registrations,
    register_embedding_provider,
    register_memory_repository,
)
from core.knowledge import catalog
from core.vector_store.sqlite_hybrid_store import SqliteHybridStore
from sdk.adapters.memory import (
    NAMESPACE_KNOWLEDGE,
    NAMESPACE_MEDIA_ASSET,
    SCOPE_CHAR_CANON,
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SAVE_ISOLATED,
    SCOPE_SELF_PUBLIC,
    EmbeddingProvider,
    MemoryCandidateQuery,
    MemoryRecord,
    MemoryRepository,
    MemoryScopeFilter,
    StaticVectorStorePort,
    VectorSliceEntry,
)


@pytest.fixture(params=["in_memory", "sqlite_hybrid"])
def memory_repo(request, tmp_path: Path):
    if request.param == "in_memory":
        yield InMemoryMemoryRepository()
    else:
        repo = SqliteHybridMemoryRepo(tmp_path / "contract_memories.db")
        try:
            yield repo
        finally:
            repo.close()


@pytest.fixture(params=["in_memory", "sqlite_hybrid"])
def slice_store(request, tmp_path: Path):
    if request.param == "in_memory":
        yield InMemoryStaticVectorStore()
    else:
        store = SqliteHybridStore(tmp_path / "contract_slices.db")
        try:
            yield store
        finally:
            store.close()


def test_runtime_checkable_protocol_conformance(tmp_path: Path):
    embedder = DeterministicHashEmbedder(dimensions=384)
    in_mem_repo = InMemoryMemoryRepository()
    in_mem_slices = InMemoryStaticVectorStore()
    sqlite_store = SqliteHybridStore(tmp_path / "proto.db")
    sqlite_repo = SqliteHybridMemoryRepo(sqlite_store)
    try:
        assert isinstance(embedder, EmbeddingProvider)
        assert isinstance(in_mem_repo, MemoryRepository)
        assert isinstance(sqlite_store, MemoryRepository)
        assert isinstance(sqlite_repo, MemoryRepository)
        assert isinstance(in_mem_slices, StaticVectorStorePort)
        assert isinstance(sqlite_store, StaticVectorStorePort)
    finally:
        sqlite_store.close()


def test_repository_contract_crud_and_scope_isolation(memory_repo: MemoryRepository):
    embedder = DeterministicHashEmbedder(dimensions=64)
    id_self = memory_repo.upsert(
        MemoryRecord(
            id="m-self",
            scope=SCOPE_SELF_PUBLIC,
            owner_id="__self__",
            detail_text="用户喜欢在雨天喝手冲咖啡",
            gist_text="喜欢雨天喝手冲咖啡",
            created_at=100.0,
            embedding=embedder.embed_query("用户喜欢在雨天喝手冲咖啡"),
        )
    )
    id_alice = memory_repo.upsert(
        MemoryRecord(
            id="m-alice",
            scope=SCOPE_CHAR_CROSS_SAVE,
            owner_id="爱丽丝",
            detail_text="爱丽丝害怕打雷，雷雨夜会躲在书房",
            gist_text="害怕打雷",
            created_at=200.0,
            embedding=embedder.embed_query("爱丽丝害怕打雷"),
        )
    )
    memory_repo.upsert(
        MemoryRecord(
            id="m-bob",
            scope=SCOPE_CHAR_CROSS_SAVE,
            owner_id="鲍勃",
            detail_text="鲍勃擅长修理怀表",
            created_at=300.0,
            embedding=embedder.embed_query("鲍勃擅长修理怀表"),
        )
    )

    fetched = memory_repo.get(id_self)
    assert fetched is not None
    assert fetched.detail_text == "用户喜欢在雨天喝手冲咖啡"
    assert fetched.gist_text == "喜欢雨天喝手冲咖啡"

    alice_only = memory_repo.list_by_scope(
        MemoryScopeFilter(scopes=(SCOPE_CHAR_CROSS_SAVE,), owner_ids=("爱丽丝",))
    )
    assert [r.id for r in alice_only] == [id_alice]

    assert memory_repo.set_pinned(id_alice, True) is True
    pinned_only = memory_repo.list_by_scope(
        MemoryScopeFilter(owner_ids=("爱丽丝",), only_pinned=True)
    )
    assert [r.id for r in pinned_only] == [id_alice]

    assert memory_repo.delete(id_self) is True
    assert memory_repo.get(id_self) is None
    assert memory_repo.delete("non-existent") is False


def test_repository_contract_cjk_japanese_english_hybrid_search(memory_repo: MemoryRepository):
    embedder = DeterministicHashEmbedder(dimensions=64)
    samples = [
        ("m-cn", "花火大会那天约定明年一起去京都看红叶", ("花火大会", "京都"), 10.0),
        ("m-jp", "狛枝凪斗は希望ヶ峰学園の生徒で幸運を持っている", ("希望ヶ峰学園",), 20.0),
        ("m-en", "Project Chimera launch code is Aurora-7749", ("Chimera",), 30.0),
    ]
    for mid, text, tags, ts in samples:
        memory_repo.upsert(
            MemoryRecord(
                id=mid,
                scope=SCOPE_CHAR_CROSS_SAVE,
                owner_id="Nagito",
                detail_text=text,
                topic_tags=tags,
                created_at=ts,
                event_at=ts * 100.0,
                embedding=embedder.embed_query(text),
            )
        )

    # Pure keyword FTS query for CJK phrase
    cn_hits = memory_repo.search_candidates(
        MemoryCandidateQuery(
            scope_filter=MemoryScopeFilter(owner_ids=("Nagito",)),
            keyword_query="京都 红叶",
            limit=5,
        )
    )
    assert cn_hits and cn_hits[0].record.id == "m-cn"
    assert cn_hits[0].fts_score > 0.0

    # Japanese kanji/kana query
    jp_hits = memory_repo.search_candidates(
        MemoryCandidateQuery(
            scope_filter=MemoryScopeFilter(owner_ids=("Nagito",)),
            keyword_query="希望ヶ峰学園",
            limit=5,
        )
    )
    assert jp_hits and jp_hits[0].record.id == "m-jp"

    # Multi-clause Max-Pool vector + keyword hybrid query
    multi_hits = memory_repo.search_candidates(
        MemoryCandidateQuery(
            scope_filter=MemoryScopeFilter(owner_ids=("Nagito",)),
            query_vectors=(
                embedder.embed_query("unrelated clause"),
                embedder.embed_query("Project Chimera launch code is Aurora-7749"),
            ),
            keyword_query="Aurora 7749",
            limit=5,
        )
    )
    assert multi_hits[0].record.id == "m-en"
    assert multi_hits[0].vector_score > 0.99

    # Temporal event_from / event_to bounds
    window_hits = memory_repo.search_candidates(
        MemoryCandidateQuery(
            scope_filter=MemoryScopeFilter(
                owner_ids=("Nagito",),
                event_from=1500.0,
                event_to=2500.0,
            ),
            keyword_query="希望ヶ峰学園",
            limit=5,
        )
    )
    assert [h.record.id for h in window_hits] == ["m-jp"]


def test_repository_contract_slot_superseding_and_transitive_rollback(
    memory_repo: MemoryRepository,
):
    # v1 at turn 2 -> superseded by v2 at turn 5 -> superseded by v3 at turn 8
    memory_repo.upsert(
        MemoryRecord(
            id="drink-v1",
            scope=SCOPE_SAVE_ISOLATED,
            owner_id="Alice",
            slot_key="profile:favorite_drink",
            detail_text="爱丽丝最喜欢红茶",
            source_session_id="save-1",
            source_turn_seq=2,
            created_at=10.0,
        )
    )
    memory_repo.upsert(
        MemoryRecord(
            id="drink-v2",
            scope=SCOPE_SAVE_ISOLATED,
            owner_id="Alice",
            slot_key="profile:favorite_drink",
            detail_text="爱丽丝改喝乌龙茶了",
            source_session_id="save-1",
            source_turn_seq=5,
            created_at=20.0,
        )
    )
    memory_repo.upsert(
        MemoryRecord(
            id="drink-v3",
            scope=SCOPE_SAVE_ISOLATED,
            owner_id="Alice",
            slot_key="profile:favorite_drink",
            detail_text="爱丽丝最近只喝冰美式",
            source_session_id="save-1",
            source_turn_seq=8,
            created_at=30.0,
        )
    )
    # Pinned memory and canon memory should survive rollback even if turn_seq > 3
    memory_repo.upsert(
        MemoryRecord(
            id="pinned-note",
            scope=SCOPE_SAVE_ISOLATED,
            owner_id="Alice",
            detail_text="关键锚点：已解锁地下室钥匙",
            pinned=True,
            source_session_id="save-1",
            source_turn_seq=9,
            created_at=35.0,
        )
    )
    memory_repo.upsert(
        MemoryRecord(
            id="canon-note",
            scope=SCOPE_CHAR_CANON,
            owner_id="Alice",
            detail_text="出厂设定：皇家学院二年级生",
            source_session_id="save-1",
            source_turn_seq=9,
            created_at=36.0,
        )
    )
    # Cross-save memory extracted on turn 7 of save-1 SHOULD also roll back!
    memory_repo.upsert(
        MemoryRecord(
            id="cross-save-turn7",
            scope=SCOPE_CHAR_CROSS_SAVE,
            owner_id="Alice",
            detail_text="第7轮提取的跨存档记忆",
            source_session_id="save-1",
            source_turn_seq=7,
            created_at=28.0,
        )
    )
    # Other session's memory at turn 10 must be untouched
    memory_repo.upsert(
        MemoryRecord(
            id="other-save",
            scope=SCOPE_SAVE_ISOLATED,
            owner_id="Alice",
            detail_text="另一个存档的记忆",
            source_session_id="save-2",
            source_turn_seq=10,
            created_at=40.0,
        )
    )

    active_before = memory_repo.list_by_scope(
        MemoryScopeFilter(
            scopes=(SCOPE_SAVE_ISOLATED,),
            owner_ids=("Alice",),
            session_id="save-1",
        )
    )
    assert {r.id for r in active_before} == {"drink-v3", "pinned-note"}

    # Rewind save-1 back to turn 3: drink-v2, drink-v3, cross-save-turn7 deleted, drink-v1 restored!
    deleted_count = memory_repo.rollback_after_turn("save-1", 3)
    assert deleted_count == 3

    v1 = memory_repo.get("drink-v1")
    assert v1 is not None and v1.superseded_by is None
    assert memory_repo.get("drink-v2") is None
    assert memory_repo.get("drink-v3") is None
    assert memory_repo.get("cross-save-turn7") is None
    assert memory_repo.get("pinned-note") is not None
    assert memory_repo.get("canon-note") is not None
    assert memory_repo.get("other-save") is not None


def test_repository_contract_entity_expansion_and_recall_reinforcement(
    memory_repo: MemoryRepository,
):
    memory_repo.upsert(
        MemoryRecord(
            id="e1",
            scope=SCOPE_CHAR_CROSS_SAVE,
            owner_id="Alice",
            detail_text="白银怀表藏在旧钟楼顶层",
            entities=("白银怀表", "旧钟楼"),
            importance=0.9,
            created_at=10.0,
        )
    )
    memory_repo.upsert(
        MemoryRecord(
            id="e2",
            scope=SCOPE_CHAR_CROSS_SAVE,
            owner_id="Bob",
            detail_text="Bob 也听说过旧钟楼",
            entities=("旧钟楼",),
            importance=0.95,
            created_at=20.0,
        )
    )

    expanded = memory_repo.expand_entities(
        ("旧钟楼",),
        MemoryScopeFilter(scopes=(SCOPE_CHAR_CROSS_SAVE,), owner_ids=("Alice",)),
    )
    assert [r.id for r in expanded] == ["e1"]

    updated = memory_repo.record_recall(("e1",), recalled_at=500.0)
    assert updated == 1
    refreshed = memory_repo.get("e1")
    assert refreshed is not None
    assert refreshed.recall_count == 1
    assert refreshed.last_recalled_at == 500.0


def test_static_vector_store_contract_and_cache_coherence(slice_store: StaticVectorStorePort):
    embedder = DeterministicHashEmbedder(dimensions=32)
    entries = [
        VectorSliceEntry(
            id=f"k-{i}",
            namespace=NAMESPACE_KNOWLEDGE,
            scope_id="worldbook_a" if i < 3 else "worldbook_b",
            text=f"设定条目 {i}：星辰之塔第 {i} 层封印",
            metadata={"user_id": "worldbook_a" if i < 3 else "worldbook_b", "tier": i},
            created_at=float(i + 1),
            embedding=embedder.embed_query(f"设定条目 {i}：星辰之塔第 {i} 层封印"),
        )
        for i in range(5)
    ]
    assert slice_store.upsert_slices(entries) == 5
    assert dict(slice_store.count_by_scope(namespace=NAMESPACE_KNOWLEDGE)) == {
        "worldbook_a": 3,
        "worldbook_b": 2,
    }

    q_vec = embedder.embed_query("设定条目 2：星辰之塔第 2 层封印")
    hits = slice_store.search_slices(
        namespace=NAMESPACE_KNOWLEDGE,
        scope_ids=("worldbook_a", "worldbook_b"),
        query_vector=q_vec,
        keyword_query="星辰之塔 2",
        limit=3,
    )
    assert hits[0].entry.id == "k-2"

    # Mutating the scope must invalidate any in-memory NumPy matrix cache immediately
    assert slice_store.delete_slice(namespace=NAMESPACE_KNOWLEDGE, slice_id="k-2") is True
    hits_after_delete = slice_store.search_slices(
        namespace=NAMESPACE_KNOWLEDGE,
        scope_ids=("worldbook_a",),
        query_vector=q_vec,
        limit=5,
    )
    assert all(h.entry.id != "k-2" for h in hits_after_delete)

    page = slice_store.list_slices(
        namespace=NAMESPACE_KNOWLEDGE,
        scope_id="worldbook_a",
        offset=0,
        limit=10,
    )
    assert [e.id for e in page] == ["k-0", "k-1"]
    assert slice_store.delete_scope(namespace=NAMESPACE_KNOWLEDGE, scope_id="worldbook_b") == 2
    assert dict(slice_store.count_by_scope(namespace=NAMESPACE_KNOWLEDGE)) == {"worldbook_a": 2}


def test_end_to_end_hybrid_engine_operations_media_knowledge_and_di_registry(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)
    embedder = DeterministicHashEmbedder(dimensions=384)
    register_embedding_provider(
        EmbeddingProviderContribution(
            provider="test-hash",
            factory=lambda: embedder,
            priority=1,
        )
    )
    try:
        engine = HybridMemoryEngine.from_config(
            {
                "embedder": {"config": {"model": str(tmp_path / "dummy-snapshot"), "embedding_dims": 384}},
                "vector_store": {"config": {"path": str(tmp_path / "shinsekai_store.db")}},
            }
        )
        monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)
        monkeypatch.setattr(media_assets, "ensure_mem0", lambda: engine)

        # 1. Memory remember + dedup + search + list + forget
        r1 = operations.memory_remember("狛枝凪斗喜欢吃抹茶甜点", character_name="狛枝凪斗")
        assert r1["ok"] is True and r1["duplicate"] is False

        r_dup = operations.memory_remember("狛枝凪斗喜欢吃抹茶甜点", character_name="狛枝凪斗")
        assert r_dup["ok"] is True and r_dup["duplicate"] is True

        listed = operations.memory_list("狛枝凪斗")
        assert listed["count"] == 1
        mem_id = listed["memories"][0]["id"]

        searched = operations.memory_search("抹茶甜点", character_name="狛枝凪斗")
        assert searched["count"] == 1
        assert searched["memories"][0]["id"] == mem_id

        # 2. Media assets batch indexing + stale fingerprint cleanup + search
        cands_v1 = [
            {"asset_id": "sp-1", "path": "smile.png", "tags": "温柔微笑 开心"},
            {"asset_id": "sp-2", "path": "angry.png", "tags": "生气 愤怒 皱眉"},
        ]
        idx1 = media_assets.ensure_media_asset_indexes(
            [{"scope": "sprite:Nagito", "candidates": cands_v1}]
        )
        assert idx1 == {"catalogCount": 1, "assetCount": 2, "addedCount": 2}
        idx2 = media_assets.ensure_media_asset_indexes(
            [{"scope": "sprite:Nagito", "candidates": cands_v1}]
        )
        assert idx2["addedCount"] == 0

        matches = media_assets.search_media_assets(
            scope="sprite:Nagito",
            vibe="生气 愤怒",
            candidates=cands_v1,
            limit=2,
        )
        assert matches and matches[0]["asset_id"] == "sp-2"

        # Changing catalog candidates replaces stale fingerprint slices cleanly
        cands_v2 = [{"asset_id": "sp-3", "path": "shock.png", "tags": "惊讶 瞳孔地震"}]
        media_assets.ensure_media_asset_indexes(
            [{"scope": "sprite:Nagito", "candidates": cands_v2}]
        )
        assert dict(engine.vector_store.count_by_scope(namespace=NAMESPACE_MEDIA_ASSET)) == {
            "__shinsekai_media__:sprite:nagito": 1
        }

        assert operations.memory_forget(mem_id)["ok"] is True
        assert operations.memory_list("狛枝凪斗")["count"] == 0

        # 3. HybridKnowledgeStore + catalog counts + multi-KB search
        kb_store = HybridKnowledgeStore.from_config(
            {
                "embedder": {"config": {"model": str(tmp_path / "dummy-snapshot"), "embedding_dims": 384}},
                "vector_store": {"config": {"path": str(tmp_path / "knowledge_vectors.db")}},
            }
        )
        try:
            catalog.invalidate_knowledge_catalog()
            w1 = add_knowledge_entry(kb_store, "希望峰学园第77期学生住在贾巴沃克岛", "danganronpa")
            assert w1["ok"] is True and w1["duplicate"] is False
            w_dup = add_knowledge_entry(kb_store, "希望峰学园第77期学生住在贾巴沃克岛", "danganronpa")
            assert w_dup["duplicate"] is True

            add_knowledge_entry(kb_store, "黑白熊是希望峰学园的自称学园长", "monokuma_lore")
            counts = catalog.get_knowledge_entry_counts(
                kb_store.vector_store.client,
                kb_store.vector_store.collection_name,
                refresh=True,
            )
            assert counts == {"danganronpa": 1, "monokuma_lore": 1}

            kb_hits = search_knowledge(
                kb_store,
                "贾巴沃克岛",
                knowledge_ids=["danganronpa", "monokuma_lore"],
                limit=5,
            )
            assert kb_hits["count"] >= 1
            assert kb_hits["memories"][0]["knowledge_id"] == "danganronpa"

            local_hits = search_local_knowledge_entries(kb_store, "monokuma_lore", "黑白熊")
            assert local_hits["count"] == 1
        finally:
            kb_store.close()
            engine.close()

        # 4. Custom MemoryRepository DI override check
        custom_repo = InMemoryMemoryRepository()
        register_memory_repository(
            MemoryRepositoryContribution(
                provider="custom-in-memory",
                factory=lambda: custom_repo,
                priority=1,
            )
        )
        di_engine = HybridMemoryEngine.from_config(
            {
                "embedder": {"config": {"model": str(tmp_path / "dummy-snapshot"), "embedding_dims": 384}},
                "vector_store": {"config": {"path": str(tmp_path / "di_store.db")}},
            }
        )
        try:
            assert di_engine.repo is custom_repo
        finally:
            di_engine.close()
    finally:
        clear_memory_adapter_registrations()
        clear_shared_onnx_embedders()


def test_media_assets_identical_catalogs_across_scopes_do_not_collide_or_overwrite(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SHINSEKAI_MEMORY_SERVICE_URL", raising=False)

    base_embedder = DeterministicHashEmbedder(dimensions=384)
    embed_doc_calls: list[list[str]] = []

    class _CountingEmbedder:
        dimensions = 384

        def embed_query(self, text: str):
            return base_embedder.embed_query(text)

        def embed_documents(self, texts, *, batch_size: int = 32):
            del batch_size
            batch = list(texts)
            embed_doc_calls.append(batch)
            return base_embedder.embed_documents(batch)

        def status(self):
            return base_embedder.status()

    store = SqliteHybridStore(tmp_path / "shared_media_scopes.db")
    engine = HybridMemoryEngine(
        embedder=_CountingEmbedder(),
        repo=SqliteHybridMemoryRepo(store),
        vector_store=store,
        store=store,
    )
    monkeypatch.setattr(media_assets, "ensure_mem0", lambda: engine)

    shared_candidates = [
        {"asset_id": "outfit-smile", "path": "shared/smile.png", "tags": "温柔微笑 开心 放松"},
        {"asset_id": "outfit-serious", "path": "shared/serious.png", "tags": "严肃 认真 冷静"},
    ]
    try:
        # Index identical candidate catalogs under two distinct character scopes
        idx_res = media_assets.ensure_media_asset_indexes(
            [
                {"scope": "sprite:Alice", "candidates": shared_candidates},
                {"scope": "sprite:Bob", "candidates": shared_candidates},
            ]
        )
        assert idx_res == {"catalogCount": 2, "assetCount": 4, "addedCount": 4}
        assert len(embed_doc_calls) == 2
        assert dict(store.count_by_scope(namespace=NAMESPACE_MEDIA_ASSET)) == {
            "__shinsekai_media__:sprite:alice": 2,
            "__shinsekai_media__:sprite:bob": 2,
        }

        # Alternating searches across both scopes must hit existing indexes without re-embedding
        embed_doc_calls.clear()
        alice_hits = media_assets.search_media_assets(
            scope="sprite:Alice",
            vibe="温柔微笑",
            candidates=shared_candidates,
            limit=2,
        )
        bob_hits = media_assets.search_media_assets(
            scope="sprite:Bob",
            vibe="严肃 冷静",
            candidates=shared_candidates,
            limit=2,
        )
        alice_hits_again = media_assets.search_media_assets(
            scope="sprite:Alice",
            vibe="开心",
            candidates=shared_candidates,
            limit=2,
        )
        assert alice_hits[0]["asset_id"] == "outfit-smile"
        assert bob_hits[0]["asset_id"] == "outfit-serious"
        assert alice_hits_again[0]["asset_id"] == "outfit-smile"
        assert embed_doc_calls == []

        # Updating Alice's catalog must NOT evict or overwrite Bob's catalog slices
        alice_updated = [
            {"asset_id": "outfit-smile", "path": "shared/smile.png", "tags": "温柔微笑 开心 放松"},
            {"asset_id": "outfit-surprised", "path": "alice/surprised.png", "tags": "惊讶 脸红"},
            {"asset_id": "outfit-wink", "path": "alice/wink.png", "tags": "眨眼 俏皮"},
        ]
        media_assets.ensure_media_asset_indexes(
            [{"scope": "sprite:Alice", "candidates": alice_updated}]
        )
        assert dict(store.count_by_scope(namespace=NAMESPACE_MEDIA_ASSET)) == {
            "__shinsekai_media__:sprite:alice": 3,
            "__shinsekai_media__:sprite:bob": 2,
        }

        # Bob's index remains intact and requires zero re-indexing
        embed_doc_calls.clear()
        bob_after_alice_update = media_assets.search_media_assets(
            scope="sprite:Bob",
            vibe="温柔微笑",
            candidates=shared_candidates,
            limit=2,
        )
        assert bob_after_alice_update[0]["asset_id"] == "outfit-smile"
        assert embed_doc_calls == []
    finally:
        engine.close()
