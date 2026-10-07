from __future__ import annotations

from pathlib import Path


def test_knowledge_config_uses_isolated_storage_and_collection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "ai.knowledge.config.build_mem0_config",
        lambda: {
            "vector_store": {"provider": "qdrant", "config": {}},
            "embedder": {"provider": "huggingface", "config": {}},
            "history_db_path": "old.db",
        },
    )

    from ai.knowledge.config import build_knowledge_mem0_config

    config = build_knowledge_mem0_config()
    assert config["vector_store"]["config"]["collection_name"] == "character_knowledge_settings_rag_minilm"
    assert config["vector_store"]["config"]["path"] == (tmp_path / "data" / "knowledge" / "qdrant").as_posix()
    assert config["history_db_path"] == str(tmp_path / "data" / "knowledge" / "knowledge_history.db")


def test_bindings_resolve_shared_knowledge_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from ai.knowledge.bindings import bind_character_knowledge, list_knowledge_ids_for_characters

    bind_character_knowledge("Monika", "ddlc")
    bind_character_knowledge("Sayori", "ddlc")
    assert list_knowledge_ids_for_characters(["Monika", "Sayori"]) == ["ddlc"]
    assert (tmp_path / "data" / "knowledge" / "knowledge.db").is_file()


def test_preview_knowledge_import_reuses_memory_txt_parser(tmp_path):
    source = tmp_path / "knowledge.txt"
    source.write_text("第一行\n\n第二行\n", encoding="utf-8")

    from ai.knowledge.imports import preview_knowledge_import

    preview = preview_knowledge_import(
        [source],
        knowledge_id="ddlc",
        source_root=tmp_path,
        max_chunk_tokens=256,
    )
    assert preview["fileCount"] == 1
    assert preview["dialogueLineCount"] == 2
    assert preview["chunkCount"] == 1
