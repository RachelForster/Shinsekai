from __future__ import annotations

import pytest

from ai.memory import deduplication


def test_find_duplicate_memory_accepts_semantic_match():
    match = deduplication.find_duplicate_memory(
        "用户爱喝红茶",
        {"results": [{"id": "mem-1", "memory": "用户喜欢喝红茶", "score": 0.96}]},
    )

    assert match is not None
    assert match.memory_id == "mem-1"
    assert match.match_type == "semantic"
    assert match.similarity == pytest.approx(0.96)


def test_find_duplicate_memory_rejects_match_below_threshold():
    match = deduplication.find_duplicate_memory(
        "用户爱喝红茶",
        {"results": [{"id": "mem-1", "memory": "用户喜欢喝红茶", "score": 0.91}]},
    )

    assert match is None


def test_find_duplicate_memory_detects_normalized_exact_text_without_score():
    match = deduplication.find_duplicate_memory(
        "  用户喜欢喝红茶  ",
        [{"id": "mem-1", "memory": "用户喜欢喝红茶"}],
    )

    assert match is not None
    assert match.match_type == "exact"
    assert match.similarity is None


def test_semantic_threshold_can_be_configured(monkeypatch):
    monkeypatch.setenv("SHINSEKAI_MEMORY_DEDUP_THRESHOLD", "0.88")

    assert deduplication.semantic_deduplication_threshold() == pytest.approx(0.88)


def test_invalid_semantic_threshold_uses_safe_default(monkeypatch):
    monkeypatch.setenv("SHINSEKAI_MEMORY_DEDUP_THRESHOLD", "2")

    assert deduplication.semantic_deduplication_threshold() == pytest.approx(
        deduplication.DEFAULT_SEMANTIC_DEDUPLICATION_THRESHOLD
    )
