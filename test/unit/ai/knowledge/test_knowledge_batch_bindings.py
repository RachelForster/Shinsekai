import sqlite3

import pytest

from ai.knowledge import bindings


def test_batch_is_idempotent_and_preserves_other_knowledge_and_unedited_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bindings.batch_knowledge_bindings("a", ["old", "keep"], [])
    bindings.bind_character_knowledge("old", "b")
    for _ in range(2):
        result = bindings.batch_knowledge_bindings("a", [" new ", "new"], ["old"])
        assert result == {"ok": True, "knowledge_id": "a", "characterNames": ["keep", "new"]}
    assert bindings.list_knowledge_binding_names("b")["characterNames"] == ["old"]
    bindings.batch_knowledge_bindings("a", [f"role-{i}" for i in range(120)], [])
    assert len(bindings.list_knowledge_binding_names("a")["characterNames"]) == 122


@pytest.mark.parametrize("add,remove", [("name", []), ([None], []), ([" "], []), (["a"], [" a "])])
def test_invalid_batch_does_not_change_bindings(tmp_path, monkeypatch, add, remove):
    monkeypatch.chdir(tmp_path)
    bindings.bind_character_knowledge("keep", "a")
    with pytest.raises(ValueError):
        bindings.batch_knowledge_bindings("a", add, remove)
    assert bindings.list_knowledge_binding_names("a")["characterNames"] == ["keep"]


def test_batch_rolls_back_removals_if_insert_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bindings.bind_character_knowledge("old", "a")
    with bindings._connect() as connection:
        connection.execute("""CREATE TRIGGER reject_bad BEFORE INSERT ON character_knowledge_bindings
            WHEN NEW.character_name = 'bad' BEGIN SELECT RAISE(ABORT, 'rejected'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        bindings.batch_knowledge_bindings("a", ["bad"], ["old"])
    assert bindings.list_knowledge_binding_names("a")["characterNames"] == ["old"]
