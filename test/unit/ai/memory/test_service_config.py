from __future__ import annotations

from pathlib import Path

from ai.memory import config as memory_config


class _FakeConfigManager:
    def get_llm_api_config(self):
        return ("ChatGPT", "gpt-4o-mini", "", "test-key")


def test_mem0_uses_local_multilingual_embedding(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(memory_config, "ConfigManager", _FakeConfigManager)

    config = memory_config.build_mem0_config()

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
        / "hub"
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    )
    snapshot = model_dir / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(b"model")
    monkeypatch.setenv("HF_HOME", str(cache_home))

    assert memory_config.is_embedding_model_cached() is True


def test_embedding_model_cache_detection_uses_hub_cache_env(monkeypatch, tmp_path):
    hub_cache = tmp_path / "hub-cache"
    model_dir = (
        hub_cache
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    )
    snapshot = model_dir / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / "config_sentence_transformers.json").write_text("{}", encoding="utf-8")
    (snapshot / "pytorch_model.bin").write_bytes(b"model")
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.is_embedding_model_cached() is True


def test_embedding_model_cache_detection_ignores_incomplete_cache(monkeypatch, tmp_path):
    hub_cache = tmp_path / "hub-cache"
    empty_home = tmp_path / "hf-home"
    model_dir = (
        hub_cache
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    )
    (model_dir / "refs").mkdir(parents=True)
    monkeypatch.setenv("HF_HOME", str(empty_home))
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)

    assert memory_config.is_embedding_model_cached() is False


def test_embedding_model_cache_detection_ignores_onnx_only_cache(monkeypatch, tmp_path):
    hub_cache = tmp_path / "hub-cache"
    empty_home = tmp_path / "hf-home"
    snapshot = (
        hub_cache
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
        / "snapshots"
        / "abc123"
    )
    (snapshot / "onnx").mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "onnx" / "model_qint8_avx512.onnx").write_bytes(b"model")
    monkeypatch.setenv("HF_HOME", str(empty_home))
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)

    assert memory_config.is_embedding_model_cached() is False
