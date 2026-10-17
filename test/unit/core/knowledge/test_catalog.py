from types import SimpleNamespace
from uuid import UUID
from contextlib import nullcontext

import pytest
from qdrant_client import QdrantClient, models

from core.knowledge import catalog
from core.knowledge.catalog import format_knowledge_entry, list_store_entries, scroll_knowledge_records


@pytest.fixture
def knowledge_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = QdrantClient(":memory:")
    client.create_collection("knowledge", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
    client.upsert("knowledge", points=[models.PointStruct(
        id=i, vector=[1.0, 0.0], payload={"user_id": "alpha" if i < 270 else "orphan", "data": f"entry-{i}"}
    ) for i in range(275)])
    catalog.invalidate_knowledge_catalog()
    try:
        yield client
    finally:
        client.close()
        catalog.invalidate_knowledge_catalog()


def test_counts_scan_all_vector_pages(knowledge_store):
    assert catalog.get_knowledge_entry_counts(knowledge_store, "knowledge") == {"alpha": 270, "orphan": 5}


def test_collect_entry_ids_reads_all_pages_and_only_the_selected_knowledge(knowledge_store):
    assert catalog.collect_knowledge_entry_ids(knowledge_store, "knowledge", " alpha ") == sorted(
        str(i) for i in range(270)
    )
    assert catalog.collect_knowledge_entry_ids(knowledge_store, "knowledge", "empty") == []


def test_collect_entry_ids_deduplicates_across_pages(monkeypatch):
    def scroll(client, collection_name, *, knowledge_id, cursor, limit):
        assert collection_name == "knowledge"
        assert knowledge_id == "alpha"
        if cursor is None:
            return [SimpleNamespace(id="b"), SimpleNamespace(id="a")], 1
        assert cursor == "1"
        return [SimpleNamespace(id="a"), SimpleNamespace(id="c")], None

    monkeypatch.setattr(catalog, "scroll_knowledge_records", scroll)
    assert catalog.collect_knowledge_entry_ids(object(), "knowledge", "alpha") == ["a", "b", "c"]


def test_collect_entry_ids_rejects_blank_id_before_reading(monkeypatch):
    monkeypatch.setattr(catalog, "scroll_knowledge_records", lambda *a, **kw: pytest.fail("unfiltered read"))
    with pytest.raises(ValueError, match="knowledge id is required"):
        catalog.collect_knowledge_entry_ids(object(), "knowledge", " ")


def test_counts_do_not_reuse_cache_for_another_collection(knowledge_store):
    assert catalog.get_knowledge_entry_counts(knowledge_store, "knowledge") == {"alpha": 270, "orphan": 5}
    knowledge_store.create_collection("other", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
    knowledge_store.upsert("other", points=[
        models.PointStruct(id=1, vector=[1.0, 0.0], payload={"user_id": "different"}),
    ])
    assert catalog.get_knowledge_entry_counts(knowledge_store, "other") == {"different": 1}
    assert catalog.get_knowledge_entry_counts(knowledge_store, "knowledge") == {"alpha": 270, "orphan": 5}


def test_counts_do_not_reuse_cache_for_another_client(knowledge_store):
    assert catalog.get_knowledge_entry_counts(knowledge_store, "knowledge") == {"alpha": 270, "orphan": 5}
    other = QdrantClient(":memory:")
    try:
        other.create_collection("knowledge", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
        assert catalog.get_knowledge_entry_counts(other, "knowledge") == {}
    finally:
        other.close()
    assert catalog.get_knowledge_entry_counts(knowledge_store, "knowledge") == {"alpha": 270, "orphan": 5}


def test_catalog_invalidation_observes_new_data(knowledge_store):
    catalog.get_knowledge_entry_counts(knowledge_store, "knowledge")
    knowledge_store.upsert("knowledge", points=[models.PointStruct(
        id=300, vector=[1.0, 0.0], payload={"user_id": "new-knowledge", "data": "new"}
    )])
    catalog.invalidate_knowledge_catalog()
    result = catalog.get_knowledge_entry_counts(knowledge_store, "knowledge")
    assert len(result) == 3
    assert result["new-knowledge"] == 1


@pytest.mark.parametrize("fail_after_write", [False, True])
def test_write_scope_refreshes_cached_counts_even_after_partial_failure(knowledge_store, fail_after_write):
    assert "new" not in catalog.get_knowledge_entry_counts(knowledge_store, "knowledge")
    expected = pytest.raises(RuntimeError, match="write interrupted") if fail_after_write else nullcontext()
    with expected:
        with catalog.invalidate_catalog_after_write():
            knowledge_store.upsert("knowledge", points=[
                models.PointStruct(id=300, vector=[1.0, 0.0], payload={"user_id": "new"}),
            ])
            if fail_after_write:
                raise RuntimeError("write interrupted")
    assert catalog.get_knowledge_entry_counts(knowledge_store, "knowledge")["new"] == 1


def test_catalog_reuses_cache_until_ttl_expires(knowledge_store, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(catalog.time, "monotonic", lambda: clock[0])
    assert catalog.get_knowledge_entry_counts(knowledge_store, "knowledge") == {"alpha": 270, "orphan": 5}
    knowledge_store.upsert("knowledge", points=[models.PointStruct(
        id=300, vector=[1.0, 0.0], payload={"user_id": "new", "data": "new"},
    )])
    clock[0] = 129.0
    assert catalog.get_knowledge_entry_counts(knowledge_store, "knowledge").get("new", 0) == 0
    clock[0] = 130.0
    assert catalog.get_knowledge_entry_counts(knowledge_store, "knowledge").get("new", 0) == 1


def test_catalog_refresh_bypasses_unexpired_cache(knowledge_store, monkeypatch):
    monkeypatch.setattr(catalog.time, "monotonic", lambda: 100.0)
    catalog.get_knowledge_entry_counts(knowledge_store, "knowledge")
    knowledge_store.upsert("knowledge", points=[models.PointStruct(
        id=300, vector=[1.0, 0.0], payload={"user_id": "new", "data": "new"},
    )])
    assert catalog.get_knowledge_entry_counts(knowledge_store, "knowledge").get("new", 0) == 0
    assert catalog.get_knowledge_entry_counts(knowledge_store, "knowledge", refresh=True).get("new", 0) == 1


def test_failed_catalog_refresh_does_not_publish_partial_scan(knowledge_store, monkeypatch):
    expected = catalog.get_knowledge_entry_counts(knowledge_store, "knowledge")
    original_scroll = catalog.scroll_knowledge_records

    def fail_second_page(client, collection_name, **kwargs):
        if kwargs["cursor"] is not None:
            raise RuntimeError("scan interrupted")
        return original_scroll(client, collection_name, **kwargs)

    monkeypatch.setattr(catalog, "scroll_knowledge_records", fail_second_page)
    with pytest.raises(RuntimeError, match="scan interrupted"):
        catalog.get_knowledge_entry_counts(knowledge_store, "knowledge", refresh=True)
    assert catalog.get_knowledge_entry_counts(knowledge_store, "knowledge") == expected


def test_scroll_filters_knowledge_and_paginates_without_vectors():
    client = QdrantClient(":memory:")
    try:
        client.create_collection("knowledge", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
        client.upsert("knowledge", points=[
            models.PointStruct(id=i, vector=[1.0, 0.0], payload={"user_id": name, "data": str(i)})
            for i, name in enumerate(["alpha", "other", "alpha"])
        ])
        rows, cursor = scroll_knowledge_records(client, "knowledge", knowledge_id="alpha", limit=1)
        assert [row.id for row in rows] == [0]
        assert rows[0].payload == {"user_id": "alpha", "data": "0"}
        assert rows[0].vector is None
        assert cursor is not None
        rows, cursor = scroll_knowledge_records(client, "knowledge", knowledge_id="alpha", cursor=str(cursor), limit=1)
        assert [row.id for row in rows] == [2]
        assert cursor is None
        rows, _ = scroll_knowledge_records(client, "knowledge", catalog=True)
        assert len(rows) == 3
        assert all(set(row.payload) == {"user_id"} for row in rows)
    finally:
        client.close()


@pytest.mark.parametrize("cursor,expected", [(None, None), ("42", 42), (str(UUID(int=1)), str(UUID(int=1)))])
def test_cursor_conversion(cursor, expected):
    calls = []
    client = SimpleNamespace(scroll=lambda **kwargs: calls.append(kwargs) or ([], None))
    assert scroll_knowledge_records(client, "selected", cursor=cursor) == ([], None)
    assert calls[0]["offset"] == expected
    assert calls[0]["collection_name"] == "selected"


def test_invalid_cursor_fails_before_reading_client():
    client = SimpleNamespace(scroll=lambda **kwargs: pytest.fail("read with invalid cursor"))
    with pytest.raises(ValueError, match="invalid knowledge entries cursor"):
        scroll_knowledge_records(client, "knowledge", cursor="invalid")


@pytest.mark.parametrize("parameter", ["limit", "top_k"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_entry_list_adapts_mem0_arguments_and_result_envelopes(parameter, wrapped):
    calls = []

    def result(filters, count):
        calls.append((filters, count))
        rows = [{"id": "1", "memory": "setting"}]
        return {"results": rows} if wrapped else rows

    def legacy(*, filters, limit):
        return result(filters, limit)

    def current(*, filters, top_k, **kwargs):
        return result(filters, top_k)

    store = SimpleNamespace(get_all=current if parameter == "top_k" else legacy)
    assert list_store_entries(store.get_all, "alpha", 200) == [
        {"id": "1", "memory": "setting"},
    ]
    assert calls == [({"user_id": "alpha"}, 200)]


@pytest.mark.parametrize("wrapped", [False, True])
def test_entry_list_returns_empty_results(wrapped):
    def get_all(*, filters, limit):
        return {"results": []} if wrapped else []

    store = SimpleNamespace(get_all=get_all)
    assert list_store_entries(store.get_all, "empty", 5) == []


@pytest.mark.parametrize(("row", "include_text", "expected"), [
    ({"id": "1", "memory": "setting", "content": "other"}, False, {"id": "1", "memory": "setting"}),
    ({"id": "2", "content": "other"}, False, {"id": "2", "memory": "other"}),
    ("plain", False, {"id": "", "memory": "plain"}),
    ({"id": 3, "text": "text only"}, False, {"id": "3", "memory": ""}),
    ({"id": 3, "text": "text only"}, True, {"id": "3", "memory": "text only"}),
    ({"id": "4", "content": "other", "text": "fallback"}, True, {"id": "4", "memory": "other"}),
])
def test_format_knowledge_entry_normalizes_rows(row, include_text, expected):
    assert format_knowledge_entry(row, include_text=include_text) == expected
