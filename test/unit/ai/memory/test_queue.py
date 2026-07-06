from __future__ import annotations

import json

from ai.memory.queue import MemoryWriteQueue


def test_memory_write_queue_persists_dedupes_and_flushes(tmp_path):
    saved = []

    def remember(content, character_name=None):
        saved.append((character_name, content))
        return {"ok": True}

    path = tmp_path / "queue.json"
    queue = MemoryWriteQueue(path=path, remember_func=remember)

    first = queue.enqueue("用户喜欢咖啡", character_name="Alice", source="test", confidence="bad")
    duplicate = queue.enqueue("用户喜欢咖啡", character_name="Alice")

    assert first["queued"] is True
    assert duplicate["duplicate"] is True
    assert len(queue) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["items"][0]["confidence"] == 1.0

    reloaded = MemoryWriteQueue(path=path, remember_func=remember)
    assert len(reloaded) == 1

    result = reloaded.flush()

    assert result["saved"] == 1
    assert result["pending"] == 0
    assert saved == [("Alice", "用户喜欢咖啡")]


def test_memory_write_queue_keeps_failed_items(tmp_path):
    def remember(_content, character_name=None):
        return {"status": "loading", "message": "loading"}

    queue = MemoryWriteQueue(path=tmp_path / "queue.json", remember_func=remember)
    queue.enqueue("待写入记忆", character_name="Alice")

    result = queue.flush()

    assert result["saved"] == 0
    assert result["pending"] == 1
    assert result["errors"]
