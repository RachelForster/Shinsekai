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
