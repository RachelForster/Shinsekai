"""Unit tests for selective media repair, speculative dialog, and compact instructions."""

from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock

from ai.llm.compact_manager import CompactManager
from ai.llm.dialog_repair import repair_dialog_output
from ai.llm.llm_manager import LLMManager
from ai.llm.speculative_dialog import run_speculative_dialog_generation
from core.chat_history.models import CHUNK_FEED_SOURCE
from core.messaging.dialog_output import (
    has_valid_dialog_output,
    parse_and_validate_dialog_output,
)
from sdk.hooks import BeforeCompactContext, PluginHookDispatcher
from test.mocks import MockLLMAdapter


def test_selective_speaker_media_validation_allows_unbound_npcs_and_requires_scene_bgm() -> None:
    bound = frozenset({"Alice"})
    requires = lambda name: name in bound

    # Bound character with media, unbound NPC without media -> valid!
    payload = (
        '{"dialog":['
        '{"character_name":"Alice","sprite":"0","speech":"Hello"},'
        '{"character_name":"Shopkeeper","speech":"Fresh bread here!"},'
        '{"character_name":"NARR","speech":"Dust settled."}'
        ']}'
    )
    assert has_valid_dialog_output(payload) is False
    ok, items = parse_and_validate_dialog_output(payload, speaker_requires_media=requires)
    assert ok is True
    assert len(items) == 3

    # Bound character missing media -> invalid even in selective mode!
    missing_bound = '{"dialog":[{"character_name":"Alice","speech":"Hello"}]}'
    assert has_valid_dialog_output(missing_bound, speaker_requires_media=requires) is False

    # SCENE / bgm must always provide media!
    missing_scene = '{"dialog":[{"character_name":"SCENE","speech":"Rainy street"}]}'
    assert has_valid_dialog_output(missing_scene, speaker_requires_media=requires) is False
    missing_bgm = '{"dialog":[{"character_name":"bgm","speech":""}]}'
    assert has_valid_dialog_output(missing_bgm, speaker_requires_media=requires) is False


def test_selective_repair_uses_safe_text_section_for_braces_in_speaker_names() -> None:
    fixed = '{"dialog":[{"character_name":"NPC","speech":"Hello"},{"character_name":"A{bad}B","sprite":"0","speech":"Yo"}]}'
    adapter = MockLLMAdapter(responses=[fixed])
    repaired = repair_dialog_output(
        adapter,
        "broken prose",
        [{"role": "user", "content": "next"}],
        {},
        cancelled=lambda: False,
        event_logger=logging.getLogger("test"),
        speaker_requires_media=lambda name: name == "A{bad}B",
        bound_speakers=("A{bad}B",),
        locale="en",
    )
    assert repaired == fixed
    repair_prompt = adapter.call_history[0]["messages"][-1]["content"]
    assert "unbound minor/NPC speakers may omit" in repair_prompt
    assert "A{bad}B" in repair_prompt


def test_before_compact_add_instruction_dedup_and_injection_safety() -> None:
    ctx = BeforeCompactContext(messages=[], older_messages=[], recent_messages=[])
    ctx.add_instruction("  Preserve arc-{0} anchors.  ")
    ctx.add_instruction("Preserve arc-{0} anchors.")
    ctx.add_instruction("   ")
    assert ctx.extra_instructions == ["Preserve arc-{0} anchors."]

    dispatcher = PluginHookDispatcher()
    dispatcher.register_before_compact(
        lambda c: c.add_instruction("Keep unresolved plot {flags} intact.")
    )
    adapter = MockLLMAdapter(responses=["Compacted summary body"])
    manager = CompactManager(adapter, hook_dispatcher=dispatcher, recent_message_limit=1, locale="en")
    result = manager.compact_messages(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "turn 1"},
            {"role": "assistant", "content": "reply 1"},
            {"role": "user", "content": "turn 2"},
        ]
    )
    assert len(result) >= 2
    prompt_sent = adapter.call_history[0]["messages"][-1]["content"]
    assert "Keep unresolved plot {flags} intact." in prompt_sent


def test_speculative_dialog_is_pure_tool_free_non_streaming_and_cancellable() -> None:
    valid = '{"dialog":[{"character_name":"Narrator","speech":"Quiet"}]}'
    adapter = MockLLMAdapter(responses=[valid])
    caller_msgs = [{"role": "user", "content": "Chunk 1"}]
    snapshot_before = [dict(m) for m in caller_msgs]

    result = run_speculative_dialog_generation(
        adapter=adapter,
        messages=caller_msgs,
        system_prompt="Script driver",
        generation_kwargs={"temperature": 0.2, "tools": ["forbidden"], "stream": True},
        speaker_requires_media=lambda _n: False,
    )
    assert not result.cancelled
    assert result.error is None
    assert len(result.dialogs) == 1
    assert caller_msgs == snapshot_before
    assert adapter.call_history[0]["stream"] is False
    assert adapter.call_history[0]["kwargs"]["tools"] is None

    cancel = threading.Event()
    cancel.set()
    cancelled_adapter = MockLLMAdapter(responses=[valid])
    res_cancelled = run_speculative_dialog_generation(
        adapter=cancelled_adapter,
        messages=caller_msgs,
        cancel_event=cancel,
    )
    assert res_cancelled.cancelled is True
    assert cancelled_adapter.call_history == []


def test_llm_manager_suppresses_local_time_for_chunk_feed_and_wires_policy() -> None:
    adapter = MockLLMAdapter(
        responses=['{"dialog":[{"character_name":"Bystander","speech":"Look!"}]}']
    )
    manager = LLMManager(adapter=adapter, user_template="sys")
    manager.set_speaker_media_policy(lambda name: name == "Hero", bound_speakers=("Hero",))

    reply = manager.chat(
        "[chunk_00001]",
        stream=False,
        dialog_output_required=True,
        user_source=CHUNK_FEED_SOURCE,
    )
    assert "Bystander" in reply
    sent_user = adapter.call_history[0]["messages"][1]["content"]
    assert sent_user == "[chunk_00001]"
    assert "[本地时间" not in sent_user
