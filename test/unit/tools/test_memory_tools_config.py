from __future__ import annotations

from pathlib import Path

from llm.tools import memory_tools


class _FakeConfigManager:
    def get_llm_api_config(self):
        return ("ChatGPT", "gpt-4o-mini", "", "test-key")


def test_mem0_uses_local_multilingual_embedding(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(memory_tools, "ConfigManager", _FakeConfigManager)

    config = memory_tools._build_mem0_config()

    assert config["embedder"]["provider"] == "huggingface"
    assert (
        config["embedder"]["config"]["model"]
        == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    assert config["embedder"]["config"]["embedding_dims"] == 384
    assert config["vector_store"]["config"]["embedding_model_dims"] == 384
    assert (
        config["vector_store"]["config"]["collection_name"]
        == "character_memories_multilingual_minilm"
    )
    assert config["vector_store"]["config"]["path"] == (
        tmp_path / "data" / "memory" / "qdrant"
    ).as_posix()


def test_embedding_model_cache_detection_uses_multilingual_model(monkeypatch, tmp_path):
    cache_home = tmp_path / "hf"
    model_dir = (
        cache_home
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    )
    model_dir.mkdir(parents=True)
    monkeypatch.setenv("HF_HOME", str(cache_home))

    assert memory_tools._is_embedding_model_cached() is True
