from __future__ import annotations

import json

import pytest

from ai.memory.imports import execute_memory_import, preview_memory_import
from test.mocks import MockLLMAdapter


def test_preview_mixed_txt_and_json_uses_plain_dialogue_and_estimates_requests(tmp_path):
    text_path = tmp_path / "notes.txt"
    text_path.write_text("你: 喜欢雨天\nMika: 我会记住。", encoding="utf-8-sig")
    json_path = tmp_path / "history.json"
    json_path.write_text(
        json.dumps(
            [
                {"role": "system", "content": "secret prompt"},
                {"role": "user", "content": "Please remember tea"},
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {"dialog": [{"character_name": "Mika", "speech": "Tea noted."}]},
                        ensure_ascii=False,
                    ),
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    preview = preview_memory_import([text_path, json_path], character_name="Mika")

    assert preview["fileCount"] == 2
    assert preview["dialogueLineCount"] == 4
    assert preview["chunkCount"] == 2
    assert preview["sourceTokens"] > 0
    assert preview["estimatedInputTokens"] > preview["sourceTokens"]
    assert preview["estimatedTotalTokens"] == (
        preview["estimatedInputTokens"] + preview["estimatedOutputTokens"]
    )
    assert preview["warnings"] == []


def test_execute_import_extracts_all_chunks_then_deduplicates_and_saves_to_selected_character(tmp_path):
    first = tmp_path / "first.txt"
    first.write_text("user: likes tea", encoding="utf-8")
    second = tmp_path / "second.json"
    second.write_text(
        json.dumps([{"role": "user", "content": "Tea is still my favorite"}]),
        encoding="utf-8",
    )
    adapter = MockLLMAdapter(
        responses=[
            '[{"character_name":"Other","memory":"User likes tea","confidence":0.9}]',
            '[{"character_name":"Other","memory":"User likes tea","confidence":0.8}]',
        ]
    )
    saved = []
    progress = []

    result = execute_memory_import(
        [first, second],
        character_name="Mika",
        llm_adapter=adapter,
        remember_func=lambda memory, character_name=None: saved.append((character_name, memory)) or {"ok": True},
        progress_callback=lambda phase, value, message, log: progress.append((phase, value, message, log)),
    )

    assert len(adapter.call_history) == 2
    assert saved == [("Mika", "User likes tea")]
    assert result["savedCount"] == 1
    assert result["duplicateCount"] == 1
    assert result["memories"] == ["User likes tea"]
    assert {row[0] for row in progress} >= {"parse", "extract", "write"}


def test_preview_rejects_invalid_json_and_unsupported_files(tmp_path):
    invalid = tmp_path / "broken.json"
    invalid.write_text("{bad", encoding="utf-8")
    unsupported = tmp_path / "history.md"
    unsupported.write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON 历史消息格式无效"):
        preview_memory_import([invalid], character_name="Mika")
    with pytest.raises(ValueError, match="不支持的文件类型"):
        preview_memory_import([unsupported], character_name="Mika")


def test_preview_accepts_active_branch_export(tmp_path):
    path = tmp_path / "branches.json"
    path.write_text(
        json.dumps(
            {
                "activeBranchId": "branch-2",
                "branches": {
                    "main": {"history": ["你: main"]},
                    "branch-2": {"history": ["你: branch", "Mika: selected"]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    preview = preview_memory_import([path], character_name="Mika")

    assert preview["dialogueLineCount"] == 2
    assert preview["files"][0]["dialogueCharacters"] == len("你: branch\nMika: selected")
