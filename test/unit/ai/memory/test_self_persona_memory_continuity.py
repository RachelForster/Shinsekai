"""Unit tests for memory continuity under immutable ``__self__`` across renames."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ai.memory import operations
from ai.memory.extraction import parse_memory_drafts
from ai.memory.hooks import MemoryAutoHooks
from ai.memory.queue import MemoryWriteQueue
from application.memory.manage_memories import resolve_memory_owner_name
from config.schema import Character, SELF_PERSONA_ID, SELF_PERSONA_NAME, SELF_PERSONA_SPRITE_PREFIX
from ai.memory.orchestrator import is_roleplay_player_persona
from sdk.hooks import BeforeChatContext
from sdk.adapters.memory import SCOPE_CHAR_CROSS_SAVE, SCOPE_SELF_PUBLIC


class _NoopLlm:
    def complete(self, *_args, **_kwargs):
        return "{}"


def test_resolve_memory_owner_name_maps_renamed_and_legacy_self_to_self_id() -> None:
    self_char = Character(
        id=SELF_PERSONA_ID,
        name="浅羽",
        color="#89b4fa",
        sprite_prefix=SELF_PERSONA_SPRITE_PREFIX,
        is_builtin=True,
        pinned=True,
        undeletable=True,
    )
    mika = Character(name="Mika", color="#ffffff", sprite_prefix="mika")
    cfg = SimpleNamespace(
        get_character_by_name=lambda n: self_char if n in {"浅羽", SELF_PERSONA_NAME} else (mika if n == "Mika" else None)
    )

    assert resolve_memory_owner_name(SELF_PERSONA_NAME, config_manager=cfg) == SELF_PERSONA_ID
    assert resolve_memory_owner_name(SELF_PERSONA_ID, config_manager=cfg) == SELF_PERSONA_ID
    assert resolve_memory_owner_name("浅羽", config_manager=cfg) == SELF_PERSONA_ID
    assert resolve_memory_owner_name("Mika", config_manager=cfg) == "Mika"
    assert resolve_memory_owner_name("", config_manager=cfg) == ""


def test_memory_tool_context_routes_renamed_self_without_roleplay_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_calls: list[tuple[str, str]] = []

    class _FakeMem0:
        def search(self, _query, *, filters, limit=10):
            seen_calls.append(("search", filters["user_id"]))
            return {"results": []}

        def add(self, _content, *, user_id, infer=False):
            seen_calls.append(("add", user_id))
            return {"results": []}

    monkeypatch.setattr(operations, "ensure_mem0", lambda: _FakeMem0())
    token = operations.bind_memory_tool_context(
        session_id="sess-1",
        memory_mode="shared",
        player_character="浅羽",
        self_persona_name="浅羽",
    )
    try:
        ctx = operations.current_memory_tool_context()
        assert ctx.self_persona_name == "浅羽"
        assert ctx.player_character == "浅羽"
        assert operations._is_self_agent_name("浅羽", self_persona_name=ctx.self_persona_name) is True
        assert operations._resolve_agent_id("浅羽", self_persona_name=ctx.self_persona_name) == SELF_PERSONA_ID

        add_res = operations.memory_remember("浅羽喜欢凌晨喝黑咖啡", character_name="浅羽")
        search_res = operations.memory_search("黑咖啡", character_name="浅羽")
        assert add_res["agent_id"] == SELF_PERSONA_ID
        assert search_res["agent_id"] == SELF_PERSONA_ID
        assert seen_calls == [
            ("search", SELF_PERSONA_ID),
            ("add", SELF_PERSONA_ID),
            ("search", SELF_PERSONA_ID),
        ]
    finally:
        operations.reset_memory_tool_context(token)


def test_parse_memory_drafts_attributes_renamed_self_persona_to_self_scope() -> None:
    payload = json.dumps(
        {
            "memories": [
                {
                    "character_name": "浅羽",
                    "gist": "黑咖啡偏好",
                    "detail": "浅羽习惯在观星时喝不加糖的黑咖啡",
                    "kind": "preference",
                    "importance": 0.8,
                },
                {
                    "character_name": "Mika",
                    "gist": "望远镜",
                    "detail": "Mika珍藏着旧折射望远镜",
                    "kind": "fact",
                    "importance": 0.7,
                },
            ]
        },
        ensure_ascii=False,
    )
    drafts = parse_memory_drafts(
        payload,
        character_names=["Mika"],
        self_persona_name="浅羽",
    )
    assert len(drafts) == 2
    by_owner = {draft.owner_id: draft for draft in drafts}
    assert SELF_PERSONA_ID in by_owner
    assert by_owner[SELF_PERSONA_ID].scope == SCOPE_SELF_PUBLIC
    assert by_owner["Mika"].scope == SCOPE_CHAR_CROSS_SAVE


def test_memory_hooks_treat_renamed_self_player_as_self_and_isolate_npc_roleplay() -> None:
    captured_turns: list[object] = []

    def _fake_recall(turn_input, **_kwargs):
        captured_turns.append(turn_input)
        return {"memories": [], "contextText": ""}

    self_hooks = MemoryAutoHooks(
        llm_adapter=_NoopLlm(),
        character_names=["浅羽", "Mika"],
        session_id="sess-self",
        memory_mode="shared",
        player_character="浅羽",
        self_persona_name="浅羽",
        queue=MemoryWriteQueue(),
        recall_func=_fake_recall,
    )
    assert self_hooks.player_character == SELF_PERSONA_ID
    assert is_roleplay_player_persona(self_hooks.player_character) is False
    assert self_hooks._normalize_memory_owner_name("浅羽") == SELF_PERSONA_ID

    messages = [{"role": "user", "content": "今晚天台风很大", "_turn_seq": 1}]
    self_hooks.before_chat(
        BeforeChatContext(messages=messages, tools=[], generation_kwargs={}, stream=False)
    )
    assert len(captured_turns) == 1
    assert captured_turns[0].active_character_names == (SELF_PERSONA_ID, "Mika")

    npc_hooks = MemoryAutoHooks(
        llm_adapter=_NoopLlm(),
        character_names=["浅羽", "Mika"],
        session_id="sess-npc",
        memory_mode="shared",
        player_character="Mika",
        self_persona_name="浅羽",
        queue=MemoryWriteQueue(),
        recall_func=_fake_recall,
    )
    assert npc_hooks.player_character == "Mika"
    assert is_roleplay_player_persona(npc_hooks.player_character) is True
