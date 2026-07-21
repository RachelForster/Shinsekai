"""mem0 configuration helpers for long-term memory."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from config.config_manager import ConfigManager

from ai.memory.constants import EMBEDDING_DIMS, EMBEDDING_MODEL, VECTOR_COLLECTION

_EMBEDDING_MODEL_REQUIRED_JSON_FILES = (
    ("config.json", dict),
    ("modules.json", list),
    ("1_Pooling/config.json", dict),
    ("tokenizer_config.json", dict),
)
_EMBEDDING_MODEL_WEIGHT_FILES = (
    "model.safetensors",
    "pytorch_model.bin",
)
_EMBEDDING_MODEL_TOKENIZER_FILES = (
    "tokenizer.json",
    "sentencepiece.bpe.model",
    "unigram.json",
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
    try:
        model_dir_name = f"models--{EMBEDDING_MODEL.replace('/', '--')}"
        cache_roots = []
        for env_name in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
            raw = os.environ.get(env_name)
            if raw:
                cache_roots.append(Path(raw))
        hf_home = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")
        cache_roots.extend([hf_home / "hub", hf_home])
        cache_roots.extend([Path.cwd() / "data" / "cache" / "huggingface" / "hub"])

        seen: set[Path] = set()
        for root in cache_roots:
            model_dir = (root / model_dir_name).resolve(strict=False)
            if model_dir in seen:
                continue
            seen.add(model_dir)
            snapshots_dir = model_dir / "snapshots"
            snapshot = _complete_embedding_snapshot(snapshots_dir, model_dir / "refs" / "main")
            if snapshot is not None:
                return snapshot
        return None
    except Exception:
        return None


def _has_complete_embedding_snapshot(snapshots_dir: Path) -> bool:
    return _complete_embedding_snapshot(snapshots_dir) is not None


def _nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _read_json_file(path: Path) -> Any | None:
    if not _nonempty_file(path):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def is_embedding_model_snapshot_complete(snapshot: Path) -> bool:
    """Return whether a snapshot has the artifacts required for local loading."""
    try:
        if not snapshot.is_dir():
            return False

        parsed_json: dict[str, Any] = {}
        for relative_path, expected_type in _EMBEDDING_MODEL_REQUIRED_JSON_FILES:
            value = _read_json_file(snapshot / relative_path)
            if not isinstance(value, expected_type):
                return False
            parsed_json[relative_path] = value

        modules = parsed_json["modules.json"]
        if not modules:
            return False
        for module in modules:
            if not isinstance(module, dict):
                return False
            if not all(isinstance(module.get(key), str) for key in ("name", "path", "type")):
                return False
            module_path = module["path"]
            if module_path and not (snapshot / module_path).is_dir():
                return False

        has_weights = any(_nonempty_file(snapshot / name) for name in _EMBEDDING_MODEL_WEIGHT_FILES)
        has_tokenizer = any(_nonempty_file(snapshot / name) for name in _EMBEDDING_MODEL_TOKENIZER_FILES)
        return has_weights and has_tokenizer
    except (OSError, TypeError, ValueError):
        return False


def _complete_embedding_snapshot(snapshots_dir: Path, main_ref: Path | None = None) -> Path | None:
    if not snapshots_dir.is_dir():
        return None

    candidates: list[Path] = []
    if main_ref is not None and main_ref.is_file():
        revision = main_ref.read_text(encoding="utf-8").strip()
        if revision:
            candidates.append(snapshots_dir / revision)
    candidates.extend(sorted(snapshots_dir.iterdir(), key=lambda path: path.name, reverse=True))

    seen: set[Path] = set()
    for snapshot in candidates:
        if snapshot in seen:
            continue
        seen.add(snapshot)
        if not snapshot.is_dir():
            continue
        if is_embedding_model_snapshot_complete(snapshot):
            return snapshot
    return None
