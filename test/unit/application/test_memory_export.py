from __future__ import annotations

from datetime import datetime

from application.memory import manage_memories


def test_format_memories_text_renders_numbered_entries_with_labels():
    text = manage_memories.format_memories_text(
        "Mio",
        [
            {"id": "c1", "memory": "Student council member.", "pinned": True},
            {"id": "d1", "memory": "Long story\nsecond line", "gist": "Went to the festival", "createdAt": 1_700_000_000},
            {"id": "", "memory": "No id memory"},
        ],
        labels={"header": "角色记忆", "canon": "固有", "detail": "细节", "total": "条目数"},
        now=datetime(2026, 1, 1, 12, 0, 0),
    )

    lines = text.split("\n")
    assert lines[0] == "# 角色记忆: Mio"
    assert lines[1] == "# Exported at: 2026-01-01 12:00:00"
    assert lines[2] == "# 条目数: 3"
    assert "1. [固有] Student council member." in text
    assert "   ID: c1" in text
    assert "2. Went to the festival" in text
    assert "   细节: Long story\n   second line" in text
    assert "   Created at: " in text
    assert "3. No id memory" in text
    assert "ID: \n" not in text


def test_export_memories_text_collects_all_and_filters_selection(monkeypatch):
    import ai.memory.operations as operations

    rows = [{"id": f"m{i}", "memory": f"memory {i}"} for i in range(3)]
    monkeypatch.setattr(
        operations,
        "memory_list_all",
        lambda name, **_kwargs: {"agentId": name, "count": len(rows), "memories": rows},
    )

    everything = manage_memories.export_memories_text("Mio")
    selected = manage_memories.export_memories_text("Mio", memory_ids=["m2", "missing"])

    assert everything["count"] == 3
    assert "3. memory 2" in everything["text"]
    assert selected["count"] == 1
    assert "1. memory 2" in selected["text"]
    assert "memory 0" not in selected["text"]


def test_export_memories_text_propagates_errors(monkeypatch):
    import ai.memory.operations as operations

    monkeypatch.setattr(operations, "memory_list_all", lambda *_a, **_k: {"error": "boom"})

    assert manage_memories.export_memories_text("Mio") == {"error": "boom"}
