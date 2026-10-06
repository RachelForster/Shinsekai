import sqlite3

import pytest

from ai.knowledge import bindings as b


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "_database_path", lambda: tmp_path / "knowledge.db")


def test_crud_and_reverse_queries():
    b.bind_character_knowledge(" A ", " old ")
    b.bind_character_knowledge("A", "old")
    b.bind_character_knowledge("B", "old")
    assert b.get_knowledge_binding_counts() == {"old": 2}
    assert b.unbind_character_knowledge("A", "old") is True
    b.bind_character_knowledge("A", "new")
    assert b.list_knowledge_ids_for_characters(["A"]) == ["new"]
    assert b.list_knowledge_binding_names("old")["characterNames"] == ["B"]
    result = b.list_character_knowledge_bindings("A")
    assert result["count"] == 1
    assert result["bindings"][0]["knowledge_id"] == "new"
    assert result["bindings"][0]["createdAt"]
    assert b.unbind_character_knowledge("A", "new") is True
    assert b.unbind_character_knowledge("A", "new") is False
    assert b.list_knowledge_ids_for_characters(["B"]) == ["old"]


def test_pagination_and_bulk_deletion_are_scoped():
    for knowledge_id in ["a", "b", "c"]:
        b.bind_character_knowledge("A", knowledge_id)
    b.bind_character_knowledge("B", "a")
    result = b.list_character_knowledge_bindings("A", page=2, page_size=2)
    assert result["count"] == 3
    assert [row["knowledge_id"] for row in result["bindings"]] == ["c"]
    assert b.delete_knowledge_bindings("a") == 2
    assert b.delete_knowledge_bindings("a") == 0
    b.bind_character_knowledge("B", "b")
    b.delete_character_bindings("A")
    assert b.list_knowledge_ids_for_characters(["A"]) == []
    assert b.list_knowledge_ids_for_characters(["B"]) == ["b"]
    b.delete_character_bindings("A")
    assert b.get_knowledge_binding_counts() == {"b": 1}


def test_character_rename_preserves_all_bindings_and_timestamps():
    for knowledge_id in ["a", "b"]:
        b.bind_character_knowledge("Old", knowledge_id)
    b.bind_character_knowledge("Other", "a")
    original = b.list_character_knowledge_bindings("Old")["bindings"]
    b.rename_character_bindings(" Old ", " New ")
    assert b.list_character_knowledge_bindings("New")["bindings"] == original
    assert b.list_knowledge_ids_for_characters(["Old"]) == []
    assert b.list_knowledge_binding_names("a")["characterNames"] == ["New", "Other"]
    b.rename_character_bindings("Old", "New")
    b.rename_character_bindings("New", "New")
    assert b.list_character_knowledge_bindings("New")["bindings"] == original
    assert b.get_knowledge_binding_counts() == {"a": 2, "b": 1}


def test_character_rename_merges_duplicates_and_preserves_earliest_timestamp():
    b.bind_character_knowledge("Old", "a")
    b.bind_character_knowledge("New", "a")
    b.bind_character_knowledge("New", "b")
    with b._connect() as connection:
        connection.execute("UPDATE character_knowledge_bindings SET created_at = '2020-01-01' WHERE character_name = 'Old'")
        connection.execute("UPDATE character_knowledge_bindings SET created_at = '2021-01-01' WHERE character_name = 'New'")
    b.rename_character_bindings("Old", "New")
    assert b.list_knowledge_ids_for_characters(["Old"]) == []
    assert b.list_character_knowledge_bindings("New")["bindings"] == [
        {"knowledge_id": "a", "createdAt": "2020-01-01"},
        {"knowledge_id": "b", "createdAt": "2021-01-01"},
    ]
    assert b.get_knowledge_binding_counts() == {"a": 1, "b": 1}


def test_failed_character_rename_rolls_back_all_changes():
    b.bind_character_knowledge("Old", "a")
    b.bind_character_knowledge("New", "b")
    with b._connect() as connection:
        connection.execute("CREATE TRIGGER fail_rename_delete BEFORE DELETE ON character_knowledge_bindings "
                           "BEGIN SELECT RAISE(ABORT, 'blocked'); END")
    with pytest.raises(sqlite3.IntegrityError, match="blocked"):
        b.rename_character_bindings("Old", "New")
    assert b.list_knowledge_ids_for_characters(["Old"]) == ["a"]
    assert b.list_knowledge_ids_for_characters(["New"]) == ["b"]


@pytest.mark.parametrize("call", [
    lambda: b.bind_character_knowledge("", "w"),
    lambda: b.unbind_character_knowledge("A", " "),
    lambda: b.list_character_knowledge_bindings(""),
    lambda: b.delete_knowledge_bindings(""),
    lambda: b.delete_character_bindings(" "),
    lambda: b.rename_character_bindings("", "New"),
    lambda: b.rename_character_bindings("A", " "),
])
def test_empty_identifiers_never_mean_delete_all(call):
    b.bind_character_knowledge("A", "w")
    with pytest.raises(ValueError):
        call()
    assert b.list_knowledge_ids_for_characters(["A"]) == ["w"]
