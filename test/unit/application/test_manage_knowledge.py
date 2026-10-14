"""Application knowledge binding, preview, and status workflows."""


import pytest

from core.knowledge import bindings
from application.knowledge import manage_knowledge


def test_character_binding_rename_and_clear_preserve_lifecycle_without_loading_model(tmp_path, monkeypatch):
    from core.knowledge import bindings
    from ai.knowledge import runtime
    monkeypatch.setattr(bindings, "_database_path", lambda: tmp_path / "knowledge.db")
    monkeypatch.setattr(runtime, "get_mem0", lambda: pytest.fail("loaded model"))
    monkeypatch.setattr(runtime, "start_mem0_loading", lambda **kw: pytest.fail("started model"))
    manage_knowledge.add_binding("Old", "a")
    manage_knowledge.add_binding("Old", "b")
    manage_knowledge.rename_character_bindings("Old", "New")
    assert manage_knowledge.list_character_bindings("Old")["count"] == 0
    assert manage_knowledge.list_character_bindings("New")["count"] == 2
    manage_knowledge.add_binding("Other", "a")
    manage_knowledge.clear_character_bindings("New")
    assert manage_knowledge.list_character_bindings("New")["count"] == 0
    assert bindings.list_knowledge_ids_for_characters(["Other"]) == ["a"]


def test_check_knowledge_status_delegates_start_loading_to_runtime(monkeypatch):
    from ai.knowledge import runtime
    monkeypatch.setattr(runtime, "check_mem0_status", lambda *, start_loading: {"start": start_loading})
    assert manage_knowledge.check_knowledge_status(start_loading=False) == {"start": False}


def test_preview_import_reads_source_without_loading_model(monkeypatch, tmp_path):
    from ai.knowledge import runtime
    monkeypatch.setattr(runtime, "get_mem0", lambda: pytest.fail("loaded model"))
    monkeypatch.setattr(runtime, "start_mem0_loading", lambda **_: pytest.fail("started model"))
    path = tmp_path / "novel.txt"
    path.write_text("一段小说。", encoding="utf-8")
    result = manage_knowledge.preview_import([path], knowledge_id="knowledge", source_root=tmp_path, config_manager=None)
    assert result["fileCount"] == 1


@pytest.mark.parametrize("operation", [
    lambda: manage_knowledge.list_entries("a"),
    lambda: manage_knowledge.search_entries("a", "fact"),
    lambda: manage_knowledge.list_instances(),
    lambda: manage_knowledge.remember_knowledge("fact", "a"),
    lambda: manage_knowledge.remember_and_list("fact", "a"),
    lambda: manage_knowledge.forget_knowledge("id"),
])
def test_runtime_failure_is_an_error_result(monkeypatch, operation):
    def fail():
        raise RuntimeError("store unavailable")
    monkeypatch.setattr(manage_knowledge, "get_mem0", fail)
    assert operation() == {"error": "store unavailable"}


def test_unbound_search_does_not_acquire_store(monkeypatch):
    monkeypatch.setattr("ai.knowledge.service.request_knowledge_service", lambda *args: None)
    monkeypatch.setattr(manage_knowledge, "list_knowledge_ids_for_characters", lambda names: [])
    monkeypatch.setattr(manage_knowledge, "get_mem0", lambda: pytest.fail("unbound search loaded store"))
    assert manage_knowledge.search_knowledge("fact", character_names=["A"]) == {
        "query": "fact", "knowledge_ids": [], "count": 0, "memories": [],
    }


@pytest.mark.parametrize("write_result", [{"ok": True}, {"error": "failed"}])
def test_remember_and_list_reuses_store_and_only_lists_after_success(monkeypatch, write_result):
    from ai.knowledge import operations
    store = object()
    acquired, calls = [], []
    monkeypatch.setattr(manage_knowledge, "get_mem0", lambda: acquired.append(store) or store)
    monkeypatch.setattr(operations, "add_knowledge_entry", lambda actual, *args: calls.append(("write", actual)) or write_result)
    listed = {"knowledge_id": "a", "memories": []}
    monkeypatch.setattr(operations, "list_knowledge_entries", lambda actual, *args: calls.append(("list", actual)) or listed)
    result = manage_knowledge.remember_and_list("fact", "a")
    assert acquired == [store]
    assert calls == ([("write", store), ("list", store)] if write_result.get("ok") else [("write", store)])
    assert result == (listed if write_result.get("ok") else write_result)


def test_chat_hook_uses_application_search(monkeypatch):
    from application.knowledge.hooks import install_knowledge_hooks
    from sdk.hooks import PluginHookDispatcher
    monkeypatch.setenv("SHINSEKAI_KNOWLEDGE_ENABLED", "1")
    hooks = install_knowledge_hooks(PluginHookDispatcher(), character_names=["A"])
    assert hooks.search_func is manage_knowledge.search_knowledge
