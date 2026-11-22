"""Stage P2 tests for localized session compaction, extraction prompts, and context sentinels."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai.llm.compact_manager import CompactManager
from ai.llm.template.session import (
    KNOWLEDGE_CONTEXT_MARKER,
    LEGACY_KNOWLEDGE_CONTEXT_MARKERS,
    LEGACY_MEMORY_CONTEXT_MARKERS,
    LEGACY_OUTFIT_CONTEXT_MARKERS,
    LEGACY_RELATION_CONTEXT_MARKERS,
    MEMORY_CONTEXT_MARKER,
    OUTFIT_CONTEXT_MARKER,
    RELATION_CONTEXT_MARKER,
)
from ai.memory.backends.in_memory import DeterministicHashEmbedder
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo
from ai.memory.extraction import (
    build_extraction_messages,
    build_structured_extraction_messages,
)
from ai.memory.hooks import MemoryAutoHooks
from ai.memory.orchestrator import MemoryOrchestrator
from ai.memory.queue import MemoryWriteQueue
from application.chat.capabilities.outfit import (
    OutfitBeforeChatProvider,
    OutfitRuntimeController,
)
from application.chat.capabilities.relation import RelationTurnContextProvider
from application.knowledge.hooks import KnowledgeHooks
from application.story.scene import ConfigSceneModel
from config.feature_flags import FeatureFlag, FeatureFlagConfigManager
from config.schema import Character, Sprite
from core.chat_history.models import (
    build_compact_summary_message,
    extract_summary_body,
    is_compact_summary_message,
    is_omitted_history_summary,
)
from sdk.adapters.memory import MemoryDraft, SCOPE_CHAR_CROSS_SAVE, TurnRecallInput
from sdk.hooks import BeforeChatContext
from test.mocks import MockLLMAdapter


@pytest.mark.parametrize(
    (
        "locale",
        "sys_marker",
        "intro_marker",
        "user_role",
        "wrapper_marker",
        "omitted_marker",
    ),
    [
        (
            "zh_CN",
            "专业的对话总结助手",
            "用中文总结",
            "用户: 你好 {raw_brace}",
            "【历史对话总结】",
            "【历史摘要】",
        ),
        (
            "en",
            "professional conversation summarization assistant",
            "Write the summary in English",
            "User: 你好 {raw_brace}",
            "[Conversation Summary]",
            "[History Summary]",
        ),
        (
            "ja",
            "専門アシスタント",
            "日本語で客観的かつ正確に要約",
            "ユーザー: 你好 {raw_brace}",
            "【これまでの会話の要約】",
            "【履歴要約】",
        ),
    ],
)
def test_compact_manager_and_summary_framing_switch_across_locales(
    locale: str,
    sys_marker: str,
    intro_marker: str,
    user_role: str,
    wrapper_marker: str,
    omitted_marker: str,
) -> None:
    adapter = MockLLMAdapter(responses=["Condensed summary text."])
    cm = CompactManager(
        adapter,
        max_tokens=10_000,
        compact_threshold=0.5,
        recent_message_limit=1,
        locale=locale,
    )
    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "你好 {raw_brace}"},
        {"role": "assistant", "content": "回复"},
        {"role": "user", "content": "最新"},
    ]
    compacted = cm.compact_messages(messages)
    assert len(adapter.call_history) == 1
    req_msgs = adapter.call_history[0]["messages"]
    assert sys_marker in req_msgs[0]["content"]
    assert intro_marker in req_msgs[1]["content"]
    assert user_role in req_msgs[1]["content"]

    summary_msg = compacted[1]
    assert wrapper_marker in summary_msg["content"]
    assert is_compact_summary_message(summary_msg) is True
    assert extract_summary_body(summary_msg["content"]) == "Condensed summary text."
    # Re-wrapping an already-wrapped message must never double-wrap
    rewrapped = build_compact_summary_message(summary_msg["content"], locale=locale)
    assert rewrapped["content"] == summary_msg["content"]

    omitted = cm._omitted_history_message()
    assert omitted["content"].startswith(omitted_marker)
    assert is_compact_summary_message(omitted) is True
    assert is_omitted_history_summary(omitted["content"]) is True


@pytest.mark.parametrize(
    ("locale", "relative_date_example", "forbidden_leak", "heading"),
    [
        ("zh_CN", "'明天'", "'tomorrow'", "对话内容："),
        ("en", "'tomorrow'", "明天", "Dialogue:"),
        ("ja", "'明日'", "'tomorrow'", "対話内容："),
    ],
)
def test_memory_extraction_prompts_eliminate_chinese_leak_and_preserve_untrusted_braces(
    locale: str,
    relative_date_example: str,
    forbidden_leak: str,
    heading: str,
) -> None:
    untrusted_dialogue = "user: 记住暗号 {0.__class__} 与 {unknown_key}"
    structured = build_structured_extraction_messages(
        untrusted_dialogue,
        character_names=("Mika",),
        now_iso="2026-11-22T10:00:00+08:00",
        locale=locale,
    )
    simple = build_extraction_messages(
        untrusted_dialogue,
        "Mika",
        locale=locale,
    )
    assert relative_date_example in structured[1]["content"]
    assert forbidden_leak not in structured[1]["content"]
    assert heading in structured[1]["content"]
    assert untrusted_dialogue in structured[1]["content"]
    assert heading in simple[1]["content"]
    assert untrusted_dialogue in simple[1]["content"]


def test_memory_and_knowledge_hooks_deduplicate_both_new_and_legacy_sentinels(
    tmp_path: Path,
) -> None:
    search_calls: list[str] = []
    mem_hooks = MemoryAutoHooks(
        llm_adapter=MockLLMAdapter(),
        character_names=["Mika"],
        queue=MemoryWriteQueue(path=tmp_path / "q.json"),
        search_func=lambda q, **_kw: (
            search_calls.append(q) or {"memories": [{"id": "m1", "memory": "fact"}]}
        ),
        locale="ja",
    )
    for marker in (MEMORY_CONTEXT_MARKER, *LEGACY_MEMORY_CONTEXT_MARKERS):
        ctx = BeforeChatContext(
            messages=[
                {"role": "system", "content": f"{marker}\n- existing"},
                {"role": "user", "content": "質問です"},
            ],
            tools=None,
            generation_kwargs={},
            stream=False,
        )
        mem_hooks.before_chat(ctx)
        assert len(ctx.messages) == 2
    assert search_calls == []

    fresh_ctx = BeforeChatContext(
        messages=[{"role": "user", "content": "新しい質問"}],
        tools=None,
        generation_kwargs={},
        stream=False,
    )
    mem_hooks.before_chat(fresh_ctx)
    assert fresh_ctx.messages[-1]["content"].startswith(MEMORY_CONTEXT_MARKER)
    assert "このターンに関連する長期記憶" in fresh_ctx.messages[-1]["content"]

    know_search = Mock(return_value={"memories": [{"memory": "Lore entry"}]})
    know_hooks = KnowledgeHooks(
        character_names=["Mika"],
        search_func=know_search,
        locale="en",
    )
    know_hooks.enabled = True
    for marker in (KNOWLEDGE_CONTEXT_MARKER, *LEGACY_KNOWLEDGE_CONTEXT_MARKERS):
        k_ctx = BeforeChatContext(
            messages=[
                {"role": "system", "content": f"{marker}\n- old lore"},
                {"role": "user", "content": "harbor"},
            ],
            tools=None,
            generation_kwargs={},
            stream=False,
        )
        know_hooks.before_chat(k_ctx)
        assert len(k_ctx.messages) == 2
    know_search.assert_not_called()

    k_fresh = BeforeChatContext(
        messages=[{"role": "user", "content": "harbor"}],
        tools=None,
        generation_kwargs={},
        stream=False,
    )
    know_hooks.before_chat(k_fresh)
    injected_k = k_fresh.messages[-1]["content"]
    assert injected_k.startswith(KNOWLEDGE_CONTEXT_MARKER)
    assert "Relevant background setting references:" in injected_k
    assert injected_k.splitlines() == [
        "[Shinsekai:knowledge] Relevant background setting references:",
        "- Lore entry",
    ]


@pytest.mark.parametrize(
    ("locale", "tier_tag", "guidance_marker"),
    [
        ("zh_CN", "[清晰]", "本轮相关的长期记忆"),
        ("en", "[Clear]", "Relevant long-term memories for this turn"),
        ("ja", "[鮮明]", "このターンに関連する長期記憶"),
    ],
)
def test_memory_orchestrator_renders_localized_tiered_context(
    tmp_path: Path,
    locale: str,
    tier_tag: str,
    guidance_marker: str,
) -> None:
    repo = SqliteHybridMemoryRepo(tmp_path / f"mem_{locale}.db")
    try:
        orch = MemoryOrchestrator(
            embedder=DeterministicHashEmbedder(dimensions=384),
            global_repo=repo,
        )
        orch.ingest_drafts(
            [
                MemoryDraft(
                    owner_id="Mika",
                    scope=SCOPE_CHAR_CROSS_SAVE,
                    detail_text="Mika keeps a brass telescope",
                    gist_text="brass telescope",
                    importance=0.85,
                )
            ],
            now_ts=1_763_000_000.0,
        )
        block = orch.recall_for_turn(
            TurnRecallInput(
                user_text="Where is Mika's brass telescope?",
                active_character_names=("Mika", "Nanami"),
                now_ts=1_763_000_100.0,
            ),
            locale=locale,
        )
        assert block.rendered.startswith(MEMORY_CONTEXT_MARKER)
        assert guidance_marker in block.rendered
        assert tier_tag in block.rendered
    finally:
        repo.close()


def test_outfit_and_relation_providers_follow_ui_language_and_strip_legacy_markers(
    tmp_path: Path,
) -> None:
    s1 = tmp_path / "a.png"
    s2 = tmp_path / "b.png"
    s1.write_bytes(b"a")
    s2.write_bytes(b"b")
    kurisu = Character(
        name="Kurisu",
        color="#c84b31",
        sprite_prefix="k",
        character_setting="Scientist",
        sprites=[
            Sprite(path=s1, group="coat"),
            Sprite(path=s2, group="casual"),
        ],
        sprite_groups=["coat", "casual"],
        default_sprite_group="coat",
        emotion_tags="立绘 1：calm\n立绘 2：smile\n",
        relation_graph={
            "nodes": [{"key": "Kurisu"}, {"key": "Okabe"}],
            "edges": [{"source": "Kurisu", "target": "Okabe", "content": "Lab partner"}],
        },
    )
    okabe = Character(
        name="Okabe",
        color="#333333",
        sprite_prefix="o",
        character_setting="Inventor",
        sprites=[],
    )
    cfg = SimpleNamespace(
        config=SimpleNamespace(
            characters=[kurisu, okabe],
            system_config=SimpleNamespace(ui_language="en", voice_language="ja"),
        ),
        get_character_by_name=lambda n: {"Kurisu": kurisu, "Okabe": okabe}.get(n),
    )

    controller = OutfitRuntimeController()
    controller.initialize(cfg, character_names=["Kurisu", "Okabe"])
    outfit_provider = OutfitBeforeChatProvider(controller)

    # Legacy Chinese outfit marker from an older save is stripped cleanly before injecting new EN block!
    ctx = BeforeChatContext(
        messages=[
            {"role": "system", "content": f"{LEGACY_OUTFIT_CONTEXT_MARKERS[0]}\n旧服装说明"},
            {"role": "user", "content": "Change outfit"},
        ],
        tools=None,
        generation_kwargs={},
        stream=False,
    )
    outfit_provider.before_chat(ctx)
    assert len(ctx.messages) == 2
    assert ctx.messages[-1]["content"].startswith(OUTFIT_CONTEXT_MARKER)
    assert "[Active Character Outfit Group State]" in ctx.messages[-1]["content"]
    assert "Outfit switch item example: " in ctx.messages[-1]["content"]

    # Switch UI language live to Japanese -> outfit & relation prompts immediately switch to Japanese!
    cfg.config.system_config.ui_language = "ja"
    outfit_provider.before_chat(ctx)
    assert len(ctx.messages) == 2
    assert ctx.messages[-1]["content"].startswith(OUTFIT_CONTEXT_MARKER)
    assert "[現在のキャラクター衣装グループ状態]" in ctx.messages[-1]["content"]

    rel_provider = RelationTurnContextProvider(
        config=cfg,
        character_names=("Kurisu", "Okabe"),
    )
    # Legacy relation marker prevents duplicate injection
    legacy_rel_ctx = BeforeChatContext(
        messages=[
            {"role": "system", "content": f"{LEGACY_RELATION_CONTEXT_MARKERS[0]}\n[Kurisu]"},
            {"role": "user", "content": "こんにちは"},
        ],
        tools=None,
        generation_kwargs={},
        stream=False,
    )
    rel_provider.before_chat(legacy_rel_ctx)
    assert len(legacy_rel_ctx.messages) == 2

    fresh_rel_ctx = BeforeChatContext(
        messages=[{"role": "user", "content": "こんにちは"}],
        tools=None,
        generation_kwargs={},
        stream=False,
    )
    rel_provider.before_chat(fresh_rel_ctx)
    assert fresh_rel_ctx.messages[-1]["content"].startswith(RELATION_CONTEXT_MARKER)
    assert "キャラクター関係：" in fresh_rel_ctx.messages[-1]["content"]


def test_config_scene_model_follows_config_ui_language(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_systems: list[str] = []

    class _Adapter:
        def chat(self, messages, stream=False, **_kwargs):
            captured_systems.append(messages[0]["content"])
            return json.dumps({"dialogue": [{"characterId": "ling", "text": "ok"}]})

    flags = FeatureFlagConfigManager(
        environ={},
        overrides={FeatureFlag.STORY_SYSTEM: True},
    )
    cfg = SimpleNamespace(
        config=SimpleNamespace(system_config=SimpleNamespace(ui_language="zh_CN"))
    )
    model = ConfigSceneModel(flags, config_manager=cfg)
    monkeypatch.setattr(model, "_llm_manager", lambda: SimpleNamespace(llm_adapter=_Adapter()))

    for lang, expected_phrase in (
        ("zh_CN", "Shinsekai 的场景渲染器"),
        ("en", "Shinsekai's scene renderer"),
        ("ja", "Shinsekai のシーンレンダラー"),
    ):
        cfg.config.system_config.ui_language = lang
        model.complete({"tools": []})
        assert expected_phrase in captured_systems[-1]
