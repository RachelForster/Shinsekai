"""Compatibility facade for long-term memory APIs."""

from __future__ import annotations

from .config import build_mem0_config as _build_mem0_config
from .config import is_embedding_model_cached as _is_embedding_model_cached
from .operations import memory_forget, memory_remember, memory_search
from .runtime import check_mem0_status
from .runtime import get_mem0 as _get_mem0

__all__ = [
    "_build_mem0_config",
    "_get_mem0",
    "_is_embedding_model_cached",
    "check_mem0_status",
    "memory_forget",
    "memory_remember",
    "memory_search",
]
