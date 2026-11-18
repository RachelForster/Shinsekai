"""Configuration and model-asset specs for long-term memory."""

from __future__ import annotations

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
from ai.memory.onnx_validation import (
    resolve_safe_snapshot_file,
    validate_onnx_embedding_snapshot,
    validate_onnx_model_file,
)

_safe_snapshot_file = resolve_safe_snapshot_file
_validate_onnx_file = validate_onnx_model_file
_validate_onnx_embedding_snapshot = validate_onnx_embedding_snapshot

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
    snapshot_validator=validate_onnx_embedding_snapshot,
    enforce_allow_patterns=False,
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
