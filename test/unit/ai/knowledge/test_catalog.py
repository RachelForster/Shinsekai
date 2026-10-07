from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient, models

from ai.knowledge import catalog
from ai.knowledge.bindings import bind_character_knowledge


@pytest.fixture
def knowledge_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = QdrantClient(":memory:")
    client.create_collection("knowledge", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
    client.upsert("knowledge", points=[models.PointStruct(
        id=i, vector=[1.0, 0.0], payload={"user_id": "alpha" if i < 270 else "orphan", "data": f"entry-{i}"}
    ) for i in range(275)])
    store = SimpleNamespace(vector_store=SimpleNamespace(client=client, collection_name="knowledge"))
    catalog.invalidate_knowledge_catalog()
    try:
        yield store
    finally:
        client.close()
        catalog.invalidate_knowledge_catalog()


def test_catalog_scans_all_pages_and_includes_unbound_and_empty_knowledge(knowledge_store):
    bind_character_knowledge("A", "alpha")
    bind_character_knowledge("B", "empty")
    result = catalog.list_knowledge_catalog(knowledge_store)
    assert result["knowledge"] == [
        {"knowledge_id": "alpha", "entryCount": 270, "characterCount": 1},
        {"knowledge_id": "empty", "entryCount": 0, "characterCount": 1},
        {"knowledge_id": "orphan", "entryCount": 5, "characterCount": 0},
    ]


def test_catalog_paginates_results(knowledge_store):
    result = catalog.list_knowledge_catalog(knowledge_store, page=2, page_size=1)
    assert result == {
        "count": 2,
        "page": 2,
        "pageSize": 1,
        "knowledge": [{"knowledge_id": "orphan", "entryCount": 5, "characterCount": 0}],
    }


def test_catalog_invalidation_observes_new_data(knowledge_store):
    catalog.list_knowledge_catalog(knowledge_store)
    knowledge_store.vector_store.client.upsert("knowledge", points=[models.PointStruct(
        id=300, vector=[1.0, 0.0], payload={"user_id": "new-knowledge", "data": "new"}
    )])
    catalog.invalidate_knowledge_catalog()
    result = catalog.list_knowledge_catalog(knowledge_store)
    assert result["count"] == 3
    assert {"knowledge_id": "new-knowledge", "entryCount": 1, "characterCount": 0} in result["knowledge"]


def test_catalog_reuses_cache_until_ttl_expires(knowledge_store, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(catalog.time, "monotonic", lambda: clock[0])
    assert catalog.list_knowledge_catalog(knowledge_store)["count"] == 2
    knowledge_store.vector_store.client.upsert("knowledge", points=[models.PointStruct(
        id=300, vector=[1.0, 0.0], payload={"user_id": "new", "data": "new"},
    )])
    clock[0] = 129.0
    assert catalog.list_knowledge_catalog(knowledge_store, "new")["count"] == 0
    clock[0] = 130.0
    assert catalog.list_knowledge_catalog(knowledge_store, "new")["count"] == 1


def test_catalog_refresh_bypasses_unexpired_cache(knowledge_store, monkeypatch):
    monkeypatch.setattr(catalog.time, "monotonic", lambda: 100.0)
    catalog.list_knowledge_catalog(knowledge_store)
    knowledge_store.vector_store.client.upsert("knowledge", points=[models.PointStruct(
        id=300, vector=[1.0, 0.0], payload={"user_id": "new", "data": "new"},
    )])
    assert catalog.list_knowledge_catalog(knowledge_store, "new")["count"] == 0
    assert catalog.list_knowledge_catalog(knowledge_store, "new", refresh=True)["count"] == 1


def test_catalog_reads_current_bindings_while_entry_counts_are_cached(knowledge_store, monkeypatch):
    monkeypatch.setattr(catalog.time, "monotonic", lambda: 100.0)
    catalog.list_knowledge_catalog(knowledge_store)
    knowledge_store.vector_store.client.upsert("knowledge", points=[models.PointStruct(
        id=300, vector=[1.0, 0.0], payload={"user_id": "new", "data": "new"},
    )])
    bind_character_knowledge("A", "empty")
    assert catalog.list_knowledge_catalog(knowledge_store, "empty")["knowledge"] == [
        {"knowledge_id": "empty", "entryCount": 0, "characterCount": 1},
    ]
    assert catalog.list_knowledge_catalog(knowledge_store, "new")["count"] == 0


def test_failed_catalog_refresh_does_not_publish_partial_scan(knowledge_store, monkeypatch):
    expected = catalog.list_knowledge_catalog(knowledge_store)
    original_scroll = catalog.scroll_knowledge_records

    def fail_second_page(store, **kwargs):
        if kwargs["cursor"] is not None:
            raise RuntimeError("scan interrupted")
        return original_scroll(store, **kwargs)

    monkeypatch.setattr(catalog, "scroll_knowledge_records", fail_second_page)
    with pytest.raises(RuntimeError, match="scan interrupted"):
        catalog.list_knowledge_catalog(knowledge_store, refresh=True)
    assert catalog.list_knowledge_catalog(knowledge_store) == expected


@pytest.mark.parametrize("query", ["alp", "ALP", "  alp  "])
def test_catalog_normalizes_id_query(knowledge_store, query):
    result = catalog.list_knowledge_catalog(knowledge_store, query)
    assert result["count"] == 1
    assert result["knowledge"] == [{"knowledge_id": "alpha", "entryCount": 270, "characterCount": 0}]


def test_catalog_does_not_match_entry_contents(knowledge_store):
    result = catalog.list_knowledge_catalog(knowledge_store, "entry-269")
    assert result["count"] == 0
    assert result["knowledge"] == []
