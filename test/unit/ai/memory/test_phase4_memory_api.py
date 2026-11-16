"""Unit tests for Phase 4 memory operations: '自设' scope, rich list, pin/unpin, awaken, and session memoryMode."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import time
from types import SimpleNamespace

import pytest

from ai.memory import operations
from ai.memory.backends.in_memory import DeterministicHashEmbedder
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
from ai.memory.engine import HybridMemoryEngine
from ai.memory.hooks import MemoryAutoHooks
from ai.memory.queue import MemoryWriteQueue
from application.chat.capabilities.contracts import StartupCapabilityContext
from application.chat.capabilities.memory import MemorySessionCapability
from application.chat.conversation_library import (
    _id,
    conversation_details,
    remember_conversation,
    update_conversation_settings,
)
from application.chat.host.projection import _chat_session_preferences_patch
from config.schema import SELF_PERSONA_NAME
from core.chat_history.sqlite_session_store import (
    close_all_session_stores,
    close_session_store_for_dir,
    open_session_store_for_dir,
)
from frontend_bridge_core import memory as bridge_memory
from frontend_bridge_core.routes import memory_routes
from sdk.adapters.memory import (
    SCOPE_CHAR_CANON,
    SCOPE_CHAR_CROSS_SAVE,
    SCOPE_SELF_PUBLIC,
    TurnRecallInput,
)
from sdk.hooks import BeforeCompactContext, PluginHookDispatcher


@pytest.fixture()
def hybrid_engine(tmp_path, monkeypatch):
    repo = SqliteHybridMemoryRepo(tmp_path / "memory_hybrid.db")
    engine = HybridMemoryEngine(repo=repo, embedder=DeterministicHashEmbedder())
    monkeypatch.setattr(operations, "ensure_mem0", lambda: engine)
    monkeypatch.setattr(operations, "peek_mem0", lambda: engine)
    yield engine
    repo.close()
    close_all_session_stores()


def test_self_persona_memory_maps_to_self_public_scope(hybrid_engine):
    added = operations.memory_remember(
        "我在现实里养了一只名叫团子的布偶猫。",
        character_name=SELF_PERSONA_NAME,
        gist_text="养了一只叫团子的布偶猫",
        pinned=True,
    )
    assert added["scope"] == SCOPE_SELF_PUBLIC
    assert added["pinned"] is True

    listed = operations.memory_list(SELF_PERSONA_NAME)
    assert listed["count"] == 1
    item = listed["memories"][0]
    assert item["scope"] == SCOPE_SELF_PUBLIC
    assert item["pinned"] is True
    assert item["clarity"] == "canon"
    assert item["retention"] == 1.0
    assert item["gist"] == "养了一只叫团子的布偶猫"
    assert "团子" in item["detail"]


def test_pin_unpin_demotes_canon_for_ebbinghaus_decay_and_awaken_restores_clarity(
    hybrid_engine,
):
    now = time.time()
    thirty_days_ago = now - 30 * 86400.0

    res = operations.memory_remember(
        "Nanami小时候在海边捡到过一枚蓝色的玻璃浮球。",
        character_name="Nanami",
        gist_text="小时候海边捡到蓝色玻璃浮球",
        pinned=True,
        event_at=thirty_days_ago,
    )
    mem_id = res["id"]
    existing = hybrid_engine.repo.get(mem_id)
    assert existing is not None
    assert existing.scope == SCOPE_CHAR_CANON

    hybrid_engine.repo.upsert(
        replace(
            existing,
            created_at=thirty_days_ago,
            last_recalled_at=thirty_days_ago,
            importance=0.35,
        )
    )

    before_unpin = operations.memory_list("Nanami")["memories"][0]
    assert before_unpin["pinned"] is True
    assert before_unpin["clarity"] == "canon"
    assert before_unpin["retention"] == 1.0

    unpinned_resp = operations.memory_set_pinned_and_list(
        mem_id,
        pinned=False,
        character_name="Nanami",
    )
    after_unpin = unpinned_resp["memories"][0]
    assert after_unpin["pinned"] is False
    assert after_unpin["scope"] == SCOPE_CHAR_CROSS_SAVE
    assert after_unpin["kind"] == "profile"
    assert after_unpin["retention"] < 0.75
    assert after_unpin["clarity"] in {"faded", "dormant"}

    awakened_resp = operations.memory_awaken_and_list(
        mem_id,
        character_name="Nanami",
    )
    after_awaken = awakened_resp["memories"][0]
    assert after_awaken["recallCount"] == 1
    assert after_awaken["retention"] > 0.95
    assert after_awaken["clarity"] == "clear"

    repinned_resp = operations.memory_set_pinned_and_list(
        mem_id,
        pinned=True,
        character_name="Nanami",
    )
    assert repinned_resp["memories"][0]["pinned"] is True
    assert repinned_resp["memories"][0]["clarity"] == "canon"
    assert repinned_resp["memories"][0]["scope"] == SCOPE_CHAR_CANON


def test_session_isolated_memories_merge_into_list_pin_and_awaken(
    tmp_path, hybrid_engine
):
    sess_dir = tmp_path / "data" / "conversations" / "save_branch_1"
    store = open_session_store_for_dir(sess_dir)
    store.set_memory_mode("isolated")
    sid = store.session_id

    operations.memory_remember(
        "Mika最喜欢草莓大福。",
        character_name="Mika",
        gist_text="喜欢草莓大福",
    )
    iso_added = operations.memory_remember(
        "在这条世界线里，Mika与主角一起去了北海道看雪。",
        character_name="Mika",
        gist_text="一起去北海道看雪",
        memory_mode="isolated",
        source_session_id=sid,
    )
    iso_id = iso_added["id"]

    global_only = operations.memory_list("Mika")
    assert global_only["count"] == 1

    merged = operations.memory_list("Mika", session_id=sid)
    assert merged["count"] == 2
    ids = {m["id"] for m in merged["memories"]}
    assert iso_id in ids

    pinned_res = operations.memory_set_pinned(
        iso_id,
        pinned=True,
        session_id=sid,
    )
    assert pinned_res["ok"] is True
    assert pinned_res["pinned"] is True
    assert pinned_res["updated"] is True

    awaken_res = operations.memory_awaken(iso_id, session_id=sid)
    assert awaken_res["ok"] is True
    assert awaken_res["awakened"] == 1


def test_conversation_settings_and_live_set_memory_mode_command(tmp_path):
    project_root = tmp_path
    history_dir = project_root / "data" / "chat_history"
    conv_dir = history_dir / "sess_demo"
    conv_dir.mkdir(parents=True)
    active_file = conv_dir / "active.json"
    active_file.write_text("[]", encoding="utf-8")

    state = SimpleNamespace(
        project_root_dir=str(project_root),
        history_dir=str(history_dir),
        template_dir_path=str(project_root / "data" / "templates"),
        chat_session={},
        config_manager=SimpleNamespace(get_character_by_name=lambda _n: None),
    )
    remember_conversation(
        state,
        conv_dir,
        {
            "templateId": "tpl_1",
            "templateName": "测试会话",
            "characters": ["Mika"],
            "memoryMode": "shared",
            "autoOutfitSwitch": True,
        },
    )
    conv_id = _id(conv_dir)
    details0 = conversation_details(state, conv_id)
    assert details0["memoryMode"] == "shared"
    assert details0["autoOutfitSwitch"] is True

    updated = update_conversation_settings(
        state,
        conv_id,
        {"memoryMode": "inherit_readonly", "autoOutfitSwitch": False},
    )
    assert updated["memoryMode"] == "inherit_readonly"
    assert updated["autoOutfitSwitch"] is False

    store = open_session_store_for_dir(conv_dir)
    emitted: list[dict] = []
    cap = MemorySessionCapability()
    cap._history_arg = str(active_file)
    cap._hooks = SimpleNamespace(memory_mode="inherit_readonly")
    cap._transport = SimpleNamespace(emit=emitted.append)

    handlers = cap.command_handlers()
    handlers["set-memory-mode"]({"memoryMode": "isolated"})

    assert cap._hooks.memory_mode == "isolated"
    assert store.get_memory_mode() == "isolated"
    assert emitted == [{"type": "memory.mode", "memoryMode": "isolated"}]
    cap.on_shutdown()
    close_all_session_stores()


def test_inherited_global_memory_can_be_read_without_being_reinforced_or_edited(
    tmp_path, hybrid_engine,
):
    store = open_session_store_for_dir(tmp_path / "readonly")
    store.set_memory_mode("inherit_readonly")
    content = "Mika promised to return the silver compass on Friday"
    mid = operations.memory_remember(content, character_name="Mika")["id"]
    original = hybrid_engine.repo.get(mid)

    recall = operations.memory_recall_turn(TurnRecallInput(
        user_text=content,
        active_character_names=("Mika",),
        session_id=store.session_id,
        memory_mode="inherit_readonly",
    ))
    assert mid in recall["recalled_ids"]
    result = operations.memory_search(content, character_name="Mika", session_id=store.session_id)
    assert mid in [row["id"] for row in result["memories"]]
    assert "error" in operations.memory_set_pinned(mid, True, session_id=store.session_id)
    assert "error" in operations.memory_awaken(mid, session_id=store.session_id)
    updated = hybrid_engine.repo.get(mid)
    assert updated.recall_count == original.recall_count
    assert updated.last_recalled_at == original.last_recalled_at
    assert not updated.pinned


def test_chat_remember_does_not_create_pinned_canon(hybrid_engine, monkeypatch):
    monkeypatch.setattr(bridge_memory, "_check_mem0_before_call", lambda: None)
    result = memory_routes._memory_remember(SimpleNamespace(body={
        "characterName": "Mika",
        "content": "Mika saw a compass turn silver",
        "kind": "canon",
        "pinned": True,
    })).data
    item = hybrid_engine.repo.get(result["id"])
    assert item.scope == SCOPE_CHAR_CROSS_SAVE
    assert item.kind == "episodic"
    assert not item.pinned


def test_fresh_save_exposes_and_persists_memory_mode_before_first_turn(tmp_path):
    directory = tmp_path / "fresh"
    state = SimpleNamespace(chat_session={
        "historyPath": str(directory),
        "memoryMode": "isolated",
        "autoOutfitSwitch": False,
    })
    before_startup = _chat_session_preferences_patch(state)
    assert before_startup["memoryMode"] == "isolated"
    assert before_startup["autoOutfitSwitch"] is False

    cap = MemorySessionCapability()
    try:
        cap.on_llm_ready(StartupCapabilityContext(
            args=SimpleNamespace(history=str(directory), memory_mode="isolated"),
            config=None,
            llm_adapter=None,
            llm_manager=None,
            plugin_manager=None,
            hook_dispatcher=None,
            character_names=("Mika",),
        ))
        close_session_store_for_dir(directory)
        assert open_session_store_for_dir(directory).get_memory_mode() == "isolated"
        assert not open_session_store_for_dir(directory).list_turns()
    finally:
        cap.on_shutdown()
        close_session_store_for_dir(directory)


def test_live_mode_switch_excludes_older_dialogue_after_restart(tmp_path, monkeypatch):
    directory = tmp_path / "previous-mode"
    store = open_session_store_for_dir(directory)
    store.set_memory_mode("isolated")
    private_turn = store.append_raw_message({"role": "user", "content": "Old isolated fact"})
    extraction_windows = []

    def install_hooks(_dispatcher, **kwargs):
        hooks = MemoryAutoHooks(
            **kwargs,
            queue=MemoryWriteQueue(path=tmp_path / "pending.json"),
        )
        monkeypatch.setattr(
            hooks, "_extract_drafts",
            lambda messages, **_: extraction_windows.append(messages) or [],
        )
        return hooks

    startup = StartupCapabilityContext(
        args=SimpleNamespace(history=str(directory)),
        config=None,
        llm_adapter=None,
        llm_manager=None,
        plugin_manager=None,
        hook_dispatcher=PluginHookDispatcher(),
        character_names=("Mika",),
        runtime_imports=SimpleNamespace(install_memory_hooks=install_hooks),
    )
    cap = MemorySessionCapability()
    reopened_cap = MemorySessionCapability()
    try:
        cap.on_llm_ready(startup)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(cap.command_handlers()["set-memory-mode"], "shared").result()
        assert operations.current_memory_tool_context().memory_mode == "shared"
        assert store.get_memory_mode_start_seq() == private_turn.seq
        cap.on_shutdown()
        close_session_store_for_dir(directory)

        reopened = open_session_store_for_dir(directory)
        shared_turn = reopened.append_raw_message({"role": "user", "content": "New shared fact"})
        reopened_cap.on_llm_ready(startup)
        older = [
            {**turn.raw_message, "_turn_seq": turn.seq}
            for turn in (private_turn, shared_turn)
        ]
        reopened_cap._hooks.before_compact(BeforeCompactContext(
            messages=older, older_messages=older, recent_messages=[],
            up_to_seq=shared_turn.seq,
        ))
        assert [[m["turn_seq"] for m in window] for window in extraction_windows] == [[shared_turn.seq]]
    finally:
        if reopened_cap._tool_ctx_token is not None:
            reopened_cap.on_shutdown()
        if cap._tool_ctx_token is not None:
            cap.on_shutdown()
        close_session_store_for_dir(directory)
