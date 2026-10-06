from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from types import SimpleNamespace
import json
import urllib.error

import pytest

from ai.knowledge import catalog, service

from ai.knowledge import operations as ops


@pytest.fixture(autouse=True)
def local_knowledge(monkeypatch):
    monkeypatch.delenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", raising=False)
    monkeypatch.delenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", raising=False)


def test_explicit_knowledge_search_never_calls_remote(monkeypatch):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", "http://unused")
    monkeypatch.setattr(service.urllib.request, "urlopen", lambda *a, **k: pytest.fail("remote called"))
    def search(query, *, filters, limit):
        knowledge_id = filters["user_id"]
        return [{"memory": knowledge_id, "score": 0.9 if knowledge_id == "b" else 0.3}]
    monkeypatch.setattr(ops, "get_mem0", lambda: SimpleNamespace(search=search))
    result = ops.search_knowledge("test", knowledge_ids=["a", "b"], limit=1)
    assert result["knowledge_ids"] == ["a", "b"]
    assert result["memories"][0]["memory"] == "b"


@pytest.mark.parametrize("operation", [
    lambda: ops.search_knowledge("test", knowledge_ids=["a"]),
    lambda: ops.add_knowledge_entry("fact", "a"),
    lambda: ops.delete_knowledge_entry("id"),
    lambda: ops.list_knowledge_entries("a"),
])
def test_local_failures_are_error_results(monkeypatch, operation):
    def fail():
        raise RuntimeError("store unavailable")
    monkeypatch.setattr(ops, "get_mem0", fail)
    assert operation()["error"] == "store unavailable"


@pytest.mark.parametrize("error", [
    urllib.error.HTTPError("http://test", 503, "unavailable", {}, BytesIO(b"unavailable")),
    urllib.error.URLError("offline"),
])
def test_http_failures_are_error_results(monkeypatch, error):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", "http://knowledge")
    def fail(*a, **k):
        raise error
    monkeypatch.setattr(service.urllib.request, "urlopen", fail)
    assert "error" in ops.knowledge_service_status()


def test_remote_status_and_owner_guard(monkeypatch):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", "http://knowledge")
    calls = []
    def request(req, **kwargs):
        calls.append((req.full_url, json.loads(req.data), kwargs))
        return BytesIO(b'{"status":"loading"}')
    monkeypatch.setattr(service.urllib.request, "urlopen", request)
    monkeypatch.setattr(ops, "get_mem0", lambda: pytest.fail("status loaded local store"))
    assert ops.knowledge_service_status(start_loading=True, retry=True) == {"status": "loading"}
    assert calls[0][0] == "http://knowledge/status"
    assert calls[0][1] == {"startLoading": True, "retry": True}
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", "1")
    assert ops.knowledge_service_status() is None
    assert len(calls) == 1
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", "0")
    assert ops.knowledge_service_status()["status"] == "loading"


@pytest.mark.parametrize("payload", [b"not json", b"[]"])
def test_invalid_service_response(monkeypatch, payload):
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", "http://knowledge")
    monkeypatch.setattr(service.urllib.request, "urlopen", lambda *a, **k: BytesIO(payload))
    assert "error" in ops.knowledge_service_status()


def test_forget_invalidates_catalog(monkeypatch):
    deleted = []
    monkeypatch.setattr(ops, "get_mem0", lambda: SimpleNamespace(delete=deleted.append))
    monkeypatch.setattr(catalog, "_catalog_expires", 999.0)
    assert ops.delete_knowledge_entry("entry") == {"ok": True, "memory_id": "entry"}
    assert deleted == ["entry"]
    assert catalog._catalog_expires == 0


@pytest.mark.parametrize("result", [{"status": "loading"}, {"status": "missing_dependency"}, {"error": "failed"}])
def test_combined_operations_preserve_failure(monkeypatch, result):
    monkeypatch.setattr(ops, "add_knowledge_entry", lambda *a: result)
    monkeypatch.setattr(ops, "delete_knowledge_entry", lambda *a: result)
    monkeypatch.setattr(ops, "list_knowledge_entries", lambda *a: pytest.fail("listed after failure"))
    assert ops.add_knowledge_entry_and_list("fact", "a") == result
    assert ops.delete_knowledge_entry_and_list("id", "a") == result


def test_combined_operations_return_selected_knowledge(monkeypatch):
    monkeypatch.setattr(ops, "add_knowledge_entry", lambda *a: {"ok": True})
    monkeypatch.setattr(ops, "delete_knowledge_entry", lambda *a: {"ok": True})
    monkeypatch.setattr(ops, "list_knowledge_entries", lambda knowledge_id: {"knowledge_id": knowledge_id, "memories": []})
    assert ops.add_knowledge_entry_and_list("fact", "a")["knowledge_id"] == "a"
    assert ops.delete_knowledge_entry_and_list("id", "b")["knowledge_id"] == "b"
    assert "error" in ops.delete_knowledge_entry_and_list("id", "")


def test_concurrent_remember_deduplicates_under_lock(monkeypatch):
    rows = []
    def search(query, *, filters, limit):
        return list(rows)
    def add(text, **kwargs):
        rows.append({"id": "saved", "memory": text})
    store = SimpleNamespace(search=search, add=add)
    monkeypatch.setattr(ops, "get_mem0", lambda: store)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: ops.add_knowledge_entry("same fact", "a"), range(16)))
    assert len(rows) == 1
    assert sum(result["duplicate"] for result in results) == 15


@pytest.mark.parametrize("owner,url,remote", [
    ("1", "http://knowledge", False),
    (" 1 ", "http://knowledge", False),
    ("0", "http://knowledge", True),
    (None, "http://knowledge", True),
    ("0", "", False),
    (None, "", False),
])
def test_owner_selects_local_or_http_operation(monkeypatch, owner, url, remote):
    if owner is not None:
        monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", owner)
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", url)
    deleted, requests = [], []
    monkeypatch.setattr(ops, "get_mem0", lambda: SimpleNamespace(delete=deleted.append))
    def request(req, **kwargs):
        requests.append(req.full_url)
        return BytesIO(b'{"ok":true}')
    monkeypatch.setattr(service.urllib.request, "urlopen", request)
    assert ops.delete_knowledge_entry("entry")["ok"] is True
    assert requests == (["http://knowledge/forget"] if remote else [])
    assert deleted == ([] if remote else ["entry"])
