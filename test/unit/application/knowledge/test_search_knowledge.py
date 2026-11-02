"""Service-local knowledge search, independent of remote connection settings."""
import importlib
import pytest
from ai.knowledge import operations

search_module = importlib.import_module("application.knowledge.search_knowledge")

def test_unbound_search_does_not_acquire_store(monkeypatch):
    monkeypatch.setattr(search_module, "list_knowledge_ids_for_characters", lambda names: [])
    monkeypatch.setattr(search_module, "get_mem0", lambda: pytest.fail("unbound search loaded store"))
    assert search_module.search_knowledge("fact", character_names=["A"]) == {
        "query": "fact", "knowledge_ids": [], "count": 0, "memories": [],
    }




def test_bound_search_uses_local_store_even_with_remote_url(monkeypatch):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", "http://other-service")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: pytest.fail("local service forwarded request"))
    monkeypatch.setattr(search_module, "list_knowledge_ids_for_characters", lambda names: ["world"])
    store = object()
    monkeypatch.setattr(search_module, "get_mem0", lambda: store)
    calls = []
    monkeypatch.setattr(operations, "search_knowledge", lambda actual, query, **kw: calls.append((actual, query, kw)) or {"count": 1})
    assert search_module.search_knowledge(" fact ", character_names=[" A "]) == {"count": 1}
    assert calls == [(store, "fact", {"knowledge_ids": ["world"], "limit": 5})]


def test_local_store_failure_is_an_error_result(monkeypatch):
    monkeypatch.setattr(search_module, "list_knowledge_ids_for_characters", lambda names: ["world"])
    def fail():
        raise RuntimeError("store unavailable")
    monkeypatch.setattr(search_module, "get_mem0", fail)
    assert search_module.search_knowledge("fact", character_names=["A"]) == {"error": "store unavailable"}
