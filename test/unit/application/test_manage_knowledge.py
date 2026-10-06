"""Application knowledge binding, preview, status, and deletion workflows."""

from types import SimpleNamespace

import pytest

from ai.knowledge import bindings, catalog, operations as ops
from application.knowledge import manage_knowledge


@pytest.fixture
def isolated_knowledge(tmp_path, monkeypatch):
    monkeypatch.setattr(bindings, "_database_path", lambda: tmp_path / "knowledge.db")
    monkeypatch.delenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", raising=False)
    monkeypatch.delenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", raising=False)


def install_deletion_store(monkeypatch, rows, *, fail_on=None):
    events = []
    def scroll(store, *, knowledge_id, cursor, limit):
        assert knowledge_id == "target"
        events.append("scroll")
        ids = sorted(key for key, entry_knowledge_id in rows.items() if entry_knowledge_id == knowledge_id)
        start = int(cursor or 0)
        end = start + limit
        return [SimpleNamespace(id=mid) for mid in ids[start:end]], end if end < len(ids) else None
    def delete(mid):
        events.append("delete")
        if mid == fail_on:
            raise RuntimeError("write failed")
        del rows[mid]
    monkeypatch.setattr(ops, "scroll_knowledge_records", scroll)
    monkeypatch.setattr(ops, "get_mem0", lambda: SimpleNamespace(delete=delete))
    return events


def test_delete_knowledge_removes_all_pages_and_bindings_without_touching_other_knowledge(isolated_knowledge, monkeypatch):
    rows = {str(i): "target" for i in range(520)} | {"other-entry": "other"}
    events = install_deletion_store(monkeypatch, rows)
    bindings.bind_character_knowledge("A", "target")
    bindings.bind_character_knowledge("B", "target")
    bindings.bind_character_knowledge("A", "other")
    monkeypatch.setattr(catalog, "_catalog_expires", 999)
    assert manage_knowledge.delete_knowledge(" target ") == {
        "ok": True, "knowledge_id": "target", "deletedEntryCount": 520, "deletedBindingCount": 2,
    }
    assert events[:4] == ["scroll", "scroll", "scroll", "delete"]
    assert rows == {"other-entry": "other"}
    assert bindings.list_knowledge_ids_for_characters(["A", "B"]) == ["other"]
    assert catalog._catalog_expires == 0
    assert manage_knowledge.delete_knowledge("target")["deletedEntryCount"] == 0


def test_delete_knowledge_entry_failure_preserves_bindings_and_allows_retry(isolated_knowledge, monkeypatch):
    rows = {"a": "target", "b": "target"}
    install_deletion_store(monkeypatch, rows, fail_on="b")
    bindings.bind_character_knowledge("A", "target")
    result = manage_knowledge.delete_knowledge("target")
    assert result["ok"] is False and result["failedStage"] == "entries"
    assert result["deletedEntryCount"] == 1 and result["deletedBindingCount"] == 0
    assert bindings.list_knowledge_ids_for_characters(["A"]) == ["target"]
    install_deletion_store(monkeypatch, rows)
    assert manage_knowledge.delete_knowledge("target")["deletedBindingCount"] == 1
    assert rows == {}


def test_delete_knowledge_binding_failure_reports_stage_and_allows_retry(isolated_knowledge, monkeypatch):
    install_deletion_store(monkeypatch, {})
    bindings.bind_character_knowledge("A", "target")
    real_delete = bindings.delete_knowledge_bindings
    def fail(_):
        raise RuntimeError("database locked")
    monkeypatch.setattr(bindings, "delete_knowledge_bindings", fail)
    result = manage_knowledge.delete_knowledge("target")
    assert result["failedStage"] == "bindings"
    monkeypatch.setattr(bindings, "delete_knowledge_bindings", real_delete)
    assert manage_knowledge.delete_knowledge("target")["deletedBindingCount"] == 1


def test_delete_knowledge_rejects_blank_id_without_loading_store(isolated_knowledge, monkeypatch):
    monkeypatch.setattr(ops, "get_mem0", lambda: pytest.fail("loaded store"))
    assert manage_knowledge.delete_knowledge(" ")["failedStage"] == "validate"


def test_delete_knowledge_forwards_remote_request_without_accessing_local_store(isolated_knowledge, monkeypatch):
    calls = []
    monkeypatch.setattr(ops, "request_knowledge_service", lambda endpoint, data: calls.append((endpoint, data)) or {"ok": True})
    monkeypatch.setattr(ops, "get_mem0", lambda: pytest.fail("local store accessed"))
    assert manage_knowledge.delete_knowledge("target") == {"ok": True}
    assert calls == [("delete", {"knowledge_id": "target"})]


def test_character_binding_rename_and_clear_preserve_lifecycle_without_loading_model(tmp_path, monkeypatch):
    from ai.knowledge import bindings, runtime
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
