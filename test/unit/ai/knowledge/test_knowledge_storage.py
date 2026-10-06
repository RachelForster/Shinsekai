from types import SimpleNamespace

import pytest

from ai.knowledge.storage import format_knowledge_entry, list_store_entries, search_store_entries


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
    assert list_store_entries(store, "alpha", 200) == [
        {"id": "1", "memory": "setting"},
    ]
    assert calls == [({"user_id": "alpha"}, 200)]


@pytest.mark.parametrize("wrapped", [False, True])
def test_entry_list_returns_empty_results(wrapped):
    def get_all(*, filters, limit):
        return {"results": []} if wrapped else []

    store = SimpleNamespace(get_all=get_all)
    assert list_store_entries(store, "empty", 5) == []


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


@pytest.mark.parametrize("parameter", ["limit", "top_k"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_entry_search_adapts_mem0_without_losing_fields(parameter, wrapped):
    calls = []
    rows = [{"id": "1", "memory": "setting", "score": 0.8}]

    def result(query, filters, count):
        calls.append((query, filters, count))
        return {"results": rows} if wrapped else rows

    def legacy(query, *, filters, limit):
        return result(query, filters, limit)

    def current(query, *, filters, top_k):
        return result(query, filters, top_k)

    store = SimpleNamespace(search=current if parameter == "top_k" else legacy)
    assert search_store_entries(store, "test", "alpha", 5) == rows
    assert calls == [("test", {"user_id": "alpha"}, 5)]
