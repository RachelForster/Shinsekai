"""Knowledge deletion, failure recovery, and import coordination."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from core.knowledge import catalog
from core.knowledge import bindings
from application.knowledge import delete_knowledge as deletion


@pytest.fixture
def isolated_knowledge(tmp_path, monkeypatch):
    monkeypatch.setattr(bindings, "_database_path", lambda: tmp_path / "knowledge.db")
    monkeypatch.delenv("SHINSEKAI_KNOWLEDGE_SERVICE_URL", raising=False)
    monkeypatch.delenv("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER", raising=False)


def install_deletion_store(monkeypatch, rows, *, fail_on=None):
    events = []
    client = object()
    def scroll(actual_client, collection_name, *, knowledge_id, cursor, limit):
        assert actual_client is client
        assert collection_name == "knowledge"
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
    monkeypatch.setattr(catalog, "scroll_knowledge_records", scroll)
    monkeypatch.setattr(deletion, "get_mem0", lambda: SimpleNamespace(delete=delete, vector_store=SimpleNamespace(client=client, collection_name="knowledge")))
    return events


def test_delete_knowledge_removes_all_pages_and_bindings_without_touching_other_knowledge(isolated_knowledge, monkeypatch):
    rows = {str(i): "target" for i in range(520)} | {"other-entry": "other"}
    events = install_deletion_store(monkeypatch, rows)
    bindings.bind_character_knowledge("A", "target")
    bindings.bind_character_knowledge("B", "target")
    bindings.bind_character_knowledge("A", "other")
    monkeypatch.setattr(catalog, "_catalog_expires", 999)
    assert deletion.delete_knowledge_base(" target ") == {
        "ok": True, "knowledge_id": "target", "deletedEntryCount": 520, "deletedBindingCount": 2,
    }
    assert events[:4] == ["scroll", "scroll", "scroll", "delete"]
    assert rows == {"other-entry": "other"}
    assert bindings.list_knowledge_ids_for_characters(["A", "B"]) == ["other"]
    assert catalog._catalog_expires == 0
    assert deletion.delete_knowledge_base("target")["deletedEntryCount"] == 0


def test_delete_knowledge_entry_failure_preserves_bindings_and_allows_retry(isolated_knowledge, monkeypatch):
    rows = {"a": "target", "b": "target"}
    install_deletion_store(monkeypatch, rows, fail_on="b")
    bindings.bind_character_knowledge("A", "target")
    result = deletion.delete_knowledge_base("target")
    assert result["ok"] is False and result["failedStage"] == "entries"
    assert result["deletedEntryCount"] == 1 and result["deletedBindingCount"] == 0
    assert bindings.list_knowledge_ids_for_characters(["A"]) == ["target"]
    install_deletion_store(monkeypatch, rows)
    assert deletion.delete_knowledge_base("target")["deletedBindingCount"] == 1
    assert rows == {}


def test_delete_knowledge_binding_failure_reports_stage_and_allows_retry(isolated_knowledge, monkeypatch):
    install_deletion_store(monkeypatch, {})
    bindings.bind_character_knowledge("A", "target")
    real_delete = bindings.delete_knowledge_bindings
    def fail(_):
        raise RuntimeError("database locked")
    monkeypatch.setattr(bindings, "delete_knowledge_bindings", fail)
    result = deletion.delete_knowledge_base("target")
    assert result["failedStage"] == "bindings"
    monkeypatch.setattr(bindings, "delete_knowledge_bindings", real_delete)
    assert deletion.delete_knowledge_base("target")["deletedBindingCount"] == 1


def test_delete_knowledge_rejects_blank_id_without_loading_store(isolated_knowledge, monkeypatch):
    monkeypatch.setattr(deletion, "get_mem0", lambda: pytest.fail("loaded store"))
    assert deletion.delete_knowledge_base(" ")["failedStage"] == "validate"


def test_collect_failure_does_not_start_deletion(isolated_knowledge, monkeypatch):
    rows = {str(i): "target" for i in range(520)}
    events = install_deletion_store(monkeypatch, rows)
    bindings.bind_character_knowledge("A", "target")
    original_scroll = catalog.scroll_knowledge_records

    def fail_second_page(*args, **kwargs):
        if kwargs["cursor"] is not None:
            raise RuntimeError("scan interrupted")
        return original_scroll(*args, **kwargs)

    monkeypatch.setattr(catalog, "scroll_knowledge_records", fail_second_page)
    result = deletion.delete_knowledge_base("target")
    assert result["failedStage"] == "collect"
    assert result["deletedEntryCount"] == result["deletedBindingCount"] == 0
    assert events == ["scroll"]
    assert len(rows) == 520
    assert bindings.list_knowledge_ids_for_characters(["A"]) == ["target"]


def test_delete_knowledge_does_not_wait_for_import_extraction(isolated_knowledge, tmp_path, monkeypatch):
    from application.knowledge import import_knowledge as imports
    monkeypatch.setattr(imports, "get_mem0", lambda: object())
    path = tmp_path / "source.txt"
    path.write_text("Knowledge setting.", encoding="utf-8")
    entered, release = Event(), Event()
    rows = {"old": "target"}
    install_deletion_store(monkeypatch, rows)

    def extract(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return [{"content": "Knowledge setting.", "knowledge_id": "target"}]

    monkeypatch.setattr(imports.KnowledgeExtractor, "extract_chunk", extract)
    monkeypatch.setattr(imports, "add_knowledge_entry", lambda *_: {"ok": True})
    with ThreadPoolExecutor(max_workers=2) as pool:
        importing = pool.submit(
            imports.execute_knowledge_import, [path], knowledge_id="target",
            source_root=tmp_path, max_chunk_tokens=256, llm_adapter=None,
        )
        try:
            assert entered.wait(5)
            deleting_future = pool.submit(deletion.delete_knowledge_base, "target")
            assert deleting_future.result(timeout=2)["deletedEntryCount"] == 1
            assert rows == {}
        finally:
            release.set()
        assert importing.result(timeout=5)["savedCount"] == 1


def test_delete_knowledge_waits_for_import_writes_before_removing_entries(isolated_knowledge, tmp_path, monkeypatch):
    from application.knowledge import import_knowledge as imports
    monkeypatch.setattr(imports, "get_mem0", lambda: object())
    from test.mocks import MockLLMAdapter
    path = tmp_path / "source.txt"
    path.write_text("Knowledge setting.", encoding="utf-8")
    entered, release, deleting = Event(), Event(), Event()
    rows = {}
    install_deletion_store(monkeypatch, rows)
    def remember(*_):
        entered.set()
        assert release.wait(5)
        rows["new"] = "target"
        return {"ok": True}
    monkeypatch.setattr(imports, "add_knowledge_entry", remember)
    def delete():
        deleting.set()
        return deletion.delete_knowledge_base("target")
    with ThreadPoolExecutor(max_workers=2) as pool:
        importing = pool.submit(imports.execute_knowledge_import, [path], knowledge_id="target",
                                source_root=tmp_path, max_chunk_tokens=256,
                                llm_adapter=MockLLMAdapter(responses=['[{"content":"Knowledge setting."}]']))
        try:
            assert entered.wait(5)
            deleting_future = pool.submit(delete)
            assert deleting.wait(5)
            assert not deleting_future.done()
        finally:
            release.set()
        assert importing.result(timeout=5)["savedCount"] == 1
        assert deleting_future.result(timeout=5)["deletedBindingCount"] == 0
    assert rows == {}
    assert bindings.list_knowledge_ids_for_characters(["A"]) == []


def test_forget_invalidates_catalog(monkeypatch):
    deleted = []
    store = SimpleNamespace(delete=deleted.append)
    monkeypatch.setattr(catalog, "_catalog_expires", 999.0)
    assert deletion.delete_knowledge_entry(store, "entry") == {"ok": True, "memory_id": "entry"}
    assert deleted == ["entry"]
    assert catalog._catalog_expires == 0


def test_delete_entry_store_failure_is_an_error_result(monkeypatch):
    def fail(mid):
        raise RuntimeError("store unavailable")
    store = SimpleNamespace(delete=fail)
    assert deletion.delete_knowledge_entry(store, "id")["error"] == "store unavailable"


def test_delete_entry_rejects_blank_id_without_touching_store():
    assert deletion.delete_knowledge_entry(object(), " ") == {"error": "memory id is required"}


@pytest.mark.parametrize("result", [{"status": "loading"}, {"status": "missing_dependency"}, {"error": "failed"}])
def test_forget_and_list_preserves_failure(monkeypatch, result):
    monkeypatch.setattr(deletion, "get_mem0", lambda: SimpleNamespace(get_all=lambda **kwargs: []))
    monkeypatch.setattr(deletion, "delete_knowledge_entry", lambda *a: result)
    monkeypatch.setattr(deletion, "read_knowledge_entries", lambda *a: pytest.fail("listed after failure"))
    assert deletion.delete_knowledge_entry_and_list("id", "a") == result


def test_forget_and_list_returns_selected_knowledge(monkeypatch):
    monkeypatch.setattr(deletion, "get_mem0", lambda: SimpleNamespace(get_all=lambda **kwargs: []))
    monkeypatch.setattr(deletion, "delete_knowledge_entry", lambda *a: {"ok": True})
    monkeypatch.setattr(deletion, "read_knowledge_entries", lambda get_all, knowledge_id: {"knowledge_id": knowledge_id, "memories": []})
    assert deletion.delete_knowledge_entry_and_list("id", "b")["knowledge_id"] == "b"
    assert "error" in deletion.delete_knowledge_entry_and_list("id", "")


def test_delete_and_list_reuses_store(monkeypatch):
    acquired, events = [], []
    store = SimpleNamespace(
        delete=lambda mid: events.append(("delete", mid)),
        get_all=lambda *, filters, limit: events.append(("list", filters)) or [],
    )
    monkeypatch.setattr(deletion, "get_mem0", lambda: acquired.append(store) or store)
    assert deletion.delete_knowledge_entry_and_list(" id ", "a") == {
        "knowledge_id": "a", "count": 0, "memories": [],
    }
    assert acquired == [store]
    assert events == [("delete", "id"), ("list", {"user_id": "a"})]
