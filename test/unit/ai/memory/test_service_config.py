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


def _symlink_or_skip(link_path: Path, target_path: Path, *, target_is_directory: bool = False) -> None:
    try:
        link_path.symlink_to(target_path, target_is_directory=target_is_directory)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Symlink privilege not enabled on this Windows environment")
        raise


def _write_hf_blob_symlinked_snapshot(model_dir: Path, revision: str = "abc123") -> Path:
    """Create a standard Hugging Face Hub cache using relative symlinks into ../blobs/."""
    blobs_dir = model_dir / "blobs"
    blobs_dir.mkdir(parents=True, exist_ok=True)
    snapshot = model_dir / "snapshots" / revision
    (snapshot / "onnx").mkdir(parents=True, exist_ok=True)

    blob_cfg = blobs_dir / "sha256-config"
    blob_cfg.write_text(
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
    blob_tok_cfg = blobs_dir / "sha256-tok-config"
    blob_tok_cfg.write_text(
        json.dumps(
            {
                "model_max_length": 512,
                "tokenizer_class": "XLMRobertaTokenizer",
            }
        ),
        encoding="utf-8",
    )
    blob_tok = blobs_dir / "sha256-tokenizer"
    blob_tok.write_text(
        json.dumps(
            {
                "model": {"type": "Unigram", "vocab": [["<s>", 0.0], ["token", -1.0]]},
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    blob_onnx = blobs_dir / "sha256-onnx-quantized"
    blob_onnx.write_bytes(b"\x08\x07\x12\x0cshinsekai-ut" + b"\x00" * 32)

    _symlink_or_skip(snapshot / "config.json", Path("../../blobs/sha256-config"))
    _symlink_or_skip(snapshot / "tokenizer_config.json", Path("../../blobs/sha256-tok-config"))
    _symlink_or_skip(snapshot / "tokenizer.json", Path("../../blobs/sha256-tokenizer"))
    _symlink_or_skip(
        snapshot / "onnx" / "model_quantized.onnx",
        Path("../../../blobs/sha256-onnx-quantized"),
    )

    refs = model_dir / "refs"
    refs.mkdir(exist_ok=True)
    (refs / "main").write_text(revision, encoding="utf-8")
    return snapshot


def test_onnx_snapshot_validation_accepts_regular_files_and_hf_blob_symlinks(
    monkeypatch,
    tmp_path,
):
    from ai.memory.backends.onnx_embedder import find_onnx_model_file

    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    # 1. Plain regular-file snapshot
    plain_snapshot = tmp_path / "plain-local-model"
    _write_complete_embedding_snapshot(plain_snapshot)
    assert memory_config._validate_onnx_embedding_snapshot(plain_snapshot) is True
    assert find_onnx_model_file(plain_snapshot) == plain_snapshot / "onnx" / "model_quantized.onnx"

    # 2. Standard Hugging Face Hub cache with relative symlinks into same-repo blobs/
    model_dir = hub_cache / _MODEL_HUB_DIR_NAME
    hf_snapshot = _write_hf_blob_symlinked_snapshot(model_dir, revision="rev-hf-blobs")
    assert (hf_snapshot / "onnx" / "model_quantized.onnx").is_symlink() is True
    assert memory_config._validate_onnx_embedding_snapshot(hf_snapshot) is True
    assert memory_config.embedding_model_snapshot_path() == hf_snapshot
    assert memory_config.is_embedding_model_cached() is True
    assert find_onnx_model_file(hf_snapshot) == hf_snapshot / "onnx" / "model_quantized.onnx"


def test_onnx_snapshot_validation_rejects_out_of_bounds_symlinks(
    monkeypatch,
    tmp_path,
):
    from ai.memory.backends.onnx_embedder import find_onnx_model_file

    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    outside_dir = tmp_path / "outside-secrets"
    outside_dir.mkdir()
    outside_onnx = outside_dir / "external.onnx"
    outside_onnx.write_bytes(b"\x08\x07\x12\x0cshinsekai-ut" + b"\x00" * 32)
    other_repo_blob = hub_cache / "models--other--repo" / "blobs" / "sha256-other"
    other_repo_blob.parent.mkdir(parents=True)
    other_repo_blob.write_bytes(b"\x08\x07\x12\x0cshinsekai-ut" + b"\x00" * 32)

    model_dir = hub_cache / _MODEL_HUB_DIR_NAME
    snapshot = _write_hf_blob_symlinked_snapshot(model_dir, revision="rev-escape")

    # 1. Symlink escaping completely outside hub cache -> rejected
    onnx_link = snapshot / "onnx" / "model_quantized.onnx"
    onnx_link.unlink()
    _symlink_or_skip(onnx_link, outside_onnx)
    assert memory_config.resolve_safe_snapshot_file(snapshot, "onnx/model_quantized.onnx") is None
    assert memory_config._validate_onnx_embedding_snapshot(snapshot) is False
    assert memory_config.embedding_model_snapshot_path() is None
    assert find_onnx_model_file(snapshot) is None

    # 2. Symlink pointing into a DIFFERENT Hugging Face repo's blobs/ -> rejected
    onnx_link.unlink()
    _symlink_or_skip(onnx_link, other_repo_blob)
    assert memory_config.resolve_safe_snapshot_file(snapshot, "onnx/model_quantized.onnx") is None
    assert memory_config._validate_onnx_embedding_snapshot(snapshot) is False

    # 3. Restore valid ONNX link, but replace repo's blobs/ directory itself with an external symlink -> rejected
    onnx_link.unlink()
    _symlink_or_skip(onnx_link, Path("../../../blobs/sha256-onnx-quantized"))
    assert memory_config._validate_onnx_embedding_snapshot(snapshot) is True

    real_blobs = model_dir / "blobs"
    moved_blobs = tmp_path / "hijacked-blobs"
    real_blobs.rename(moved_blobs)
    _symlink_or_skip(real_blobs, moved_blobs, target_is_directory=True)
    assert memory_config.resolve_safe_snapshot_file(snapshot, "onnx/model_quantized.onnx") is None
    assert memory_config._validate_onnx_embedding_snapshot(snapshot) is False
