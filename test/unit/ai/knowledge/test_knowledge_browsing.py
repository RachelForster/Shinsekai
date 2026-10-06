from types import SimpleNamespace

import pytest

from ai.knowledge import operations as browsing
from ai.knowledge import storage


@pytest.fixture
def knowledge_store(monkeypatch):
    store = SimpleNamespace()
    monkeypatch.setattr(browsing, 'get_mem0', lambda: store)
    return store


@pytest.mark.parametrize("parameter", ["limit", "top_k"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_entry_list_uses_mem0_with_knowledge_filter(monkeypatch, parameter, wrapped):
    calls = []
    def result(filters, count):
        calls.append((filters, count))
        rows = [{"id": "1", "memory": "setting"}, {"id": "2", "content": "other"}, "plain"]
        if filters["user_id"] == "empty":
            rows = []
        return {"results": rows} if wrapped else rows
    def legacy(*, filters, limit):
        return result(filters, limit)
    def current(*, filters, top_k, **kwargs):
        return result(filters, top_k)
    store = SimpleNamespace(get_all=current if parameter == "top_k" else legacy)
    monkeypatch.setattr(browsing, "get_mem0", lambda: store)
    monkeypatch.setattr(storage, "scroll_knowledge_records", lambda *a, **kw: pytest.fail("entry list bypassed Mem0"))
    listed = browsing.list_local_knowledge_entries("alpha")
    assert listed == {"knowledge_id": "alpha", "count": 3, "memories": [
        {"id": "1", "memory": "setting"}, {"id": "2", "memory": "other"}, {"id": "", "memory": "plain"},
    ]}
    browsing.list_local_knowledge_entries("alpha", limit=999)
    browsing.list_local_knowledge_entries("orphan", limit=5)
    assert calls == [({"user_id": "alpha"}, 200), ({"user_id": "alpha"}, 200), ({"user_id": "orphan"}, 5)]
    assert browsing.list_local_knowledge_entries("empty") == {"knowledge_id": "empty", "count": 0, "memories": []}
    assert browsing.list_local_knowledge_entries("")["error"] == "knowledge id is required"


def test_entry_search_uses_explicit_knowledge_and_bounds_limit(knowledge_store):
    calls = []
    def search(query, *, filters, top_k):
        calls.append((query, filters, top_k))
        return {"results": [{"id": "1", "memory": "setting"}]}
    knowledge_store.search = search
    result = browsing.search_local_knowledge_entries("alpha", "test", limit=999)
    assert calls == [("test", {"user_id": "alpha"}, 200)]
    assert result["memories"] == [{"id": "1", "memory": "setting"}]


def test_local_entry_search_does_not_call_knowledge_service(knowledge_store, monkeypatch):
    def search(query, *, filters, top_k):
        return {"results": [{"id": "1", "memory": "setting"}]}

    def forbidden_request(*args, **kwargs):
        pytest.fail("local entry search called the knowledge service")

    knowledge_store.search = search
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", "http://127.0.0.1:8787/api/knowledge")
    monkeypatch.delenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", raising=False)
    monkeypatch.setattr(browsing, "request_knowledge_service", forbidden_request)

    result = browsing.search_local_knowledge_entries("alpha", "test")

    assert result == {
        "knowledge_id": "alpha",
        "query": "test",
        "count": 1,
        "memories": [{"id": "1", "memory": "setting"}],
    }
