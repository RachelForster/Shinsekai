from types import SimpleNamespace

import pytest

from ai.knowledge import operations as browsing


@pytest.fixture
def knowledge_store(monkeypatch):
    store = SimpleNamespace()
    return store


def test_entry_search_uses_explicit_knowledge_and_bounds_limit(knowledge_store):
    calls = []
    def search(query, *, filters, top_k):
        calls.append((query, filters, top_k))
        return {"results": [{"id": "1", "memory": "setting"}]}
    knowledge_store.search = search
    result = browsing.search_local_knowledge_entries(knowledge_store, "alpha", "test", limit=999)
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
    monkeypatch.setattr("urllib.request.urlopen", forbidden_request)

    result = browsing.search_local_knowledge_entries(knowledge_store, "alpha", "test")

    assert result == {
        "knowledge_id": "alpha",
        "query": "test",
        "count": 1,
        "memories": [{"id": "1", "memory": "setting"}],
    }
