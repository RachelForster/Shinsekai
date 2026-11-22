"""Phase 3 tests for dual-granularity extraction, hook priority, wakeup, cooldown, and tools."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

import pytest

from ai.llm.template.session import (
    LEGACY_MEMORY_CONTEXT_MARKERS,
    MEMORY_CONTEXT_MARKER,
)
from ai.memory import operations
from ai.memory.backends.in_memory import DeterministicHashEmbedder
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
from ai.memory.engine import HybridMemoryEngine
from ai.memory.extraction import (
    MemoryExtractor,
    derive_fallback_gist,
    parse_memory_drafts,
)
from ai.memory.hooks import MemoryAutoHooks
from ai.memory.queue import MemoryWriteQueue
from ai.tools.memory_tools import _tool_memory_forget, _tool_memory_remember, _tool_memory_search
from application.chat.capabilities.contracts import StartupCapabilityContext
from application.chat.capabilities.memory import MemorySessionCapability
from application.memory.manage_memories import recall_turn_memories
from application.perception.hooks import PerceptionAutoHooks
from core.chat_history.identity import CHAT_TURN_ID
from core.chat_history import sqlite_session_store
from core.chat_history.models import turn_node_from_message
from core.chat_history.sqlite_session_store import SqliteSessionStore
from core.chat_history.storage import close_session_store, open_session_store
from frontend_bridge_core import memory as bridge_memory
from frontend_bridge_core.routes import memory_routes
from core.perception.cache import PROACTIVE_TURN_INSTRUCTION, RPInputCache
from core.perception.gatekeeper import PerceptionGatekeeper
from core.perception.models import PerceptionDigestResult
from sdk.adapters.memory import (
    SCOPE_CHAR_CANON,
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SAVE_ISOLATED,
    SCOPE_SELF_PUBLIC,
    ExtractionWindow,
    MemoryDraft,
    MemoryExtractorPort,
    MemoryScopeFilter,
)
from sdk.adapters.session import (
    MEMORY_MODE_INHERIT_READONLY,
    MEMORY_MODE_ISOLATED,
    MEMORY_MODE_SHARED,
)
from sdk.hooks import (
    BeforeChatContext,
    BeforeCompactContext,
    MessageAddedContext,
    PluginHookDispatcher,
)
from test.mocks import MockLLMAdapter


def test_memory_extractor_port_parses_dual_granularity_temporal_slots_and_guards_speakers():
    raw_json = json.dumps(
        [
            {
                "character_name": "user",
                "detail": "用户偏爱喝少冰半糖的茉莉奶绿（外卖常点大杯）",
                "gist": "喜欢喝少冰半糖茉莉奶绿",
                "kind": "profile",
                "slot_key": "profile:tea_preference",
                "topics": ["饮品", "奶茶"],
                "entities": ["茉莉奶绿"],
                "importance": 0.65,
                "event_time": None,
            },
            {
                "character_name": "user",
                "detail": "用户改口说最近戒糖改喝无糖纯茶茉莉奶绿了",
                "gist": "",  # Omitted -> derive_fallback_gist kicks in!
                "kind": "profile",
                "slot_key": "profile:tea_preference",
                "topics": ["饮品"],
                "entities": ["茉莉奶绿"],
                "importance": 0.78,
                "event_time": None,
            },
            {
                "character_name": "Nanami",
                "detail": "Nanami和用户约定明天晚上八点联机打怪物猎人荒野",
                "gist": "约定联机打怪物猎人",
                "kind": "promise",
                "slot_key": "",
                "topics": ["游戏", "约定"],
                "entities": ["怪物猎人荒野"],
                "importance": 0.9,
                "event_time": "明天",
            },
            {
                # Hallucinated out-of-scene speaker -> guarded back to primary scene character ("Mika")
                "character_name": "GhostNPC",
                "detail": "提到后山神社有一棵百年银杏树",
                "gist": "后山神社有古银杏",
                "kind": "episodic",
                "entities": ["后山神社"],
                "importance": 0.55,
                "event_time": "2026-11-10",
            },
        ],
        ensure_ascii=False,
    )
    adapter = MockLLMAdapter(responses=[raw_json])
    extractor = MemoryExtractor(adapter)
    assert isinstance(extractor, MemoryExtractorPort)

    window = ExtractionWindow(
        messages=(
            {"role": "user", "content": "明天晚上八点我们联机打怪猎吧！"},
            {
                "role": "assistant",
                "content": '{"dialog":[{"character_name":"Nanami","speech":"一言为定！"}]}',
            },
        ),
        character_names=("Mika", "Nanami"),
        now_iso="2026-11-15T10:00:00+08:00",
        session_id="sess-ext",
        turn_seq=18,
    )
    drafts = extractor.extract(window)
    # Same-window slot_key `profile:tea_preference` deduplicated to latest entry -> 3 drafts total!
    assert len(drafts) == 3

    tea_draft = drafts[0]
    assert tea_draft.scope == SCOPE_SELF_PUBLIC
    assert tea_draft.owner_id == "__self__"
    assert tea_draft.slot_key == "profile:tea_preference"
    assert "无糖纯茶" in tea_draft.detail_text
    assert tea_draft.gist_text == derive_fallback_gist(tea_draft.detail_text)

    promise_draft = drafts[1]
    assert promise_draft.scope == SCOPE_CHAR_CROSS_SAVE
    assert promise_draft.owner_id == "Nanami"
    assert promise_draft.kind == "promise"
    assert promise_draft.entities == ("怪物猎人荒野",)
    assert promise_draft.event_at is not None
    assert promise_draft.source_session_id == "sess-ext"
    assert promise_draft.source_turn_seq == 18

    guarded_draft = drafts[2]
    assert guarded_draft.owner_id == "Mika"
    assert guarded_draft.entities == ("后山神社",)


def test_proactive_perception_turn_runs_perception_hook_before_memory_hook_and_skips_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    embedder = DeterministicHashEmbedder(dimensions=384)
    global_repo = SqliteHybridMemoryRepo(tmp_path / "global_mem.db")
    engine = HybridMemoryEngine(embedder=embedder, repo=global_repo)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)
    monkeypatch.setattr(operations, "_memory_service_url", lambda: "")

    try:
        # Seed a long-term memory about boss Malenia / Elden Ring
        engine.orchestrator.ingest_drafts(
            [
                MemoryDraft(
                    owner_id="Mika",
                    scope=SCOPE_CHAR_CROSS_SAVE,
                    detail_text="Mika曾提醒用户打女武神玛莲妮亚时一定要用冰冻壶打断水鸟乱舞",
                    gist_text="打玛莲妮亚可用冰冻壶断水鸟乱舞",
                    entities=("玛莲妮亚", "水鸟乱舞"),
                    importance=0.9,
                )
            ]
        )

        # Register MemoryAutoHooks FIRST and PerceptionAutoHooks SECOND on the same dispatcher!
        # Priority ordering (100 < 150) MUST still run PerceptionAutoHooks BEFORE MemoryAutoHooks!
        dispatcher = PluginHookDispatcher()
        llm_extractor_mock = MockLLMAdapter(
            responses=['[{"character_name":"Mika","detail":"不应被提取的画面记忆"}]']
        )
        mem_hooks = MemoryAutoHooks(
            llm_adapter=llm_extractor_mock,
            character_names=["Mika"],
            queue=MemoryWriteQueue(path=tmp_path / "queue.json"),
            extract_interval_turns=1,
        )
        mem_hooks.register(dispatcher)

        rp_cache = RPInputCache()
        gatekeeper = PerceptionGatekeeper()
        perc_hooks = PerceptionAutoHooks(
            rp_input_cache=rp_cache,
            gatekeeper=gatekeeper,
            is_enabled=lambda: True,
        )
        perc_hooks.register(dispatcher)

        now = time.time()
        rp_cache.record_decision(
            PerceptionDigestResult(
                digest="玩家走进圣树底层雾门挑战女武神玛莲妮亚，被水鸟乱舞秒杀",
                salience=0.92,
                mood="tense",
                game="艾尔登法环",
                created_at=now,
            )
        )
        assert perc_hooks.prepare_turn("turn-perc-1", "perception") is True

        proactive_msg = {
            "role": "user",
            "source": "perception",
            CHAT_TURN_ID: "turn-perc-1",
            "content": PROACTIVE_TURN_INSTRUCTION,
        }
        ctx = BeforeChatContext(
            messages=[{"role": "system", "content": "Sys"}, proactive_msg],
            tools=None,
            generation_kwargs={},
            stream=False,
        )
        dispatcher.dispatch_before_chat(ctx)

        # 1. Perception hook attached game cache AND Memory hook recalled Malenia tip!
        assert "[Shinsekai realtime game perception cache]" in str(proactive_msg["content"])
        assert any(
            MEMORY_CONTEXT_MARKER in str(m.get("content") or "")
            and "冰冻壶" in str(m.get("content") or "")
            for m in ctx.messages
        )

        # 2. Perception messages NEVER trigger memory extraction in message_added or before_compact!
        dispatcher.dispatch_message_added(
            MessageAddedContext(role="user", message=proactive_msg, messages=ctx.messages)
        )
        dispatcher.dispatch_message_added(
            MessageAddedContext(
                role="assistant",
                message={"role": "assistant", "content": "快扔冰冻壶呀！"},
                messages=ctx.messages,
            )
        )
        dispatcher.dispatch_before_compact(
            BeforeCompactContext(
                messages=[proactive_msg],
                older_messages=[proactive_msg],
                recent_messages=[],
                session_id="s1",
                up_to_seq=2,
            )
        )
        mem_hooks.wait_for_idle()
        assert llm_extractor_mock.call_history == []
    finally:
        global_repo.close()


def test_memory_hooks_three_turn_cooldown_and_four_hour_session_wakeup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    embedder = DeterministicHashEmbedder(dimensions=384)
    global_repo = SqliteHybridMemoryRepo(tmp_path / "global_wakeup.db")
    engine = HybridMemoryEngine(embedder=embedder, repo=global_repo)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)
    monkeypatch.setattr(operations, "_memory_service_url", lambda: "")

    clock = [1_763_000_000.0]

    try:
        engine.orchestrator.ingest_drafts(
            [
                MemoryDraft(
                    owner_id="Mika",
                    scope=SCOPE_CHAR_CROSS_SAVE,
                    kind="promise",
                    detail_text="约定周末一起去秋叶原无线电会馆淘老镜头",
                    gist_text="约定周末去秋叶原淘镜头",
                    importance=0.9,
                )
            ],
            now_ts=clock[0],
        )

        hooks = MemoryAutoHooks(
            llm_adapter=MockLLMAdapter(),
            character_names=["Mika"],
            queue=MemoryWriteQueue(path=tmp_path / "q.json"),
            cooldown_turns=3,
            clock_func=lambda: clock[0],
        )

        def run_turn(user_text: str) -> list[dict]:
            msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": user_text}]
            hooks.before_chat(
                BeforeChatContext(messages=msgs, tools=None, generation_kwargs={}, stream=False)
            )
            hooks.message_added(
                MessageAddedContext(role="user", message={"role": "user", "content": user_text}, messages=msgs)
            )
            hooks.message_added(
                MessageAddedContext(role="assistant", message={"role": "assistant", "content": "好呀"}, messages=msgs)
            )
            return msgs

        # Turn 1: Direct query -> injected!
        t1_msgs = run_turn("我们去秋叶原无线电会馆淘老镜头的约定还在吗？")
        assert any("无线电会馆" in str(m.get("content")) for m in t1_msgs if m["role"] == "system")

        # Turn 2, 3, 4 (within 3-turn cooldown): NOT re-injected repetitively!
        clock[0] += 30
        t2_msgs = run_turn("秋叶原无线电会馆几点开门？")
        assert not any("无线电会馆" in str(m.get("content")) for m in t2_msgs if m["role"] == "system")

        clock[0] += 30
        run_turn("今天中午吃咖喱饭吧")
        clock[0] += 30
        run_turn("下午还要写作业呢")

        # Turn 5 (cooldown window of 3 turns has rolled past, AND >4h session wakeup elapsed!):
        clock[0] += 5 * 3600.0  # 5 hours later!
        wakeup_msgs = run_turn("早安")
        assert any(
            "无线电会馆" in str(m.get("content"))
            for m in wakeup_msgs
            if m["role"] == "system"
        )
    finally:
        global_repo.close()


def test_bound_memory_tools_route_into_active_save_and_release_windows_sqlite_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    embedder = DeterministicHashEmbedder(dimensions=384)
    global_db_path = tmp_path / "global_tools.db"
    global_repo = SqliteHybridMemoryRepo(global_db_path)
    engine = HybridMemoryEngine(embedder=embedder, repo=global_repo)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)
    monkeypatch.setattr(operations, "_memory_service_url", lambda: "")

    save_dir = tmp_path / "conversations" / "save_isolated_tool"
    session_store = SqliteSessionStore(save_dir, session_id="save_isolated_tool")
    session_store.set_memory_mode(MEMORY_MODE_ISOLATED)

    token = operations.bind_memory_tool_context(
        session_id="save_isolated_tool",
        memory_mode=MEMORY_MODE_INHERIT_READONLY,
        player_character="骑士雷恩",
    )
    try:
        # Tool call writes a slotted memory; bound context routes strictly to save_repo!
        res1 = _tool_memory_remember(
            content="骑士雷恩佩带着银白圣剑",
            character_name="user",
            slot_key="equip:weapon",
            kind="profile",
        )
        assert res1["ok"] is True
        assert res1["duplicate"] is False

        # Supersede same slot via tool
        res2 = _tool_memory_remember(
            content="骑士雷恩将武器换成了黑曜石长枪",
            character_name="user",
            slot_key="equip:weapon",
            kind="profile",
        )
        assert res2["ok"] is True
        assert res2.get("superseded_ids") == [res1["id"]]

        # Global repo remains completely empty (no leakage!)
        assert (
            global_repo.list_by_scope(MemoryScopeFilter(scopes=(SCOPE_SELF_PUBLIC,))) == ()
        )
        assert (
            len(
                session_store.save_memory_repo.list_by_scope(
                    MemoryScopeFilter(scopes=(SCOPE_SAVE_ISOLATED,))
                )
            )
            == 1
        )

        # Tool search finds the updated weapon in the isolated save and returns clarity metadata
        search_res = _tool_memory_search(query="骑士雷恩的武器长枪", character_name="user")
        assert search_res["count"] == 1
        assert search_res["memories"][0]["memory"] == "骑士雷恩将武器换成了黑曜石长枪"
        assert search_res["memories"][0]["clarity"] == "clear"

        # Application use-case `recall_turn_memories` (/api/memory/recall) also honors isolated save
        bridge_recall = recall_turn_memories(
            {
                "userText": "骑士雷恩现在用什么武器长枪？",
                "activeCharacterNames": ["Mika"],
                "sessionId": "save_isolated_tool",
                "memoryMode": MEMORY_MODE_ISOLATED,
            }
        )
        assert bridge_recall["ok"] is True
        assert search_res["memories"][0]["id"] == res2["id"]
        assert bridge_recall["recalled_ids"] == [res2["id"]]
        assert '黑曜石长枪' in bridge_recall["rendered"]
        assert _tool_memory_forget(res2["id"])["ok"]
        assert session_store.save_memory_repo.get(res2["id"]) is None
        assert "error" in _tool_memory_forget(res2["id"])
    finally:
        operations.reset_memory_tool_context(token)
        session_store.close()
        global_repo.close()

    # Verify zero leaked SQLite file descriptors on Windows (unlink succeeds cleanly)
    (save_dir / "history.db").unlink()
    global_db_path.unlink()


def test_cold_bridge_resolves_managed_save_without_writing_globally(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sqlite_session_store, "_known_session_db_paths", {})
    monkeypatch.setattr(operations, "_memory_service_url", lambda: "")
    monkeypatch.setattr(bridge_memory, "_check_mem0_before_call", lambda: None)
    shared = SqliteHybridMemoryRepo(tmp_path / "shared.db")
    engine = HybridMemoryEngine(embedder=DeterministicHashEmbedder(dimensions=384), repo=shared)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)
    directory = tmp_path / "data" / "chat_history" / "story-save"
    directory.mkdir(parents=True)
    (directory / "story-v2.json").touch()
    store = SqliteSessionStore(directory)
    sid = store.session_id
    store.close()
    # Simulate the bridge before it has seen the chat child's path registry.
    sqlite_session_store._known_session_db_paths.clear()

    def request(route, **body):
        return route(SimpleNamespace(body=body)).data

    try:
        written = request(
            memory_routes._memory_remember,
            content="Mika promised to bring the amber compass",
            characterName="Mika",
            sourceSessionId=sid,
        )
        assert written["ok"]
        assert shared.get(written["id"]) is None
        found = request(
            memory_routes._memory_search,
            query="amber compass",
            characterName="Mika",
            sessionId=sid,
        )
        assert [row["id"] for row in found["memories"]] == [written["id"]]
        recalled = request(
            memory_routes._memory_recall,
            userText="Where is the amber compass?",
            activeCharacterNames=["Mika"],
            sessionId=sid,
        )
        assert written["id"] in recalled["recalled_ids"]
        assert request(
            memory_routes._memory_forget, memoryId=written["id"], sessionId=sid,
        )["ok"]
        assert "error" in request(
            memory_routes._memory_forget, memoryId=written["id"], sessionId=sid,
        )
        for mode in ("", MEMORY_MODE_ISOLATED, MEMORY_MODE_INHERIT_READONLY):
            failed = request(
                memory_routes._memory_remember,
                content="This must never enter global memory",
                characterName="Mika",
                sourceSessionId="absent",
                memoryMode=mode,
            )
            assert "error" in failed
        assert not shared.list_by_scope(MemoryScopeFilter(scopes=(SCOPE_CHAR_CROSS_SAVE,)))
    finally:
        shared.close()


def test_dialogue_cannot_create_canon(tmp_path, monkeypatch):
    row = {"character_name": "Mika", "detail": "Mika says she can see through walls", "kind": "CANON"}
    drafts = parse_memory_drafts(json.dumps([row]), character_names=["Mika"])
    assert [draft.kind for draft in drafts] == ["episodic"]

    repo = SqliteHybridMemoryRepo(tmp_path / "global.db")
    engine = HybridMemoryEngine(embedder=DeterministicHashEmbedder(dimensions=384), repo=repo)
    monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)
    monkeypatch.setattr(operations, "_memory_service_url", lambda: "")
    try:
        result = _tool_memory_remember(row["detail"], character_name="Mika", kind="canon")
        record = repo.get(result["id"])
        assert record.scope == SCOPE_CHAR_CROSS_SAVE and record.kind == "episodic"
        assert not record.pinned
        assert not repo.list_by_scope(MemoryScopeFilter(scopes=(SCOPE_CHAR_CANON,)))
    finally:
        repo.close()


def test_reopening_a_save_uses_the_previous_turn_for_offline_recall(tmp_path):
    directory = tmp_path / "save"
    directory.mkdir()
    past = 1_760_000_000
    offline = 9 * 24 * 60 * 60
    last_message = {"role": "assistant", "content": "Talk to you later"}
    store = open_session_store(directory)
    store.append_turn(turn_node_from_message(last_message, created_at_ms=past * 1000))
    # Proactive messages and internal tool calls should not reset the dialogue clock.
    store.append_turn(turn_node_from_message(
        {"role": "user", "source": "perception", "content": "Camera event"},
        created_at_ms=(past + 60) * 1000,
    ))
    close_session_store(directory)
    open_session_store(directory)

    recorded = []
    adapter = MockLLMAdapter()

    def installer(_dispatcher, **kwargs):
        return MemoryAutoHooks(
            **kwargs,
            queue=MemoryWriteQueue(path=tmp_path / "queue.json"),
            clock_func=lambda: past + offline,
            recall_func=lambda turn: (recorded.append(turn) or {"ok": True}),
        )

    capability = MemorySessionCapability()
    prior_rollback = sqlite_session_store.get_default_shared_memory_rollback()
    try:
        capability.on_llm_ready(StartupCapabilityContext(
            args=SimpleNamespace(history=str(directory)),
            config=None,
            llm_adapter=adapter,
            llm_manager=None,
            plugin_manager=None,
            hook_dispatcher=PluginHookDispatcher(),
            character_names=("Mika",),
            runtime_imports=SimpleNamespace(install_memory_hooks=installer),
        ))
        capability.turn_context_providers()[0].before_chat(BeforeChatContext(
            messages=[last_message, {"role": "user", "content": "Hello"}],
            tools=None,
            generation_kwargs={},
            stream=False,
        ))

        assert len(recorded) == 1
        assert recorded[0].seconds_since_last_turn == offline
    finally:
        capability.on_shutdown()
        close_session_store(directory)
        sqlite_session_store.set_default_shared_memory_rollback(prior_rollback)


@pytest.mark.parametrize("story_file", ["story-v2.json", "story-prompt-binding.json"])
def test_legacy_shared_default_yields_to_story_but_explicit_shared_survives(tmp_path, story_file):
    directory = tmp_path / "story"
    directory.mkdir()
    store = SqliteSessionStore(directory)
    store.close()
    with sqlite3.connect(directory / "history.db") as conn:
        conn.execute("INSERT INTO session_meta (key, value) VALUES ('memory_mode', 'shared')")
    conn.close()
    store = SqliteSessionStore(directory)
    try:
        assert store.get_memory_mode() == MEMORY_MODE_SHARED
        (directory / story_file).touch()
        assert store.get_memory_mode() == MEMORY_MODE_ISOLATED
        store.set_memory_mode(MEMORY_MODE_SHARED)
    finally:
        store.close()
    store = SqliteSessionStore(directory)
    try:
        assert store.get_memory_mode() == MEMORY_MODE_SHARED
    finally:
        store.close()


def test_queue_preserves_distinct_save_modes_and_personas_after_reload(tmp_path):
    path = tmp_path / "queue.json"
    queue = MemoryWriteQueue(path=path)
    scopes = [
        ("save-a", MEMORY_MODE_ISOLATED, "Rin"),
        ("save-b", MEMORY_MODE_ISOLATED, "Rin"),
        ("save-a", MEMORY_MODE_INHERIT_READONLY, "Rin"),
        ("save-a", MEMORY_MODE_ISOLATED, "Noa"),
    ]
    for session, mode, persona in scopes:
        assert queue.enqueue(
            "The compass is amber",
            character_name="Mika",
            source_session_id=session,
            memory_mode=mode,
            player_character=persona,
        )["queued"]
    written = []

    def remember(_memory, _character_name, **kwargs):
        written.append((kwargs["source_session_id"], kwargs["memory_mode"], kwargs["player_character"]))
        return {"ok": True}

    restored = MemoryWriteQueue(path=path, remember_func=remember)
    assert restored.enqueue(
        "The compass is amber",
        character_name="Mika",
        source_session_id="save-a",
        memory_mode=MEMORY_MODE_ISOLATED,
        player_character="Rin",
    )["duplicate"]
    restored.flush()
    assert written == scopes
