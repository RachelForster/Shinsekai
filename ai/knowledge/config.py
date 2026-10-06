"""Mem0 configuration for the isolated knowledge store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.memory.config import build_mem0_config
from ai.knowledge.constants import VECTOR_COLLECTION


def build_knowledge_mem0_config() -> dict[str, Any]:
    config = build_mem0_config()
    root = Path.cwd() / "data" / "knowledge"
    root.mkdir(parents=True, exist_ok=True)
    config["vector_store"]["config"].update(
        {
            "path": (root / "qdrant").as_posix(),
            "collection_name": VECTOR_COLLECTION,
        }
    )
    config["history_db_path"] = str(root / "knowledge_history.db")
    return config
