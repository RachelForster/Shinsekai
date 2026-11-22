"""Pure in-memory reference adapters for contract tests and fast sandboxes."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np

from core.vector_store.fts_tokenizer import tokenize_for_fts
from core.vector_store.in_memory import (
    InMemoryMemoryRepository,
    InMemoryStaticVectorStore,
)
from sdk.adapters.memory import ReadinessStatus


class DeterministicHashEmbedder:
    """Fast deterministic n-gram hash embedder implementing EmbeddingProvider."""

    def __init__(self, dimensions: int = 384) -> None:
        self._dimensions = max(8, int(dimensions))

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _encode_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self._dimensions, dtype=np.float32)
        tokens = tokenize_for_fts(text).split()
        if not tokens:
            tokens = [str(text or "").strip().casefold() or "__empty__"]
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            idx = int.from_bytes(digest[:4], "little") % self._dimensions
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            vec[idx] += sign
            idx2 = int.from_bytes(digest[8:12], "little") % self._dimensions
            sign2 = 1.0 if (digest[12] & 1) == 0 else -1.0
            vec[idx2] += 0.5 * sign2
        norm = float(np.linalg.norm(vec))
        if norm > 1e-12:
            vec /= norm
        return vec

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode_one(text)

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimensions), dtype=np.float32)
        return np.vstack([self._encode_one(text) for text in texts]).astype(np.float32)

    def status(self) -> ReadinessStatus:
        return ReadinessStatus(state="ready", model_cached=True, message="deterministic")


__all__ = [
    "DeterministicHashEmbedder",
    "InMemoryMemoryRepository",
    "InMemoryStaticVectorStore",
]
