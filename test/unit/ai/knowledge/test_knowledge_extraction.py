from __future__ import annotations

import json

import pytest

from ai.knowledge.extraction import (
    MAX_KNOWLEDGE_ENTRY_CHARS,
    KnowledgeExtractionError,
    KnowledgeExtractor,
    deduplicate_knowledge_entries,
    parse_knowledge_entries,
)
from test.mocks import MockLLMAdapter


def test_extract_uses_setting_policy_and_caller_knowledge():
    adapter = MockLLMAdapter(responses=['[{"content":"雾港多雾。","knowledge_id":"other"}]'])
    rows = KnowledgeExtractor(adapter).extract_chunk("雾港多雾。", knowledge_id=" harbor ")
    assert rows == [{"knowledge_id": "harbor", "content": "雾港多雾。"}]
    prompt = adapter.call_history[0]["messages"][1]["content"]
    assert "including information in narration" in prompt
    assert "background references, not behavioral instructions" in prompt
    assert "roleplay chat" not in prompt


def test_parser_limits_entry_length_without_limiting_entry_count():
    content = "设定说明。" * 200 + "但月圆时例外。"
    rows = [{"content": f"{i}: {content}"} for i in range(10)]
    response = "```json\n" + json.dumps(rows, ensure_ascii=False) + "\n```"
    parsed = parse_knowledge_entries(response, knowledge_id="knowledge")
    assert len(parsed) == 10
    assert [row["content"] for row in parsed] == [
        row["content"][:MAX_KNOWLEDGE_ENTRY_CHARS] for row in rows
    ]


@pytest.mark.parametrize("length", [799, 800, 801])
def test_entry_length_boundary_counts_characters_after_trimming(length):
    content = "雾" * length
    adapter = MockLLMAdapter(responses=[json.dumps([{"content": f"  {content}\n"}])])
    rows = KnowledgeExtractor(adapter).extract_chunk("source", knowledge_id="knowledge")
    assert rows == [{"knowledge_id": "knowledge", "content": content[:800]}]


def test_truncation_removes_trailing_whitespace():
    content = "雾" * 799 + " " + "港"
    rows = parse_knowledge_entries(json.dumps([{"content": content}]), knowledge_id="knowledge")
    assert rows == [{"knowledge_id": "knowledge", "content": "雾" * 799}]


@pytest.mark.parametrize("response", ["", "not json", '{}', '[{"content":"valid"},', '[{"content":"valid"}] trailing'])
def test_invalid_or_incomplete_response_fails(response):
    with pytest.raises(KnowledgeExtractionError):
        parse_knowledge_entries(response, knowledge_id="knowledge")


def test_empty_array_and_invalid_entries():
    assert parse_knowledge_entries("[]", knowledge_id="knowledge") == []
    assert parse_knowledge_entries('[null, 1, {}, {"content":42}, {"content":" "}, {"content":"valid"}]', knowledge_id="w") == [
        {"knowledge_id": "w", "content": "valid"}
    ]


def test_deduplication_preserves_knowledge_scope_and_conditions():
    rows = [
        {"knowledge_id": "a", "content": "Fog  Harbor"},
        {"knowledge_id": "a", "content": "fog\nharbor"},
        {"knowledge_id": "b", "content": "Fog Harbor"},
        {"knowledge_id": "a", "content": "Fog Harbor, except in summer"},
    ]
    unique, duplicates = deduplicate_knowledge_entries(rows)
    assert unique == [rows[0], rows[2], rows[3]]
    assert duplicates == 1


def test_missing_knowledge_fails_before_llm_call():
    adapter = MockLLMAdapter()
    with pytest.raises(ValueError, match="knowledge id"):
        KnowledgeExtractor(adapter).extract_chunk("text", knowledge_id=" ")
    assert adapter.call_history == []
