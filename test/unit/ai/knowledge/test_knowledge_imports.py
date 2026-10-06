from __future__ import annotations

import pytest

from ai.memory.token_estimator import estimate_message_tokens
from ai.knowledge.extraction import EXPECTED_OUTPUT_TOKENS_PER_CHUNK, KnowledgeExtractionError
from ai.knowledge.imports import execute_knowledge_import, preview_knowledge_import
from test.mocks import MockLLMAdapter


def test_import_extracts_knowledge_entries_and_preview_matches_requests(tmp_path, monkeypatch):
    source = tmp_path / "knowledge.txt"
    source.write_text("哈" * 600, encoding="utf-8")
    adapter = MockLLMAdapter(responses=['[{"content":"雾港多雾。","knowledge_id":"wrong"}]'])
    writes, bindings = [], []
    monkeypatch.setattr("ai.knowledge.imports.add_knowledge_entry", lambda content, knowledge_id: writes.append((content, knowledge_id)) or {"ok": True})
    monkeypatch.setattr("ai.knowledge.bindings.bind_character_knowledge", lambda name, knowledge_id: bindings.append((name, knowledge_id)))
    args = dict(knowledge_id="harbor", source_root=tmp_path, max_chunk_tokens=256)
    preview = preview_knowledge_import([source], **args)
    result = execute_knowledge_import([source], llm_adapter=adapter, **args)
    assert len(adapter.call_history) == result["chunkCount"] > 1
    assert writes == [("雾港多雾。", "harbor")]
    assert bindings == []
    assert "characterName" not in result
    assert result["duplicateCount"] == result["chunkCount"] - 1
    assert result["memories"] == ["雾港多雾。"]
    expected_input = sum(estimate_message_tokens(call["messages"]) for call in adapter.call_history)
    assert preview["estimatedInputTokens"] == expected_input
    assert preview["estimatedTotalTokens"] == result["estimatedTotalTokens"] == expected_input + len(adapter.call_history) * EXPECTED_OUTPUT_TOKENS_PER_CHUNK


@pytest.mark.parametrize("write_result", [{}, {"ok": False}, {"status": "failed"}, None])
def test_write_failure_does_not_bind_knowledge(tmp_path, monkeypatch, write_result):
    source = tmp_path / "knowledge.txt"
    source.write_text("雾港多雾。", encoding="utf-8")
    bindings = []
    monkeypatch.setattr("ai.knowledge.imports.add_knowledge_entry", lambda *args: write_result)
    monkeypatch.setattr("ai.knowledge.bindings.bind_character_knowledge", lambda *args: bindings.append(args))
    with pytest.raises(RuntimeError, match="写入资料知识失败"):
        execute_knowledge_import([source], knowledge_id="harbor", source_root=tmp_path,
                             max_chunk_tokens=256, llm_adapter=MockLLMAdapter(responses=['[{"content":"雾港多雾。"}]']))
    assert bindings == []


def test_bad_extraction_does_not_write_or_bind(tmp_path, monkeypatch):
    source = tmp_path / "knowledge.txt"
    source.write_text("雾港多雾。", encoding="utf-8")
    calls = []
    monkeypatch.setattr("ai.knowledge.imports.add_knowledge_entry", lambda *args: calls.append(args))
    monkeypatch.setattr("ai.knowledge.bindings.bind_character_knowledge", lambda *args: calls.append(args))
    with pytest.raises(KnowledgeExtractionError):
        execute_knowledge_import([source], knowledge_id="harbor", source_root=tmp_path,
                             max_chunk_tokens=256, llm_adapter=MockLLMAdapter(responses=['[{"content":']))
    assert calls == []
