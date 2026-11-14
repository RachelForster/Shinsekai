from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ai.memory import config as memory_config


class _FakeConfigManager:
    def get_llm_api_config(self):
        return ("ChatGPT", "gpt-4o-mini", "", "test-key")


_MODEL_HUB_DIR_NAME = "models--Xenova--paraphrase-multilingual-MiniLM-L12-v2"


def test_embedding_model_asset_download_covers_every_required_group():
    allow_patterns = set(memory_config.EMBEDDING_MODEL_ASSET.allow_patterns)

    assert all(
        any(pattern in allow_patterns for pattern in alternatives)
        for alternatives in memory_config.EMBEDDING_MODEL_ASSET.required_file_groups
    )


def _isolate_embedding_cache_roots(monkeypatch, tmp_path: Path) -> None:
    """Keep cache-detection tests independent from developer machine state."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "empty-hf-home"))
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HUGGINGFACE_HUB_CACHE", raising=False)


def _write_complete_embedding_snapshot(snapshot: Path) -> None:
    snapshot.mkdir(parents=True, exist_ok=True)
    (snapshot / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["BertModel"],
                "hidden_size": 384,
                "model_type": "bert",
                "vocab_size": 250037,
            }
        ),
        encoding="utf-8",
    )
    (snapshot / "tokenizer_config.json").write_text(
        json.dumps(
            {
                "model_max_length": 512,
                "tokenizer_class": "XLMRobertaTokenizer",
            }
        ),
        encoding="utf-8",
    )
    (snapshot / "tokenizer.json").write_text(
        json.dumps(
            {
                "model": {"type": "Unigram", "vocab": [["<s>", 0.0], ["token", -1.0]]},
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    onnx_dir = snapshot / "onnx"
    onnx_dir.mkdir(exist_ok=True)
    # Valid ONNX ModelProto field-1 varint header (0x08) + payload bytes
    (onnx_dir / "model_quantized.onnx").write_bytes(b"\x08\x07\x12\x0cshinsekai-ut" + b"\x00" * 32)
    refs = snapshot.parent.parent / "refs"
    refs.mkdir(exist_ok=True)
    (refs / "main").write_text(snapshot.name, encoding="utf-8")


def test_memory_engine_uses_local_onnx_multilingual_embedding(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(memory_config, "ConfigManager", _FakeConfigManager)

    config = memory_config.build_mem0_config()

    assert config["embedder"]["provider"] == "onnxruntime"
    assert (
        config["embedder"]["config"]["model"]
        == "Xenova/paraphrase-multilingual-MiniLM-L12-v2"
    )
    assert config["embedder"]["config"]["embedding_dims"] == 384
    assert config["vector_store"]["provider"] == "sqlite_hybrid"
    assert config["vector_store"]["config"]["embedding_model_dims"] == 384
    assert (
        config["vector_store"]["config"]["collection_name"]
        == "character_memories_multilingual_minilm"
    )
    assert config["vector_store"]["config"]["path"] == (
        tmp_path / "data" / "memory" / "shinsekai_store.db"
    ).as_posix()


def test_embedding_model_cache_detection_uses_multilingual_onnx_model(monkeypatch, tmp_path):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    cache_home = tmp_path / "hf"
    model_dir = cache_home / "hub" / _MODEL_HUB_DIR_NAME
    snapshot = model_dir / "snapshots" / "abc123"
    _write_complete_embedding_snapshot(snapshot)
    monkeypatch.setenv("HF_HOME", str(cache_home))

    assert memory_config.is_embedding_model_cached() is True


def test_embedding_model_cache_detection_uses_hub_cache_env(monkeypatch, tmp_path):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    model_dir = hub_cache / _MODEL_HUB_DIR_NAME
    snapshot = model_dir / "snapshots" / "abc123"
    _write_complete_embedding_snapshot(snapshot)
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.is_embedding_model_cached() is True


def test_embedding_model_snapshot_path_prefers_main_ref(monkeypatch, tmp_path):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    model_dir = hub_cache / _MODEL_HUB_DIR_NAME
    for revision in ("old123", "current456"):
        snapshot = model_dir / "snapshots" / revision
        _write_complete_embedding_snapshot(snapshot)
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.embedding_model_snapshot_path() == model_dir / "snapshots" / "current456"


@pytest.mark.skipif(os.name != "nt", reason="Windows verbatim paths are Windows-specific")
def test_embedding_model_snapshot_path_preserves_windows_verbatim_root(monkeypatch, tmp_path):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = Path("\\\\?\\" + str(tmp_path / ("deep-cache-" + "x" * 80)))
    snapshot = hub_cache / _MODEL_HUB_DIR_NAME / "snapshots" / "abc123"
    _write_complete_embedding_snapshot(snapshot)
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    result = memory_config.embedding_model_snapshot_path()

    assert result == snapshot
    assert str(result).startswith("\\\\?\\")


def test_embedding_model_cache_detection_rejects_config_and_weights_only(monkeypatch, tmp_path):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    snapshot = hub_cache / _MODEL_HUB_DIR_NAME / "snapshots" / "abc123"
    (snapshot / "onnx").mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "onnx" / "model_quantized.onnx").write_bytes(b"\x08" + b"\x00" * 31)
    refs = snapshot.parent.parent / "refs"
    refs.mkdir()
    (refs / "main").write_text(snapshot.name, encoding="utf-8")
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.embedding_model_snapshot_path() is None
    assert memory_config.is_embedding_model_cached() is False


@pytest.mark.parametrize(
    ("relative_path", "content"),
    (
        ("config.json", "[]"),
        ("tokenizer_config.json", "[]"),
        ("tokenizer.json", "not-json"),
    ),
)
def test_embedding_model_cache_detection_rejects_invalid_structured_files(
    monkeypatch,
    tmp_path,
    relative_path,
    content,
):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    snapshot = hub_cache / _MODEL_HUB_DIR_NAME / "snapshots" / "abc123"
    _write_complete_embedding_snapshot(snapshot)
    (snapshot / relative_path).write_text(content, encoding="utf-8")
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.embedding_model_snapshot_path() is None


def test_embedding_model_cache_detection_rejects_corrupt_onnx_graph(monkeypatch, tmp_path):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    snapshot = hub_cache / _MODEL_HUB_DIR_NAME / "snapshots" / "abc123"
    _write_complete_embedding_snapshot(snapshot)
    (snapshot / "onnx" / "model_quantized.onnx").write_bytes(b"truncated")
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.embedding_model_snapshot_path() is None


@pytest.mark.parametrize(
    ("relative_path", "mutate"),
    (
        ("config.json", lambda value: {**value, "hidden_size": 0}),
        ("config.json", lambda value: {**value, "hidden_size": 768}),
        ("tokenizer.json", lambda value: {**value, "model": {}}),
    ),
)
def test_embedding_model_cache_detection_rejects_invalid_model_structure(
    monkeypatch,
    tmp_path,
    relative_path,
    mutate,
):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    snapshot = hub_cache / _MODEL_HUB_DIR_NAME / "snapshots" / "abc123"
    _write_complete_embedding_snapshot(snapshot)
    path = snapshot / relative_path
    path.write_text(json.dumps(mutate(json.loads(path.read_text(encoding="utf-8")))), encoding="utf-8")
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.embedding_model_snapshot_path() is None


@pytest.mark.parametrize(
    "missing_file",
    (
        "tokenizer_config.json",
        "tokenizer.json",
        "onnx/model_quantized.onnx",
    ),
)
def test_embedding_model_cache_detection_rejects_missing_required_artifact(
    monkeypatch,
    tmp_path,
    missing_file,
):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    snapshot = hub_cache / _MODEL_HUB_DIR_NAME / "snapshots" / "abc123"
    _write_complete_embedding_snapshot(snapshot)
    (snapshot / missing_file).unlink()
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.embedding_model_snapshot_path() is None
    assert memory_config.is_embedding_model_cached() is False


def test_embedding_model_cache_detection_ignores_incomplete_cache(monkeypatch, tmp_path):
    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    model_dir = hub_cache / _MODEL_HUB_DIR_NAME
    (model_dir / "refs").mkdir(parents=True)
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    assert memory_config.is_embedding_model_cached() is False
