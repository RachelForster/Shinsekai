from __future__ import annotations

import os
from pathlib import Path

import pytest

from ai.memory import config as memory_config


class _FakeConfigManager:
    def get_llm_api_config(self):
        return ("ChatGPT", "gpt-4o-mini", "", "test-key")


def _isolate_embedding_cache_roots(monkeypatch, tmp_path: Path) -> None:
    """Keep cache-detection tests independent from developer machine state."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "empty-hf-home"))
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)


def _write_complete_embedding_snapshot(
    snapshot: Path,
    *,
    weight_name: str = "model.safetensors",
) -> None:
    snapshot.mkdir(parents=True, exist_ok=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "modules.json").write_text(
        """[
  {"name": "0", "path": "", "type": "sentence_transformers.models.Transformer"},
  {"name": "1", "path": "1_Pooling", "type": "sentence_transformers.models.Pooling"}
]""",
        encoding="utf-8",
    )
    pooling_dir = snapshot / "1_Pooling"
    pooling_dir.mkdir(exist_ok=True)
    (pooling_dir / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")
    (snapshot / weight_name).write_bytes(b"model")


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
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    cache_home = tmp_path / "hf"
    model_dir = (
        cache_home
        / "hub"
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    )
    snapshot = model_dir / "snapshots" / "abc123"
    _write_complete_embedding_snapshot(snapshot)
    monkeypatch.setenv("HF_HOME", str(cache_home))

    assert memory_config.is_embedding_model_cached() is True


def test_embedding_model_cache_detection_uses_hub_cache_env(monkeypatch, tmp_path):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    model_dir = (
        hub_cache
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    )
    snapshot = model_dir / "snapshots" / "abc123"
    _write_complete_embedding_snapshot(snapshot, weight_name="pytorch_model.bin")
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.is_embedding_model_cached() is True


def test_embedding_model_snapshot_path_prefers_main_ref(monkeypatch, tmp_path):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    model_dir = (
        hub_cache
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    )
    for revision in ("old123", "current456"):
        snapshot = model_dir / "snapshots" / revision
        _write_complete_embedding_snapshot(snapshot)
    refs = model_dir / "refs"
    refs.mkdir()
    (refs / "main").write_text("current456\n", encoding="utf-8")
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.embedding_model_snapshot_path() == model_dir / "snapshots" / "current456"


@pytest.mark.skipif(os.name != "nt", reason="Windows verbatim paths are Windows-specific")
def test_embedding_model_snapshot_path_preserves_windows_verbatim_root(monkeypatch, tmp_path):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = Path("\\\\?\\" + str(tmp_path / ("deep-cache-" + "x" * 80)))
    snapshot = (
        hub_cache
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
        / "snapshots"
        / "abc123"
    )
    _write_complete_embedding_snapshot(snapshot)
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    result = memory_config.embedding_model_snapshot_path()

    assert result == snapshot
    assert str(result).startswith("\\\\?\\")


def test_embedding_model_cache_detection_rejects_config_and_weights_only(monkeypatch, tmp_path):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    snapshot = (
        hub_cache
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
        / "snapshots"
        / "abc123"
    )
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(b"model")
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.embedding_model_snapshot_path() is None
    assert memory_config.is_embedding_model_cached() is False


@pytest.mark.parametrize(
    "missing_file",
    (
        "modules.json",
        "1_Pooling/config.json",
        "tokenizer_config.json",
        "tokenizer.json",
    ),
)
def test_embedding_model_cache_detection_rejects_missing_sentence_transformer_artifact(
    monkeypatch,
    tmp_path,
    missing_file,
):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    snapshot = (
        hub_cache
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
        / "snapshots"
        / "abc123"
    )
    _write_complete_embedding_snapshot(snapshot)
    (snapshot / missing_file).unlink()
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.embedding_model_snapshot_path() is None
    assert memory_config.is_embedding_model_cached() is False


def test_embedding_model_cache_detection_ignores_incomplete_cache(monkeypatch, tmp_path):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    model_dir = (
        hub_cache
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    )
    (model_dir / "refs").mkdir(parents=True)
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.is_embedding_model_cached() is False


def test_embedding_model_cache_detection_ignores_onnx_only_cache(monkeypatch, tmp_path):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    snapshot = (
        hub_cache
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
        / "snapshots"
        / "abc123"
    )
    (snapshot / "onnx").mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "onnx" / "model_qint8_avx512.onnx").write_bytes(b"model")
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.is_embedding_model_cached() is False
