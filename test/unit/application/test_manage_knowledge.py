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
