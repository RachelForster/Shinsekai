"""Knowledge bridge dependency checks and request dispatch contracts."""

import importlib.util

import pytest

from application.knowledge import manage_knowledge
from frontend_bridge_core import knowledge
from application.runtime import dependencies
from sdk.exception.types import runtime_dependency_error_from_module


@pytest.fixture
def missing_runtime(monkeypatch):
    error = runtime_dependency_error_from_module("mem0")
    error["message"] = "Missing or incompatible runtime dependencies"
    monkeypatch.setattr(dependencies, "runtime_dependency_error_for_module", lambda _: error)
    return error


def test_knowledge_browse_entries_returns_loading_without_querying_store(monkeypatch):
    monkeypatch.setattr(knowledge, "_get_knowledge_status", lambda **kwargs: {"status": "loading"})
    monkeypatch.setattr(manage_knowledge, "list_entries", lambda **kwargs: pytest.fail("queried unready store"))
    assert knowledge._knowledge_browse("entries", knowledge_id="w") == {"status": "loading"}


def test_knowledge_browse_entries_delegates_when_runtime_is_ready(monkeypatch):
    monkeypatch.setattr(knowledge, "_get_knowledge_status", lambda **kwargs: {"status": "ready"})
    monkeypatch.setattr(manage_knowledge, "list_entries", lambda **kwargs: kwargs)
    assert knowledge._knowledge_browse("entries", knowledge_id="w") == {"knowledge_id": "w"}


def test_get_knowledge_status_returns_missing_dependency(missing_runtime):
    assert knowledge._get_knowledge_status(start_loading=False) == {**missing_runtime, "status": "missing_dependency"}


def test_knowledge_search_returns_missing_dependency(missing_runtime):
    assert knowledge._knowledge_search("query", character_names=["A"]) == {**missing_runtime, "status": "missing_dependency"}


@pytest.mark.parametrize("invalid_spec", [False, True], ids=["missing-module", "invalid-spec"])
def test_check_mem0_before_call_reports_unavailable_module(monkeypatch, invalid_spec):
    monkeypatch.setattr(dependencies, "runtime_dependency_error_for_module", lambda _: None)
    def find_spec(_):
        if invalid_spec:
            raise ValueError("missing spec")
        return None
    monkeypatch.setattr(importlib.util, "find_spec", find_spec)
    result = knowledge._check_mem0_before_call()
    assert result["moduleName"] == "mem0"
    assert result["kind"] == "missing_dependency"


def test_knowledge_forget_dispatch_uses_local_store_when_bridge_owns_service(monkeypatch):
    from ai.knowledge import operations, service as knowledge_client
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", "http://self/api/knowledge")
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", "1")
    monkeypatch.setattr(knowledge, "_get_knowledge_status", lambda **kwargs: {"status": "ready"})
    monkeypatch.setattr(operations, "get_mem0", lambda: type("Store", (), {"delete": lambda self, mid: None})())
    monkeypatch.setattr(knowledge_client.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("recursive request"))
    assert knowledge._knowledge_operation("forget", memory_id="id")["ok"] is True


def test_knowledge_browse_catalog_refresh_requests_runtime_retry(monkeypatch):
    calls = []
    monkeypatch.setattr(knowledge, "_get_knowledge_status", lambda **kwargs: calls.append(kwargs) or {"status": "loading"})
    assert knowledge._knowledge_browse("instances", refresh=True)["status"] == "loading"
    assert calls == [{"start_loading": True, "retry": True}]


def test_knowledge_binding_dispatch_supports_crud_without_loading_model(tmp_path, monkeypatch):
    from ai.knowledge import bindings, runtime
    monkeypatch.setattr(bindings, "_database_path", lambda: tmp_path / "knowledge.db")
    monkeypatch.setattr(knowledge, "_get_knowledge_status", lambda **_: pytest.fail("checked model"))
    monkeypatch.setattr(runtime, "get_mem0", lambda: pytest.fail("loaded model"))
    dispatch = knowledge._knowledge_binding_operation
    assert dispatch("add", character_name="A", knowledge_id="w")["ok"]
    assert dispatch("list", character_name="A")["count"] == 1
    assert dispatch("remove", character_name="A", knowledge_id="w")["deleted"]
    assert dispatch("list", character_name="A")["count"] == 0


def test_knowledge_delete_returns_loading_without_calling_application(monkeypatch):
    monkeypatch.setattr(knowledge, "_get_knowledge_status", lambda **_: {"status": "loading"})
    monkeypatch.setattr(manage_knowledge, "delete_knowledge", lambda **_: pytest.fail("deleted before ready"))
    assert knowledge._knowledge_operation("delete", knowledge_id="w") == {"status": "loading"}


def test_knowledge_delete_dispatches_to_application_when_runtime_is_ready(monkeypatch):
    monkeypatch.setattr(knowledge, "_get_knowledge_status", lambda **_: {"status": "ready"})
    monkeypatch.setattr(manage_knowledge, "delete_knowledge", lambda **kw: {"ok": True, **kw})
    assert knowledge._knowledge_operation("delete", knowledge_id="w") == {"ok": True, "knowledge_id": "w"}


def test_get_knowledge_status_delegates_to_application_when_dependencies_are_available(monkeypatch):
    monkeypatch.setattr(knowledge, "_check_mem0_before_call", lambda: None)
    monkeypatch.setattr(manage_knowledge, "check_knowledge_status", lambda *, start_loading: {"start": start_loading})
    assert knowledge._get_knowledge_status(start_loading=False) == {"start": False}


def test_run_knowledge_import_rejects_missing_dependencies_before_accessing_state(missing_runtime):
    with pytest.raises(RuntimeError, match="incompatible"):
        knowledge._run_knowledge_import(None, "task", "knowledge", [], source_root=".")
