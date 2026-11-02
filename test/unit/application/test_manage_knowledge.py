"""Application knowledge binding, preview, and status workflows."""


from types import SimpleNamespace

import pytest

from core.knowledge import bindings
from application.knowledge import manage_knowledge


def test_character_binding_rename_and_clear_preserve_lifecycle_without_loading_model(tmp_path, monkeypatch):
    from core.knowledge import bindings
    from application.knowledge import runtime
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
    from application.knowledge import runtime
    monkeypatch.setattr(runtime, "check_mem0_status", lambda *, start_loading: {"start": start_loading})
    assert manage_knowledge.check_knowledge_status(start_loading=False) == {"start": False}


def test_preview_import_reads_source_without_loading_model(monkeypatch, tmp_path):
    from application.knowledge import runtime
    monkeypatch.setattr(runtime, "get_mem0", lambda: pytest.fail("loaded model"))
    monkeypatch.setattr(runtime, "start_mem0_loading", lambda **_: pytest.fail("started model"))
    path = tmp_path / "novel.txt"
    path.write_text("一段小说。", encoding="utf-8")
    result = manage_knowledge.preview_import([path], knowledge_id="knowledge", source_root=tmp_path, config_manager=None)
    assert result["fileCount"] == 1


@pytest.mark.parametrize("operation", [
    lambda: manage_knowledge.get_knowledge_entries("a"),
    lambda: manage_knowledge.search_entries("a", "fact"),
    lambda: manage_knowledge.remember_knowledge("fact", "a"),
    lambda: manage_knowledge.remember_and_list("fact", "a"),
    lambda: manage_knowledge.forget_knowledge("id"),
])
def test_runtime_failure_is_an_error_result(monkeypatch, operation):
    def fail():
        raise RuntimeError("store unavailable")
    monkeypatch.setattr(manage_knowledge, "get_mem0", fail)
    assert operation() == {"error": "store unavailable"}


@pytest.mark.parametrize("write_result", [{"ok": True}, {"error": "failed"}])
def test_remember_and_list_reuses_store_and_only_lists_after_success(monkeypatch, write_result):
    from ai.knowledge import operations
    store = SimpleNamespace(get_all=lambda **kwargs: [])
    acquired, calls = [], []
    monkeypatch.setattr(manage_knowledge, "get_mem0", lambda: acquired.append(store) or store)
    monkeypatch.setattr(operations, "add_knowledge_entry", lambda actual, *args: calls.append(("write", actual)) or write_result)
    listed = {"knowledge_id": "a", "memories": []}
    monkeypatch.setattr(manage_knowledge, "read_knowledge_entries", lambda actual, *args: calls.append(("list", actual)) or listed)
    result = manage_knowledge.remember_and_list("fact", "a")
    assert acquired == [store]
    assert calls == ([("write", store), ("list", store.get_all)] if write_result.get("ok") else [("write", store)])
    assert result == (listed if write_result.get("ok") else write_result)


def test_chat_hook_uses_injected_search(monkeypatch):
    from application.knowledge.hooks import install_knowledge_hooks
    from sdk.hooks import PluginHookDispatcher
    search = lambda *args, **kwargs: {"memories": []}
    hooks = install_knowledge_hooks(PluginHookDispatcher(), character_names=["A"], search_func=search, status_func=lambda **kw: {"status": "ready"})
    assert hooks.search_func is search


@pytest.fixture
def directory(tmp_path, monkeypatch):
    monkeypatch.setattr(bindings, "_database_path", lambda: tmp_path / "knowledge.db")
    client = object()
    store = SimpleNamespace(vector_store=SimpleNamespace(client=client, collection_name="knowledge"))
    counts = {"alpha": 270, "orphan": 5}
    calls = []
    monkeypatch.setattr(manage_knowledge, "get_mem0", lambda: store)

    def entry_counts(actual_client, collection_name, *, refresh=False):
        assert actual_client is client
        assert collection_name == "knowledge"
        calls.append(refresh)
        return dict(counts)

    monkeypatch.setattr(manage_knowledge, "get_knowledge_entry_counts", entry_counts)
    bindings.bind_character_knowledge("A", "alpha")
    bindings.bind_character_knowledge("B", "empty")
    return counts, calls


def test_directory_includes_vector_only_and_binding_only_knowledge(directory):
    assert manage_knowledge.list_instances() == {
        "count": 3, "page": 1, "pageSize": 20,
        "knowledge": [
            {"knowledge_id": "alpha", "entryCount": 270, "characterCount": 1},
            {"knowledge_id": "empty", "entryCount": 0, "characterCount": 1},
            {"knowledge_id": "orphan", "entryCount": 5, "characterCount": 0},
        ],
    }


@pytest.mark.parametrize("query,expected_ids", [
    ("alp", ["alpha"]),
    ("ALP", ["alpha"]),
    ("  alp  ", ["alpha"]),
    ("no-match", []),
])
def test_directory_filters_by_normalized_id(directory, query, expected_ids):
    result = manage_knowledge.list_instances(query)
    assert result["count"] == len(expected_ids)
    assert [row["knowledge_id"] for row in result["knowledge"]] == expected_ids


def test_directory_filters_and_sorts_before_pagination(directory):
    counts, _ = directory
    counts.update({"Beta": 1, "beta": 2, "zeta": 3})
    result = manage_knowledge.list_instances("eta", page=2, page_size=1)
    assert result == {
        "count": 3, "page": 2, "pageSize": 1,
        "knowledge": [{"knowledge_id": "beta", "entryCount": 2, "characterCount": 0}],
    }


@pytest.mark.parametrize("page,size,expected_page,expected_size,expected_ids", [
    (0, 0, 1, 1, ["alpha"]),
    (1, 999, 1, 100, ["alpha", "empty", "orphan"]),
    (10, 20, 10, 20, []),
])
def test_directory_pagination(directory, page, size, expected_page, expected_size, expected_ids):
    result = manage_knowledge.list_instances(page=page, page_size=size)
    assert (result["page"], result["pageSize"]) == (expected_page, expected_size)
    assert result["count"] == 3
    assert [row["knowledge_id"] for row in result["knowledge"]] == expected_ids


def test_directory_reads_current_bindings_and_forwards_refresh(directory):
    _, calls = directory
    assert manage_knowledge.list_instances("new")["count"] == 0
    bindings.bind_character_knowledge("C", "new")
    assert manage_knowledge.list_instances("new", refresh=True)["knowledge"] == [
        {"knowledge_id": "new", "entryCount": 0, "characterCount": 1},
    ]
    assert calls == [False, True]


@pytest.mark.parametrize("dependency", ["get_mem0", "get_knowledge_entry_counts", "get_knowledge_binding_counts"])
def test_directory_failure_is_an_error_result(directory, monkeypatch, dependency):
    def fail(*args, **kwargs):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(manage_knowledge, dependency, fail)
    assert manage_knowledge.list_instances() == {"error": "store unavailable"}


def test_entry_list_filters_knowledge_and_bounds_limit(monkeypatch):
    calls = []

    def get_all(*, filters, limit):
        calls.append((filters, limit))
        rows = [] if filters["user_id"] == "empty" else [{"id": "1", "memory": "setting"}]
        return {"results": rows}

    monkeypatch.setattr(manage_knowledge, "get_mem0", lambda: SimpleNamespace(get_all=get_all))
    assert manage_knowledge.get_knowledge_entries("alpha") == {
        "knowledge_id": "alpha", "count": 1, "memories": [{"id": "1", "memory": "setting"}],
    }
    manage_knowledge.get_knowledge_entries("alpha", limit=999)
    manage_knowledge.get_knowledge_entries("orphan", limit=5)
    assert calls == [({"user_id": "alpha"}, 200), ({"user_id": "alpha"}, 200), ({"user_id": "orphan"}, 5)]
    assert manage_knowledge.get_knowledge_entries("empty") == {"knowledge_id": "empty", "count": 0, "memories": []}


def test_entry_list_read_failure_is_an_error_result(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("read failed")

    monkeypatch.setattr(manage_knowledge, "get_mem0", lambda: SimpleNamespace(get_all=fail))
    assert manage_knowledge.get_knowledge_entries("a") == {"error": "read failed"}


def test_entry_list_blank_id_does_not_load_store(monkeypatch):
    monkeypatch.setattr(manage_knowledge, "get_mem0", lambda: pytest.fail("loaded store"))
    assert manage_knowledge.get_knowledge_entries(" ") == {"error": "knowledge id is required"}
