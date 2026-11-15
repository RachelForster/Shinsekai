from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import sys

import numpy as np
import pytest

from ai.memory import config as memory_config


def _pb_varint(val: int) -> bytes:
    if val < 0:
        val += 1 << 64
    out = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _pb_f_varint(field: int, val: int) -> bytes:
    return _pb_varint((field << 3) | 0) + _pb_varint(val)


def _pb_f_bytes(field: int, data: bytes) -> bytes:
    return _pb_varint((field << 3) | 2) + _pb_varint(len(data)) + data


def _pb_f_str(field: int, text: str) -> bytes:
    return _pb_f_bytes(field, text.encode("utf-8"))


def _pb_dim(val: int | str) -> bytes:
    if isinstance(val, str):
        return _pb_f_str(2, val)
    return _pb_f_varint(1, val)


def _pb_value_info(name: str, elem_type: int, dims: list[int | str]) -> bytes:
    shape = b"".join(_pb_f_bytes(1, _pb_dim(d)) for d in dims)
    tensor_type = _pb_f_varint(1, elem_type) + _pb_f_bytes(2, shape)
    return _pb_f_str(1, name) + _pb_f_bytes(2, _pb_f_bytes(1, tensor_type))


def _pb_tensor_init(name: str, elem_type: int, dims: list[int], raw_data: bytes) -> bytes:
    out = b"".join(_pb_f_varint(1, d) for d in dims)
    out += _pb_f_varint(2, elem_type)
    out += _pb_f_str(8, name)
    out += _pb_f_bytes(9, raw_data)
    return out


def _pb_node(op_type: str, inputs: list[str], outputs: list[str], *, attrs: bytes = b"") -> bytes:
    out = b"".join(_pb_f_str(1, i) for i in inputs)
    out += b"".join(_pb_f_str(2, o) for o in outputs)
    out += _pb_f_str(4, op_type)
    out += attrs
    return out


def _pb_attr_int(name: str, val: int) -> bytes:
    return _pb_f_bytes(5, _pb_f_str(1, name) + _pb_f_varint(3, val) + _pb_f_varint(20, 2))


def build_valid_minilm_onnx_bytes(
    dims: int = 384,
    *,
    input_id_name: str = "input_ids",
) -> bytes:
    """Build a minimal executable ONNX ModelProto matching MiniLM's I/O contract."""
    float_t, int64_t = 1, 7
    table = ((np.arange(8 * dims, dtype=np.float32).reshape(8, dims) % 11) + 1.0) * 0.05
    inits = [
        _pb_tensor_init("emb_table", float_t, [8, dims], table.tobytes()),
        _pb_tensor_init("zero_i64", int64_t, [], struct.pack("<q", 0)),
        _pb_tensor_init("max_i64", int64_t, [], struct.pack("<q", 7)),
        _pb_tensor_init("unsq_axes", int64_t, [1], struct.pack("<q", 2)),
    ]
    nodes = [
        _pb_node("Clip", [input_id_name, "zero_i64", "max_i64"], ["clipped_ids"]),
        _pb_node("Gather", ["emb_table", "clipped_ids"], ["gathered"], attrs=_pb_attr_int("axis", 0)),
        _pb_node("Cast", ["attention_mask"], ["mask_f32"], attrs=_pb_attr_int("to", float_t)),
        _pb_node("Unsqueeze", ["mask_3d_src" if False else "mask_f32", "unsq_axes"], ["mask_3d"]),
        _pb_node("Mul", ["gathered", "mask_3d"], ["last_hidden_state"]),
    ]
    graph = (
        b"".join(_pb_f_bytes(1, n) for n in nodes)
        + _pb_f_str(2, "shinsekai_minilm_ut")
        + b"".join(_pb_f_bytes(5, t) for t in inits)
        + _pb_f_bytes(11, _pb_value_info(input_id_name, int64_t, ["batch", "seq"]))
        + _pb_f_bytes(11, _pb_value_info("attention_mask", int64_t, ["batch", "seq"]))
        + _pb_f_bytes(12, _pb_value_info("last_hidden_state", float_t, ["batch", "seq", dims]))
    )
    opset = _pb_f_str(1, "") + _pb_f_varint(2, 13)
    return _pb_f_varint(1, 7) + _pb_f_bytes(7, graph) + _pb_f_bytes(8, opset)


_VALID_ONNX_384_BYTES = build_valid_minilm_onnx_bytes(384)

_VALID_UNIGRAM_TOKENIZER_JSON = json.dumps(
    {
        "version": "1.0",
        "truncation": None,
        "padding": None,
        "added_tokens": [],
        "normalizer": None,
        "pre_tokenizer": None,
        "post_processor": None,
        "decoder": None,
        "model": {
            "type": "Unigram",
            "unk_id": 3,
            "vocab": [
                ["<s>", 0.0],
                ["<pad>", 0.0],
                ["</s>", 0.0],
                ["<unk>", 0.0],
                ["\u2581hello", -1.0],
                ["hello", -1.0],
                ["\u2581world", -1.2],
                ["world", -1.2],
                ["\u2581\u5e0c\u671b", -1.5],
                ["\u5e0c\u671b", -1.5],
                [" ", -0.5],
                ["\u2581", -0.5],
            ],
            "byte_fallback": False,
        },
    }
)


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
        _VALID_UNIGRAM_TOKENIZER_JSON,
        encoding="utf-8",
    )
    onnx_dir = snapshot / "onnx"
    onnx_dir.mkdir(exist_ok=True)
    (onnx_dir / "model_quantized.onnx").write_bytes(_VALID_ONNX_384_BYTES)
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
        _VALID_UNIGRAM_TOKENIZER_JSON,
        encoding="utf-8",
    )
    blob_onnx = blobs_dir / "sha256-onnx-quantized"
    blob_onnx.write_bytes(_VALID_ONNX_384_BYTES)

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
    outside_onnx.write_bytes(_VALID_ONNX_384_BYTES)
    other_repo_blob = hub_cache / "models--other--repo" / "blobs" / "sha256-other"
    other_repo_blob.parent.mkdir(parents=True)
    other_repo_blob.write_bytes(_VALID_ONNX_384_BYTES)

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


def test_onnx_validation_rejects_0x08_header_truncated_bit_corrupted_and_incompatible_graphs(
    monkeypatch,
    tmp_path,
):
    from ai.memory.backends.onnx_embedder import find_onnx_model_file

    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))
    snapshot = hub_cache / _MODEL_HUB_DIR_NAME / "snapshots" / "rev-validate"
    _write_complete_embedding_snapshot(snapshot)
    onnx_file = snapshot / "onnx" / "model_quantized.onnx"

    # Corrupt a node op_type to same-length unknown op while keeping protobuf framing + 0x08 header intact
    assert b"Gather" in _VALID_ONNX_384_BYTES
    broken_op_bytes = _VALID_ONNX_384_BYTES.replace(b"Gather", b"ZzNoOp", 1)

    # Corrupt initializer weights with NaN (valid protobuf framing, rejected by tensor NaN + ORT checks)
    nan_weight_bytes = bytearray(_VALID_ONNX_384_BYTES)
    raw_header = b"emb_table" + _pb_varint((9 << 3) | 2) + _pb_varint(8 * 384 * 4)
    raw_data_pos = nan_weight_bytes.index(raw_header) + len(raw_header)
    nan_weight_bytes[raw_data_pos : raw_data_pos + 16] = struct.pack(
        "<ffff", float("nan"), 0.0, 0.0, 0.0
    )

    # Bit-corrupt protobuf wire tag near the end while keeping byte 0 == 0x08 and exact file size
    wire_corrupted_bytes = bytearray(_VALID_ONNX_384_BYTES)
    wire_corrupted_bytes[-12:] = b"\xff" * 12

    invalid_payloads: list[tuple[str, bytes, bool]] = [
        ("minimal_0x08_zeroes", b"\x08" + b"\x00" * 64, True),
        ("fake_header_0x08", b"\x08\x07\x12\x0cshinsekai-ut" + b"\x00" * 32, True),
        ("truncated_half", _VALID_ONNX_384_BYTES[: len(_VALID_ONNX_384_BYTES) // 2], True),
        ("truncated_tail_5b", _VALID_ONNX_384_BYTES[:-5], True),
        ("same_size_wire_corrupt", bytes(wire_corrupted_bytes), True),
        ("wrong_output_dims_768", build_valid_minilm_onnx_bytes(768), True),
        ("missing_input_ids", build_valid_minilm_onnx_bytes(384, input_id_name="tokens"), True),
        ("nan_initializer_weights", bytes(nan_weight_bytes), True),
        ("unknown_onnx_operator", broken_op_bytes, False),
    ]

    for case_name, payload, structural_reject in invalid_payloads:
        assert len(payload) > 16 and payload[0] == 0x08, case_name
        onnx_file.write_bytes(payload)
        assert memory_config.validate_onnx_model_file(onnx_file) is False, case_name
        assert memory_config._validate_onnx_embedding_snapshot(snapshot) is False, case_name
        assert memory_config.embedding_model_snapshot_path() is None, case_name
        assert find_onnx_model_file(snapshot) is None, case_name

        if structural_reject:
            with monkeypatch.context() as mp:
                mp.setitem(sys.modules, "onnxruntime", None)
                assert memory_config.validate_onnx_model_file(onnx_file) is False, (
                    f"Layer-1 structural check should reject {case_name} even without onnxruntime"
                )

    # Restoring the valid ONNX graph immediately restores validation
    onnx_file.write_bytes(_VALID_ONNX_384_BYTES)
    assert memory_config.validate_onnx_model_file(onnx_file) is True
    assert memory_config._validate_onnx_embedding_snapshot(snapshot) is True
    assert memory_config.embedding_model_snapshot_path() == snapshot
    assert find_onnx_model_file(snapshot) == onnx_file


def test_download_model_asset_auto_repairs_corrupt_0x08_onnx_and_embedder_succeeds(
    monkeypatch,
    tmp_path,
):
    from ai.memory.backends.onnx_embedder import OnnxMiniLmEmbedder
    from core.model_assets import service as asset_service

    _isolate_embedding_cache_roots(monkeypatch, tmp_path)
    hub_cache = tmp_path / "hub-cache"
    monkeypatch.setenv("HF_HUB_CACHE", str(hub_cache))

    model_dir = hub_cache / _MODEL_HUB_DIR_NAME
    corrupt_snapshot = model_dir / "snapshots" / "rev-corrupt-1"
    _write_complete_embedding_snapshot(corrupt_snapshot)

    # Simulate an interrupted or bit-corrupted download >16 bytes starting with 0x08
    corrupt_bytes = b"\x08\x07" + _VALID_ONNX_384_BYTES[2:96] + b"\xff\x00" * 40
    assert len(corrupt_bytes) > 16 and corrupt_bytes[0] == 0x08
    (corrupt_snapshot / "onnx" / "model_quantized.onnx").write_bytes(corrupt_bytes)

    # Must NOT be treated as cached, and OnnxMiniLmEmbedder cannot load it
    inspected = asset_service.inspect_model_asset(memory_config.EMBEDDING_MODEL_ASSET)
    assert inspected["cached"] is False
    assert memory_config.is_embedding_model_cached() is False
    with pytest.raises(Exception):
        OnnxMiniLmEmbedder(corrupt_snapshot)

    download_calls: list[dict[str, object]] = []

    def _fake_preload(repo_id: str, **kwargs):
        # Verify the corrupt snapshot was wiped before network download and force_download=True was set
        download_calls.append(
            {
                "repo_id": repo_id,
                "cached": kwargs.get("cached"),
                "force_download": kwargs.get("force_download"),
                "corrupt_snapshot_existed": corrupt_snapshot.exists(),
            }
        )
        repaired_snapshot = model_dir / "snapshots" / "rev-corrupt-1"
        _write_complete_embedding_snapshot(repaired_snapshot)
        return str(repaired_snapshot)

    monkeypatch.setattr(asset_service, "preload_huggingface_snapshot", _fake_preload)

    repaired = asset_service.download_model_asset(
        memory_config.EMBEDDING_MODEL_ASSET,
        update_task=lambda **_kw: None,
    )

    assert len(download_calls) == 1
    assert download_calls[0]["cached"] is False
    assert download_calls[0]["force_download"] is True
    assert download_calls[0]["corrupt_snapshot_existed"] is False
    assert repaired["cached"] is True
    assert repaired["downloaded"] is True
    assert memory_config.is_embedding_model_cached() is True

    embedder = OnnxMiniLmEmbedder(repaired["path"])
    vec = embedder.embed_query("hello world")
    assert vec.shape == (384,)
    assert np.isfinite(vec).all()
    assert np.isclose(np.linalg.norm(vec), 1.0, atol=1e-5)
