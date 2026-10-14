from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from types import SimpleNamespace
import json
import urllib.error
import urllib.request

import pytest

from ai.knowledge import service

from ai.knowledge import operations as ops


@pytest.fixture(autouse=True)
def local_knowledge(monkeypatch):
    monkeypatch.delenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", raising=False)
    monkeypatch.delenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", raising=False)


def test_character_knowledge_search_merges_and_ranks_bound_knowledge(monkeypatch):
    def search(query, *, filters, limit):
        knowledge_id = filters["user_id"]
        return [{"memory": knowledge_id, "score": 0.9 if knowledge_id == "b" else 0.3}]
    result = ops.search_knowledge(SimpleNamespace(search=search), "test", knowledge_ids=["b", "a", "a"], limit=1)
    assert result["knowledge_ids"] == ["a", "b"]
    assert result["memories"] == [{"memory": "b", "score": 0.9}]
    assert result["count"] == 1


@pytest.mark.parametrize("operation", [
    lambda store: ops.search_knowledge(store, "test", knowledge_ids=["a"]),
    lambda store: ops.add_knowledge_entry(store, "fact", "a"),
    lambda store: ops.list_knowledge_entries(store, "a"),
])
def test_local_failures_are_error_results(monkeypatch, operation):
    def fail(*args, **kwargs):
        raise RuntimeError("store unavailable")
    store = SimpleNamespace(search=fail, add=fail, get_all=fail)
    assert operation(store)["error"] == "store unavailable"


@pytest.mark.parametrize("error", [
    urllib.error.HTTPError("http://test", 503, "unavailable", {}, BytesIO(b"unavailable")),
    urllib.error.URLError("offline"),
])
def test_http_failures_are_error_results(monkeypatch, error):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", "http://knowledge")
    def fail(*a, **k):
        raise error
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    assert "error" in service.knowledge_service_status()


def test_remote_status_and_owner_guard(monkeypatch):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", "http://knowledge")
    calls = []
    def request(req, **kwargs):
        calls.append((req.full_url, json.loads(req.data), kwargs))
        return BytesIO(b'{"status":"loading"}')
    monkeypatch.setattr(urllib.request, "urlopen", request)
    assert service.knowledge_service_status(start_loading=True, retry=True) == {"status": "loading"}
    assert calls[0][0] == "http://knowledge/status"
    assert calls[0][1] == {"startLoading": True, "retry": True}
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", "1")
    assert service.knowledge_service_status() is None
    assert len(calls) == 1
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", "0")
    assert service.knowledge_service_status()["status"] == "loading"


@pytest.mark.parametrize("payload", [b"not json", b"[]"])
def test_invalid_service_response(monkeypatch, payload):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", "http://knowledge")
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: BytesIO(payload))
    assert "error" in service.knowledge_service_status()


def test_concurrent_remember_deduplicates_under_lock(monkeypatch):
    rows = []
    def search(query, *, filters, limit):
        return list(rows)
    def add(text, **kwargs):
        rows.append({"id": "saved", "memory": text})
    store = SimpleNamespace(search=search, add=add)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: ops.add_knowledge_entry(store, "same fact", "a"), range(16)))
    assert len(rows) == 1
    assert sum(result["duplicate"] for result in results) == 15
