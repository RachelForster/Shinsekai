"""Configuration and ONNX asset validation helpers for long-term memory."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import mmap
import os
from pathlib import Path
import threading
from typing import Any

import numpy as np

from config.config_manager import ConfigManager
from config.llm_defaults import extract_llm_api_credentials
from config.models import ApiConfig
from core.model_assets.service import ModelAssetSpec, find_cached_huggingface_snapshot
from core.storage.layout import StorageLayout
from sdk.adapters.storage import ReadableDocument

from ai.memory.constants import (
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    MEMORY_STORE_FILENAME,
    ONNX_MODEL_CANDIDATES,
    VECTOR_COLLECTION,
)

_MIN_ONNX_FILE_BYTES = 16
_ALLOWED_EMBEDDING_INPUT_NAMES = frozenset({"input_ids", "attention_mask", "token_type_ids"})
_FLOAT_TENSOR_ELEM_TYPES = frozenset({1, 10, 11, 16})  # FLOAT, FLOAT16, DOUBLE, BFLOAT16
_TENSOR_ELEM_BYTE_SIZES: dict[int, int] = {
    1: 4,   # FLOAT
    2: 1,   # UINT8
    3: 1,   # INT8
    4: 2,   # UINT16
    5: 2,   # INT16
    6: 4,   # INT32
    7: 8,   # INT64
    9: 1,   # BOOL
    10: 2,  # FLOAT16
    11: 8,  # DOUBLE
    12: 4,  # UINT32
    13: 8,  # UINT64
    14: 8,  # COMPLEX64
    15: 16, # COMPLEX128
    16: 2,  # BFLOAT16
}
_ONNX_VALIDATION_CACHE_LOCK = threading.Lock()
_ONNX_VALIDATION_CACHE: OrderedDict[tuple[Any, ...], bool] = OrderedDict()
_MAX_ONNX_VALIDATION_CACHE_ENTRIES = 32
_FULL_HASH_MAX_BYTES = 4 * 1024 * 1024
_SAMPLE_HASH_CHUNK_BYTES = 64 * 1024


def _read_json_file(path: Path) -> Any | None:
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _is_positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _norm_resolved_path_str(path: Path) -> str:
    text = str(path)
    if os.name == "nt":
        if text.startswith("\\\\?\\UNC\\"):
            text = "\\\\" + text[8:]
        elif text.startswith("\\\\?\\"):
            text = text[4:]
    return os.path.normcase(os.path.normpath(text))


def _is_strictly_within_directory(target: Path, directory: Path) -> bool:
    try:
        target_norm = _norm_resolved_path_str(target)
        dir_norm = _norm_resolved_path_str(directory)
        return (
            target_norm != dir_norm
            and os.path.commonpath([dir_norm, target_norm]) == dir_norm
        )
    except ValueError:
        return False


def resolve_safe_snapshot_file(snapshot: Path, relative_path: str) -> Path | None:
    """Resolve a snapshot file allowing regular in-snapshot files and same-repo HF blob links."""
    normalized = str(relative_path or "").strip().replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        return None
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    try:
        if not snapshot.is_dir():
            return None
        raw_target = snapshot / Path(*parts)
        if not raw_target.is_file():
            return None

        snapshot_resolved = snapshot.resolve(strict=True)
        target_resolved = raw_target.resolve(strict=True)
        if _is_strictly_within_directory(target_resolved, snapshot_resolved):
            return raw_target

        # Standard Hugging Face Hub cache layout: <repo>/snapshots/<rev>/... -> <repo>/blobs/<sha>
        if (
            snapshot.parent.name == "snapshots"
            and snapshot_resolved.parent.name == "snapshots"
        ):
            repo_resolved = snapshot_resolved.parent.parent.resolve(strict=True)
            blobs_dir = repo_resolved / "blobs"
            if blobs_dir.is_dir():
                blobs_resolved = blobs_dir.resolve(strict=True)
                if (
                    _is_strictly_within_directory(blobs_resolved, repo_resolved)
                    and _is_strictly_within_directory(target_resolved, blobs_resolved)
                ):
                    return raw_target
        return None
    except (OSError, ValueError):
        return None


_safe_snapshot_file = resolve_safe_snapshot_file


def _read_snapshot_json_file(snapshot: Path, relative_path: str) -> Any | None:
    safe_path = resolve_safe_snapshot_file(snapshot, relative_path)
    if safe_path is None:
        return None
    return _read_json_file(safe_path)


def _to_signed_int64(val: int) -> int:
    return val - (1 << 64) if val >= (1 << 63) else val


def _read_protobuf_varint(buf: memoryview, pos: int, limit: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while pos < limit and shift < 64:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, pos
        shift += 7
    raise ValueError("Invalid or truncated protobuf varint")


def _iter_protobuf_fields(buf: memoryview, start: int, limit: int):
    pos = start
    while pos < limit:
        tag, pos = _read_protobuf_varint(buf, pos, limit)
        field_num = tag >> 3
        wire_type = tag & 0x07
        if field_num <= 0:
            raise ValueError("Invalid protobuf field number 0")
        if wire_type == 0:
            val, pos = _read_protobuf_varint(buf, pos, limit)
            yield field_num, wire_type, val, 0, 0
        elif wire_type == 1:
            if pos + 8 > limit:
                raise ValueError("Truncated fixed64 protobuf field")
            yield field_num, wire_type, 0, pos, pos + 8
            pos += 8
        elif wire_type == 2:
            length, pos = _read_protobuf_varint(buf, pos, limit)
            if pos + length > limit:
                raise ValueError("Truncated length-delimited protobuf field")
            yield field_num, wire_type, length, pos, pos + length
            pos += length
        elif wire_type == 5:
            if pos + 4 > limit:
                raise ValueError("Truncated fixed32 protobuf field")
            yield field_num, wire_type, 0, pos, pos + 4
            pos += 4
        else:
            raise ValueError(f"Unsupported protobuf wire type: {wire_type}")


def _parse_tensor_proto_name_and_validate(
    mv: memoryview,
    start: int,
    end: int,
    *,
    require_name: bool = True,
) -> str:
    dims: list[int] = []
    dtype = 0
    t_name = ""
    raw_len: int | None = None
    raw_s = 0
    raw_e = 0
    has_typed_data = False
    data_loc = 0

    for tfnum, twtype, tval, ts, te in _iter_protobuf_fields(mv, start, end):
        if tfnum == 1:
            if twtype == 0:
                dims.append(_to_signed_int64(tval))
            elif twtype == 2:
                ppos = ts
                while ppos < te:
                    dval, ppos = _read_protobuf_varint(mv, ppos, te)
                    dims.append(_to_signed_int64(dval))
            else:
                raise ValueError("Invalid TensorProto.dims wire type")
        elif tfnum == 2 and twtype == 0:
            dtype = tval
        elif tfnum in (4, 5, 6, 7, 10, 11):
            has_typed_data = True
        elif tfnum == 8 and twtype == 2:
            t_name = bytes(mv[ts:te]).decode("utf-8")
        elif tfnum == 9 and twtype == 2:
            raw_len = tval
            raw_s = ts
            raw_e = te
        elif tfnum == 14 and twtype == 0:
            data_loc = tval

    if (require_name and not t_name) or dtype <= 0 or any(d < 0 for d in dims):
        raise ValueError("Invalid TensorProto header")

    numel = 1
    for d in dims:
        numel *= d
    if data_loc == 1:
        # External tensor files (.onnx_data) are not bundled in EMBEDDING_MODEL_ASSET
        raise ValueError("External ONNX tensor storage is unsupported for self-contained embedding model")
    if raw_len is not None and dtype in _TENSOR_ELEM_BYTE_SIZES:
        if raw_len != numel * _TENSOR_ELEM_BYTE_SIZES[dtype]:
            raise ValueError("TensorProto.raw_data byte length mismatch")
        if raw_len > 0 and dtype in (1, 10, 11):
            np_dtype = "<f4" if dtype == 1 else ("<f2" if dtype == 10 else "<f8")
            sub_mv = mv[raw_s:raw_e]
            arr = np.frombuffer(sub_mv, dtype=np_dtype)
            has_nan = bool(np.isnan(arr).any())
            del arr
            sub_mv.release()
            if has_nan:
                raise ValueError("TensorProto.raw_data contains NaN weights")
    elif raw_len is None and numel > 0 and not has_typed_data:
        raise ValueError("Non-empty TensorProto is missing payload data")
    return t_name


def _parse_value_info_proto(
    mv: memoryview,
    start: int,
    end: int,
) -> tuple[str, int, list[int | str | None] | None]:
    vi_name = ""
    elem_type = 0
    vi_dims: list[int | str | None] | None = None
    for vfnum, vwtype, _vval, vs, ve in _iter_protobuf_fields(mv, start, end):
        if vfnum == 1 and vwtype == 2:
            vi_name = bytes(mv[vs:ve]).decode("utf-8")
        elif vfnum == 2 and vwtype == 2:
            for tfnum, twtype, _, ts, te in _iter_protobuf_fields(mv, vs, ve):
                if tfnum == 1 and twtype == 2:
                    for ttf, ttw, ttv, tts, tte in _iter_protobuf_fields(mv, ts, te):
                        if ttf == 1 and ttw == 0:
                            elem_type = ttv
                        elif ttf == 2 and ttw == 2:
                            vi_dims = []
                            for sf, sw, _, ss, se in _iter_protobuf_fields(mv, tts, tte):
                                if sf == 1 and sw == 2:
                                    dim_entry: int | str | None = None
                                    for df, dw, dv, ds, de in _iter_protobuf_fields(mv, ss, se):
                                        if df == 1 and dw == 0:
                                            dim_entry = _to_signed_int64(dv)
                                        elif df == 2 and dw == 2:
                                            dim_entry = bytes(mv[ds:de]).decode("utf-8")
                                    vi_dims.append(dim_entry)
    if not vi_name:
        raise ValueError("Empty ValueInfoProto.name")
    return vi_name, elem_type, vi_dims


def _validate_onnx_model_proto_structure(
    resolved_path: Path,
    *,
    expected_dims: int | None,
) -> bool:
    """Validate full ONNX ModelProto/GraphProto/TensorProto wire structure and embedding I/O."""
    try:
        with resolved_path.open("rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            mv = memoryview(mm)
            try:
                ir_version = 0
                opset_versions: list[int] = []
                graph_span: tuple[int, int] | None = None

                for fnum, wtype, val, s, e in _iter_protobuf_fields(mv, 0, len(mv)):
                    if fnum == 1 and wtype == 0:
                        ir_version = _to_signed_int64(val)
                    elif fnum == 7 and wtype == 2:
                        graph_span = (s, e)
                    elif fnum == 8 and wtype == 2:
                        ver = 0
                        for ofnum, owtype, oval, os_, oe_ in _iter_protobuf_fields(mv, s, e):
                            if ofnum == 1 and owtype == 2:
                                bytes(mv[os_:oe_]).decode("utf-8")
                            elif ofnum == 2 and owtype == 0:
                                ver = _to_signed_int64(oval)
                        opset_versions.append(ver)

                if ir_version <= 0 or not opset_versions or any(v <= 0 for v in opset_versions) or graph_span is None:
                    return False

                gs, ge = graph_span
                node_count = 0
                init_names: set[str] = set()
                node_inputs: set[str] = set()
                node_outputs: set[str] = set()
                inputs: list[tuple[str, int, list[int | str | None] | None]] = []
                outputs: list[tuple[str, int, list[int | str | None] | None]] = []

                for fnum, wtype, _val, s, e in _iter_protobuf_fields(mv, gs, ge):
                    if fnum == 1 and wtype == 2:
                        op_type = ""
                        has_output = False
                        for nfnum, nwtype, _nval, ns, ne in _iter_protobuf_fields(mv, s, e):
                            if nfnum == 1 and nwtype == 2:
                                inp_name = bytes(mv[ns:ne]).decode("utf-8")
                                if inp_name:
                                    node_inputs.add(inp_name)
                            elif nfnum == 2 and nwtype == 2:
                                out_name = bytes(mv[ns:ne]).decode("utf-8")
                                if out_name:
                                    has_output = True
                                    node_outputs.add(out_name)
                            elif nfnum == 4 and nwtype == 2:
                                op_type = bytes(mv[ns:ne]).decode("utf-8")
                            elif nfnum == 5 and nwtype == 2:
                                for afnum, awtype, _, as_, ae_ in _iter_protobuf_fields(mv, ns, ne):
                                    if afnum == 4 and awtype == 2:
                                        _parse_tensor_proto_name_and_validate(
                                            mv,
                                            as_,
                                            ae_,
                                            require_name=False,
                                        )
                        if not op_type or not has_output:
                            return False
                        node_count += 1
                    elif fnum == 5 and wtype == 2:
                        init_names.add(
                            _parse_tensor_proto_name_and_validate(mv, s, e, require_name=True)
                        )
                    elif fnum == 15 and wtype == 2:
                        for sfnum, swtype, _, ss, se in _iter_protobuf_fields(mv, s, e):
                            if sfnum == 1 and swtype == 2:
                                sp_name = _parse_tensor_proto_name_and_validate(
                                    mv,
                                    ss,
                                    se,
                                    require_name=False,
                                )
                                if sp_name:
                                    init_names.add(sp_name)
                    elif fnum == 11 and wtype == 2:
                        inputs.append(_parse_value_info_proto(mv, s, e))
                    elif fnum == 12 and wtype == 2:
                        outputs.append(_parse_value_info_proto(mv, s, e))

                if node_count <= 0 or not inputs or not outputs:
                    return False

                graph_input_names = {name for name, _, _ in inputs}
                produced = graph_input_names | init_names | node_outputs
                if not node_inputs.issubset(produced):
                    return False
                if any(out_name not in produced for out_name, _, _ in outputs):
                    return False

                runtime_input_names = graph_input_names - init_names
                if (
                    "input_ids" not in runtime_input_names
                    or not runtime_input_names.issubset(_ALLOWED_EMBEDDING_INPUT_NAMES)
                ):
                    return False

                _out_name, out_elem_type, out_dims = outputs[0]
                if out_elem_type != 0 and out_elem_type not in _FLOAT_TENSOR_ELEM_TYPES:
                    return False
                if out_dims is not None:
                    if len(out_dims) not in (2, 3):
                        return False
                    last_dim = out_dims[-1]
                    if isinstance(last_dim, int):
                        if last_dim <= 0:
                            return False
                        if expected_dims is not None and last_dim != expected_dims:
                            return False
                return True
            finally:
                mv.release()
    except (OSError, UnicodeDecodeError, ValueError, BufferError):
        return False


def _get_real_onnxruntime() -> Any | None:
    try:
        import onnxruntime as ort
    except ImportError:
        return None
    if callable(getattr(ort, "InferenceSession", None)) and callable(getattr(ort, "SessionOptions", None)):
        return ort
    return None


def _validate_onnx_with_runtime(
    ort: Any,
    resolved_path: Path,
    *,
    expected_dims: int | None,
) -> bool:
    """Verify ONNX Runtime can load, optimize, and execute a minimal forward pass on the graph."""
    sess = None
    try:
        opts = ort.SessionOptions()
        if hasattr(ort, "GraphOptimizationLevel"):
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.log_severity_level = 3
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        sess = ort.InferenceSession(
            str(resolved_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        sess_inputs = sess.get_inputs()
        input_map = {inp.name: inp for inp in sess_inputs}
        if (
            "input_ids" not in input_map
            or not set(input_map).issubset(_ALLOWED_EMBEDDING_INPUT_NAMES)
        ):
            return False

        id_shape = getattr(input_map["input_ids"], "shape", None) or ()
        batch_size = (
            id_shape[0]
            if len(id_shape) >= 1 and isinstance(id_shape[0], int) and id_shape[0] > 0
            else 1
        )
        seq_len = (
            id_shape[1]
            if len(id_shape) >= 2 and isinstance(id_shape[1], int) and id_shape[1] > 0
            else 2
        )
        dummy_ids = np.zeros((batch_size, seq_len), dtype=np.int64)
        dummy_mask = np.ones((batch_size, seq_len), dtype=np.int64)
        feeds: dict[str, np.ndarray] = {}
        for name in input_map:
            if name == "input_ids":
                feeds[name] = dummy_ids
            elif name == "attention_mask":
                feeds[name] = dummy_mask
            elif name == "token_type_ids":
                feeds[name] = np.zeros_like(dummy_ids, dtype=np.int64)

        outputs = sess.run(None, feeds)
        if not outputs:
            return False
        primary = np.asarray(outputs[0], dtype=np.float32)
        if primary.ndim not in (2, 3) or primary.shape[-1] <= 0:
            return False
        if expected_dims is not None and int(primary.shape[-1]) != int(expected_dims):
            return False
        return bool(np.all(np.isfinite(primary)))
    except Exception:
        return False
    finally:
        del sess


def _sample_file_digest(path: Path, size: int) -> str:
    hasher = hashlib.blake2b(digest_size=16)
    with path.open("rb") as fh:
        if size <= _FULL_HASH_MAX_BYTES:
            while chunk := fh.read(256 * 1024):
                hasher.update(chunk)
        else:
            hasher.update(fh.read(_SAMPLE_HASH_CHUNK_BYTES))
            mid = max(0, (size // 2) - (_SAMPLE_HASH_CHUNK_BYTES // 2))
            fh.seek(mid)
            hasher.update(fh.read(_SAMPLE_HASH_CHUNK_BYTES))
            tail = max(0, size - _SAMPLE_HASH_CHUNK_BYTES)
            fh.seek(tail)
            hasher.update(fh.read(_SAMPLE_HASH_CHUNK_BYTES))
    return hasher.hexdigest()


def validate_onnx_model_file(
    path: Path,
    *,
    expected_dims: int | None = EMBEDDING_DIMS,
) -> bool:
    """Verify the ONNX ModelProto file contains a complete, executable embedding graph."""
    try:
        if not path.is_file():
            return False
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
        if stat.st_size < _MIN_ONNX_FILE_BYTES:
            return False
        ort = _get_real_onnxruntime()
        has_real_ort = ort is not None
        sample_digest = _sample_file_digest(resolved, stat.st_size)
        cache_key = (
            _norm_resolved_path_str(resolved),
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
            sample_digest,
            has_real_ort,
            expected_dims,
        )
        with _ONNX_VALIDATION_CACHE_LOCK:
            cached = _ONNX_VALIDATION_CACHE.get(cache_key)
            if cached is not None:
                _ONNX_VALIDATION_CACHE.move_to_end(cache_key)
                return cached

        valid = _validate_onnx_model_proto_structure(resolved, expected_dims=expected_dims)
        if valid and ort is not None:
            valid = _validate_onnx_with_runtime(ort, resolved, expected_dims=expected_dims)

        with _ONNX_VALIDATION_CACHE_LOCK:
            _ONNX_VALIDATION_CACHE[cache_key] = valid
            _ONNX_VALIDATION_CACHE.move_to_end(cache_key)
            while len(_ONNX_VALIDATION_CACHE) > _MAX_ONNX_VALIDATION_CACHE_ENTRIES:
                _ONNX_VALIDATION_CACHE.popitem(last=False)
        return valid
    except OSError:
        return False


_validate_onnx_file = validate_onnx_model_file


def _validate_onnx_embedding_snapshot(snapshot: Path) -> bool:
    """Validate structured metadata, tokenizer vocab, and ONNX graph in a snapshot."""
    try:
        config = _read_snapshot_json_file(snapshot, "config.json")
        if not isinstance(config, dict):
            return False
        hidden_size = config.get("hidden_size")
        if (
            not isinstance(config.get("model_type"), str)
            or not config["model_type"].strip()
            or not _is_positive_int(hidden_size)
            or hidden_size != EMBEDDING_DIMS
            or not _is_positive_int(config.get("vocab_size"))
            or not isinstance(config.get("architectures"), list)
            or not config["architectures"]
            or not all(isinstance(name, str) and name for name in config["architectures"])
        ):
            return False

        tokenizer_config = _read_snapshot_json_file(snapshot, "tokenizer_config.json")
        if (
            not isinstance(tokenizer_config, dict)
            or not isinstance(tokenizer_config.get("tokenizer_class"), str)
            or not tokenizer_config["tokenizer_class"].strip()
        ):
            return False
        if (
            "model_max_length" in tokenizer_config
            and tokenizer_config["model_max_length"] is not None
            and not _is_positive_number(tokenizer_config["model_max_length"])
        ):
            return False

        tokenizer = _read_snapshot_json_file(snapshot, "tokenizer.json")
        tokenizer_model = tokenizer.get("model") if isinstance(tokenizer, dict) else None
        if (
            not isinstance(tokenizer, dict)
            or not isinstance(tokenizer.get("version"), str)
            or not isinstance(tokenizer_model, dict)
        ):
            return False
        model_type = tokenizer_model.get("type")
        if model_type is not None and (not isinstance(model_type, str) or not model_type.strip()):
            return False
        vocab = tokenizer_model.get("vocab")
        if not isinstance(vocab, (list, dict)) or not vocab:
            return False

        for candidate_rel in ONNX_MODEL_CANDIDATES:
            onnx_file = resolve_safe_snapshot_file(snapshot, candidate_rel)
            if onnx_file is not None and _validate_onnx_file(onnx_file):
                return True
        return False
    except (OSError, TypeError, ValueError):
        return False


EMBEDDING_MODEL_ASSET = ModelAssetSpec(
    asset_id="memory.embedding",
    title="ONNX multilingual MiniLM embedding model",
    variant=EMBEDDING_MODEL,
    repo_id=EMBEDDING_MODEL,
    allow_patterns=(
        "config.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "onnx/model_quantized.onnx",
    ),
    required_file_groups=(
        ("config.json",),
        ("tokenizer_config.json",),
        ("tokenizer.json",),
        ONNX_MODEL_CANDIDATES,
    ),
    snapshot_validator=_validate_onnx_embedding_snapshot,
    enforce_allow_patterns=False,
)


_DEFAULT_CONFIG_MANAGER = ConfigManager
_memory_bindings_lock = threading.RLock()
_bound_api_settings: ReadableDocument[ApiConfig] | None = None
_bound_layout: StorageLayout | None = None


def bind_memory_api_settings(
    api_settings: ReadableDocument[ApiConfig] | None,
    *,
    layout: StorageLayout | None = None,
) -> None:
    """Bind or clear narrow ``ReadableDocument[ApiConfig]`` and ``StorageLayout`` ports."""
    with _memory_bindings_lock:
        global _bound_api_settings, _bound_layout
        _bound_api_settings = api_settings
        _bound_layout = layout


def memory_store_db_path(layout: StorageLayout | None = None) -> Path:
    """Return the path to the unified SQLite hybrid memory store."""
    with _memory_bindings_lock:
        resolved_layout = layout or _bound_layout
    base = resolved_layout.data_dir if resolved_layout is not None else (Path.cwd() / "data")
    root = base / "memory"
    root.mkdir(parents=True, exist_ok=True)
    return root / MEMORY_STORE_FILENAME


def legacy_memory_qdrant_path(layout: StorageLayout | None = None) -> Path:
    """Return the legacy local Qdrant directory path (if present for migration)."""
    with _memory_bindings_lock:
        resolved_layout = layout or _bound_layout
    base = resolved_layout.data_dir if resolved_layout is not None else (Path.cwd() / "data")
    return base / "memory" / "qdrant"


def build_memory_engine_config(
    *,
    api_settings: ReadableDocument[ApiConfig] | None = None,
    layout: StorageLayout | None = None,
) -> dict[str, Any]:
    """Build the hybrid memory engine configuration from Shinsekai's settings."""
    with _memory_bindings_lock:
        bound_settings = _bound_api_settings
        bound_layout = _bound_layout
    active_settings = (
        api_settings
        if api_settings is not None
        else (bound_settings if ConfigManager is _DEFAULT_CONFIG_MANAGER else None)
    )
    resolved_layout = layout or bound_layout
    if active_settings is not None:
        provider, model, base_url, api_key = extract_llm_api_credentials(active_settings.get())
    else:
        cfg = ConfigManager()
        provider, model, base_url, api_key = cfg.get_llm_api_config()
    provider_lower = (provider or "").strip().lower()

    openai_like = {"deepseek", "chatgpt", "gemini", "豆包", "通义千问"}
    if provider_lower == "claude":
        llm_config: dict[str, Any] = {
            "provider": "anthropic",
            "config": {
                "model": model or "claude-3-haiku-20240307",
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        }
        if api_key:
            llm_config["config"]["api_key"] = api_key
    elif provider_lower in openai_like or base_url:
        llm_config = {
            "provider": "openai",
            "config": {
                "model": model or "gpt-4o-mini",
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        }
        if api_key:
            llm_config["config"]["api_key"] = api_key
        if base_url:
            llm_config["config"]["openai_base_url"] = base_url
    else:
        llm_config = {
            "provider": "openai",
            "config": {
                "model": "gpt-4o-mini",
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        }

    db_path = memory_store_db_path(layout=resolved_layout)
    qdrant_path = legacy_memory_qdrant_path(layout=resolved_layout)
    history_base = resolved_layout.data_dir if resolved_layout is not None else (Path.cwd() / "data")
    return {
        "vector_store": {
            "provider": "sqlite_hybrid",
            "config": {
                "path": db_path.as_posix(),
                "legacy_qdrant_path": qdrant_path.as_posix(),
                "collection_name": VECTOR_COLLECTION,
                "embedding_model_dims": EMBEDDING_DIMS,
            },
        },
        "llm": llm_config,
        "embedder": {
            "provider": "onnxruntime",
            "config": {
                "model": EMBEDDING_MODEL,
                "embedding_dims": EMBEDDING_DIMS,
            },
        },
        "history_db_path": str(history_base / "memory" / "mem0_history.db"),
    }


build_mem0_config = build_memory_engine_config


def is_embedding_model_cached() -> bool:
    """Return whether the configured ONNX embedding model snapshot is cached."""
    return embedding_model_snapshot_path() is not None


def embedding_model_snapshot_path() -> Path | None:
    """Return a validated local snapshot for the configured ONNX embedding model."""
    return find_cached_huggingface_snapshot(EMBEDDING_MODEL_ASSET)
