from __future__ import annotations

import pytest

from ai.memory.token_estimator import estimate_message_tokens
from ai.knowledge.extraction import EXPECTED_OUTPUT_TOKENS_PER_CHUNK, KnowledgeExtractionError
from application.knowledge.import_knowledge import execute_knowledge_import, prepare_knowledge_import, preview_knowledge_import
from test.mocks import MockLLMAdapter


def test_import_extracts_knowledge_entries_and_preview_matches_requests(tmp_path, monkeypatch):
    source = tmp_path / "knowledge.txt"
    source.write_text("哈" * 600, encoding="utf-8")
    adapter = MockLLMAdapter(responses=['[{"content":"雾港多雾。","knowledge_id":"wrong"}]'])
    writes = []
    monkeypatch.setattr("application.knowledge.import_knowledge.add_knowledge_entry", lambda content, knowledge_id: writes.append((content, knowledge_id)) or {"ok": True})
    args = dict(knowledge_id="harbor", source_root=tmp_path, max_chunk_tokens=256)
    preview = preview_knowledge_import([source], **args)
    result = execute_knowledge_import([source], llm_adapter=adapter, **args)
    assert len(adapter.call_history) == result["chunkCount"] > 1
    assert writes == [("雾港多雾。", "harbor")]
    assert "characterName" not in result
    assert result["duplicateCount"] == result["chunkCount"] - 1
    assert result["memories"] == ["雾港多雾。"]
    expected_input = sum(estimate_message_tokens(call["messages"]) for call in adapter.call_history)
    assert preview["estimatedInputTokens"] == expected_input
    assert preview["estimatedTotalTokens"] == result["estimatedTotalTokens"] == expected_input + len(adapter.call_history) * EXPECTED_OUTPUT_TOKENS_PER_CHUNK


@pytest.mark.parametrize("write_result", [{}, {"ok": False}, {"status": "failed"}, None])
def test_import_raises_on_write_failure(tmp_path, monkeypatch, write_result):
    source = tmp_path / "knowledge.txt"
    source.write_text("雾港多雾。", encoding="utf-8")
    monkeypatch.setattr("application.knowledge.import_knowledge.add_knowledge_entry", lambda *args: write_result)
    with pytest.raises(RuntimeError, match="写入资料知识失败"):
        execute_knowledge_import([source], knowledge_id="harbor", source_root=tmp_path,
                             max_chunk_tokens=256, llm_adapter=MockLLMAdapter(responses=['[{"content":"雾港多雾。"}]']))


def test_bad_extraction_does_not_write(tmp_path, monkeypatch):
    source = tmp_path / "knowledge.txt"
    source.write_text("雾港多雾。", encoding="utf-8")
    calls = []
    monkeypatch.setattr("application.knowledge.import_knowledge.add_knowledge_entry", lambda *args: calls.append(args))
    with pytest.raises(KnowledgeExtractionError):
        execute_knowledge_import([source], knowledge_id="harbor", source_root=tmp_path,
                             max_chunk_tokens=256, llm_adapter=MockLLMAdapter(responses=['[{"content":']))
    assert calls == []


def test_preview_knowledge_import_counts_nonempty_txt_lines(tmp_path):
    source = tmp_path / "knowledge.txt"
    source.write_text("第一行\n\n第二行\n", encoding="utf-8")

    preview = preview_knowledge_import(
        [source],
        knowledge_id="ddlc",
        source_root=tmp_path,
        max_chunk_tokens=256,
    )
    assert preview["fileCount"] == 1
    assert preview["dialogueLineCount"] == 2
    assert preview["chunkCount"] == 1


def test_preparation_uses_knowledge_target_and_preserves_preview_fields(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("雾港多雾。", encoding="utf-8")
    prepared = prepare_knowledge_import(
        [source], knowledge_id=" harbor ", source_root=tmp_path, max_chunk_tokens=256,
    )
    assert prepared.knowledge_id == "harbor"
    assert not hasattr(prepared, "character_name")
    preview = prepared.preview_payload()
    assert set(preview) == {
        "fileCount", "dialogueLineCount", "dialogueCharacters", "sourceTokens",
        "chunkCount", "estimatedInputTokens", "estimatedOutputTokens",
        "estimatedTotalTokens", "files", "warnings",
    }
    assert preview["files"] == [{
        "name": "notes.txt", "kind": "txt", "dialogueLineCount": 1,
        "dialogueCharacters": 5, "sourceTokens": preview["sourceTokens"], "chunkCount": 1,
    }]
