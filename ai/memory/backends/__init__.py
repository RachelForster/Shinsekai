"""Pluggable backend implementations for memory and embedding ports."""

from __future__ import annotations

from ai.memory.backends.in_memory import (
    DeterministicHashEmbedder,
    InMemoryMemoryRepository,
    InMemoryStaticVectorStore,
)
from ai.memory.backends.onnx_embedder import OnnxMiniLmEmbedder, find_onnx_model_file
from ai.memory.backends.sqlite_repo import SqliteHybridMemoryRepo

__all__ = [
    "DeterministicHashEmbedder",
    "InMemoryMemoryRepository",
    "InMemoryStaticVectorStore",
    "OnnxMiniLmEmbedder",
    "SqliteHybridMemoryRepo",
    "find_onnx_model_file",
]
