"""mem0 configuration helpers for long-term memory."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from config.config_manager import ConfigManager
from core.model_assets.service import ModelAssetSpec, find_cached_huggingface_snapshot

from ai.memory.constants import EMBEDDING_DIMS, EMBEDDING_MODEL, VECTOR_COLLECTION


def _read_json_file(path: Path) -> Any | None:
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _validate_safetensors_file(path: Path) -> bool:
    """Parse the tensor index without loading the model payload into memory."""
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        from safetensors import safe_open
    except (ImportError, OSError):
        return False
    try:
        with safe_open(str(path), framework="numpy") as tensors:
            return bool(list(tensors.keys()))
    except Exception:
        return False


def _is_positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _safe_module_directory(snapshot: Path, relative_path: str) -> bool:
    if not relative_path:
        return True
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    try:
        module_dir = (snapshot / candidate).resolve(strict=False)
        return (
            os.path.commonpath([str(snapshot.resolve(strict=False)), str(module_dir)])
            == str(snapshot.resolve(strict=False))
            and module_dir.is_dir()
        )
    except (OSError, ValueError):
        return False


def _validate_sentence_transformer_snapshot(snapshot: Path) -> bool:
    """Validate the structured files needed for local SentenceTransformer loading."""

    try:
        config = _read_json_file(snapshot / "config.json")
        if not isinstance(config, dict):
            return False
        hidden_size = config.get("hidden_size")
        if (
            not isinstance(config.get("model_type"), str)
            or not config["model_type"].strip()
            or not _is_positive_int(hidden_size)
            or not _is_positive_int(config.get("vocab_size"))
            or not isinstance(config.get("architectures"), list)
            or not config["architectures"]
            or not all(isinstance(name, str) and name for name in config["architectures"])
        ):
            return False

        modules = _read_json_file(snapshot / "modules.json")
        if not isinstance(modules, list) or not modules:
            return False

        module_types: set[str] = set()
        module_indexes: set[int] = set()
        for module in modules:
            if not isinstance(module, dict):
                return False
            module_type = module.get("type")
            module_path = module.get("path")
            module_index = module.get("idx")
            if (
                not isinstance(module.get("name"), str)
                or not isinstance(module_path, str)
                or not isinstance(module_type, str)
                or not module_type.startswith("sentence_transformers.models.")
                or type(module_index) is not int
                or module_index in module_indexes
                or not _safe_module_directory(snapshot, module_path)
            ):
                return False
            module_indexes.add(module_index)
            module_types.add(module_type)
        if not any(name.endswith(".Transformer") for name in module_types):
            return False
        if not any(name.endswith(".Pooling") for name in module_types):
            return False

        pooling = _read_json_file(snapshot / "1_Pooling" / "config.json")
        if not isinstance(pooling, dict):
            return False
        if pooling.get("word_embedding_dimension") != hidden_size or not any(
            pooling.get(key) is True
            for key in (
                "pooling_mode_cls_token",
                "pooling_mode_mean_tokens",
                "pooling_mode_max_tokens",
                "pooling_mode_mean_sqrt_len_tokens",
            )
        ):
            return False

        tokenizer_config = _read_json_file(snapshot / "tokenizer_config.json")
        if (
            not isinstance(tokenizer_config, dict)
            or not isinstance(tokenizer_config.get("tokenizer_class"), str)
            or not tokenizer_config["tokenizer_class"].strip()
            or not _is_positive_int(tokenizer_config.get("model_max_length"))
        ):
            return False
        tokenizer = _read_json_file(snapshot / "tokenizer.json")
        tokenizer_model = tokenizer.get("model") if isinstance(tokenizer, dict) else None
        if (
            not isinstance(tokenizer, dict)
            or not isinstance(tokenizer.get("version"), str)
            or not isinstance(tokenizer_model, dict)
            or not isinstance(tokenizer_model.get("type"), str)
            or not isinstance(tokenizer_model.get("vocab"), list)
            or not tokenizer_model["vocab"]
        ):
            return False
        if not _validate_safetensors_file(snapshot / "model.safetensors"):
            return False
        return True
    except (OSError, TypeError, ValueError):
        return False

EMBEDDING_MODEL_ASSET = ModelAssetSpec(
    asset_id="memory.embedding",
    title="mem0 embedding model",
    variant=EMBEDDING_MODEL,
    repo_id=EMBEDDING_MODEL,
    allow_patterns=(
        "1_Pooling/config.json",
        "config.json",
        "config_sentence_transformers.json",
        "model.safetensors",
        "modules.json",
        "sentence_bert_config.json",
        "sentencepiece.bpe.model",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "unigram.json",
    ),
    required_file_groups=(
        ("config.json",),
        ("modules.json",),
        ("1_Pooling/config.json",),
        ("tokenizer_config.json",),
        ("model.safetensors",),
        ("tokenizer.json",),
    ),
    snapshot_validator=_validate_sentence_transformer_snapshot,
)


def build_mem0_config() -> dict[str, Any]:
    """Build the mem0 config from Shinsekai's local LLM settings."""
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

    embedder_config: dict[str, Any] = {
        "provider": "huggingface",
        "config": {
            "model": EMBEDDING_MODEL,
            "embedding_dims": EMBEDDING_DIMS,
        },
    }

    qdrant_path = (Path.cwd() / "data" / "memory" / "qdrant").as_posix()
    os.makedirs(qdrant_path, exist_ok=True)

    return {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "path": qdrant_path,
                "collection_name": VECTOR_COLLECTION,
                "embedding_model_dims": EMBEDDING_DIMS,
                "on_disk": True,
            },
        },
        "llm": llm_config,
        "embedder": embedder_config,
        "history_db_path": str(Path.cwd() / "data" / "memory" / "mem0_history.db"),
    }


def is_embedding_model_cached() -> bool:
    """Return whether the configured HuggingFace embedding model is cached."""
    return embedding_model_snapshot_path() is not None


def embedding_model_snapshot_path() -> Path | None:
    """Return a complete local snapshot for the configured embedding model."""
    return find_cached_huggingface_snapshot(EMBEDDING_MODEL_ASSET)
