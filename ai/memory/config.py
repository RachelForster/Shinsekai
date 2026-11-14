"""Configuration and ONNX asset validation helpers for long-term memory."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from config.config_manager import ConfigManager
from core.model_assets.service import ModelAssetSpec, find_cached_huggingface_snapshot

from ai.memory.constants import (
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    MEMORY_STORE_FILENAME,
    ONNX_MODEL_CANDIDATES,
    VECTOR_COLLECTION,
)

_MIN_ONNX_FILE_BYTES = 16
_PROTOBUF_FIELD1_VARINT_TAG = 0x08


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


def _safe_snapshot_file(snapshot: Path, relative_path: str) -> Path | None:
    if not relative_path:
        return None
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    try:
        root_resolved = snapshot.resolve(strict=False)
        target_resolved = (snapshot / candidate).resolve(strict=False)
        if os.path.commonpath([str(root_resolved), str(target_resolved)]) != str(root_resolved):
            return None
        raw_target = snapshot / candidate
        return raw_target if raw_target.is_file() else None
    except (OSError, ValueError):
        return None


def _validate_onnx_file(path: Path) -> bool:
    """Verify the ONNX ModelProto file exists, is non-trivial, and has a valid header."""
    try:
        if not path.is_file() or path.stat().st_size < _MIN_ONNX_FILE_BYTES:
            return False
        with path.open("rb") as fh:
            header = fh.read(_MIN_ONNX_FILE_BYTES)
        return len(header) >= _MIN_ONNX_FILE_BYTES and header[0] == _PROTOBUF_FIELD1_VARINT_TAG
    except OSError:
        return False


def _validate_onnx_embedding_snapshot(snapshot: Path) -> bool:
    """Validate structured metadata, tokenizer vocab, and ONNX graph in a snapshot."""
    try:
        config = _read_json_file(snapshot / "config.json")
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

        tokenizer_config = _read_json_file(snapshot / "tokenizer_config.json")
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

        tokenizer = _read_json_file(snapshot / "tokenizer.json")
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
            onnx_file = _safe_snapshot_file(snapshot, candidate_rel)
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
)


def memory_store_db_path() -> Path:
    """Return the path to the unified SQLite hybrid memory store."""
    root = Path.cwd() / "data" / "memory"
    root.mkdir(parents=True, exist_ok=True)
    return root / MEMORY_STORE_FILENAME


def legacy_memory_qdrant_path() -> Path:
    """Return the legacy local Qdrant directory path (if present for migration)."""
    return Path.cwd() / "data" / "memory" / "qdrant"


def build_memory_engine_config() -> dict[str, Any]:
    """Build the hybrid memory engine configuration from Shinsekai's settings."""
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

    db_path = memory_store_db_path()
    return {
        "vector_store": {
            "provider": "sqlite_hybrid",
            "config": {
                "path": db_path.as_posix(),
                "legacy_qdrant_path": legacy_memory_qdrant_path().as_posix(),
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
        "history_db_path": str(Path.cwd() / "data" / "memory" / "mem0_history.db"),
    }


build_mem0_config = build_memory_engine_config


def is_embedding_model_cached() -> bool:
    """Return whether the configured ONNX embedding model snapshot is cached."""
    return embedding_model_snapshot_path() is not None


def embedding_model_snapshot_path() -> Path | None:
    """Return a validated local snapshot for the configured ONNX embedding model."""
    return find_cached_huggingface_snapshot(EMBEDDING_MODEL_ASSET)
