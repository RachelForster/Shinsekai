from __future__ import annotations

from ai.memory import operations


class _FakeMemory:
    def get_all(self, *, filters, limit):
        assert filters == {"user_id": "Alice"}
        assert limit == 200
        return {
            "results": [
                {"id": "1", "memory": "likes tea"},
                {"id": "2", "content": "likes books"},
                "loose row",
            ]
        }


def test_memory_list_normalizes_rows(monkeypatch):
    monkeypatch.setattr(operations, "get_mem0", lambda: _FakeMemory())

    result = operations.memory_list("Alice")

    assert result == {
        "agentId": "Alice",
        "count": 3,
        "memories": [
            {"id": "1", "memory": "likes tea"},
            {"id": "2", "memory": "likes books"},
            {"id": "", "memory": "loose row"},
        ],
    }


def test_memory_remember_and_list_rejects_empty_content():
    assert operations.memory_remember_and_list("  ", character_name="Alice") == {
        "error": "memory content is required"
    }


def test_memory_forget_and_list_rejects_empty_id():
    assert operations.memory_forget_and_list("  ", character_name="Alice") == {
        "error": "memory id is required"
    }
