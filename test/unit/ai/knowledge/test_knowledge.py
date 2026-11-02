from __future__ import annotations

from ai.knowledge.config import configure_mem0_environment

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


def test_telemetry_defaults_off_and_preserves_opt_in(monkeypatch):
    monkeypatch.delenv("MEM0_TELEMETRY", raising=False)
    configure_mem0_environment()
    import os
    assert os.environ["MEM0_TELEMETRY"] == "False"
    monkeypatch.setenv("MEM0_TELEMETRY", "True")
    configure_mem0_environment()
    assert os.environ["MEM0_TELEMETRY"] == "True"


def test_instance_creation_uses_prepared_snapshot_and_telemetry(monkeypatch):
    import os
    from types import SimpleNamespace
    from ai.knowledge.config import create_knowledge_mem0

    config = {"embedder": {"config": {}}, "history_db_path": "knowledge.db"}
    store = object()
    monkeypatch.delenv("MEM0_TELEMETRY", raising=False)
    monkeypatch.setattr("ai.knowledge.config.build_knowledge_mem0_config", lambda: config)

    def from_config(actual):
        assert actual is config
        assert actual["embedder"]["config"]["model"] == "cached-snapshot"
        assert actual["history_db_path"] == "knowledge.db"
        assert os.environ["MEM0_TELEMETRY"] == "False"
        return store

    assert create_knowledge_mem0(SimpleNamespace(from_config=from_config), "cached-snapshot") is store
