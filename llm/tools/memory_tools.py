"""
mem0 长期记忆 — 每个角色的记忆用 agent_id=character_name 隔离，
LLM / Embedding / 向量库配置从项目 ConfigManager 自动派生。

安装: pip install mem0ai
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

from config.config_manager import ConfigManager
from sdk.tool_registry import tool

logger = logging.getLogger(__name__)

_mem0: Any = None
_lock = threading.Lock()


def _build_mem0_config() -> dict[str, Any]:
    """从 ConfigManager 读取 LLM api 配置，组装 mem0 所需的 config dict。"""
    cfg = ConfigManager()
    provider, model, base_url, api_key = cfg.get_llm_api_config()
    _provider_lower = (provider or "").strip().lower()

    # ── LLM extractor (mem0 用 LLM 从对话中提取事实) ──
    _openai_like = {"deepseek", "chatgpt", "gemini", "豆包", "通义千问"}
    if _provider_lower == "claude":
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
    elif _provider_lower in _openai_like or base_url:
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

    # ── Embedder ──
    # 只有 ChatGPT 有可靠的 OpenAI embedding API；其他供应商一律本地 HuggingFace
    _embedding_dims = 384
    if _provider_lower == "chatgpt" and api_key:
        embedder_config: dict[str, Any] = {
            "provider": "openai",
            "config": {
                "model": "text-embedding-3-small",
                "embedding_dims": 1536,
                "api_key": api_key,
            },
        }
        _embedding_dims = 1536
    else:
        embedder_config = {
            "provider": "huggingface",
            "config": {
                "model": "sentence-transformers/all-MiniLM-L6-v2",
                "embedding_dims": _embedding_dims,
                "device": "cpu",
            },
        }

    # ── Vector store (本地 Qdrant，数据落在项目 data 目录) ──
    qdrant_path = (Path.cwd() / "data" / "memory" / "qdrant").as_posix()
    os.makedirs(qdrant_path, exist_ok=True)

    return {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "path": qdrant_path,
                "collection_name": "character_memories",
                "embedding_model_dims": _embedding_dims,
                "on_disk": True,
            },
        },
        "llm": llm_config,
        "embedder": embedder_config,
        "history_db_path": str(
            Path.cwd() / "data" / "memory" / "mem0_history.db"
        ),
    }


def _get_mem0() -> Any:
    """惰性初始化 mem0 Memory 实例。"""
    global _mem0
    if _mem0 is not None:
        return _mem0
    with _lock:
        if _mem0 is not None:
            return _mem0
        from mem0 import Memory

        config = _build_mem0_config()
        logger.info(
            "mem0 初始化: llm.provider=%s embedder.provider=%s",
            config["llm"]["provider"],
            config["embedder"]["provider"],
        )
        _mem0 = Memory.from_config(config)
        logger.info("mem0 已就绪")
        return _mem0


def _resolve_agent_id(character_name: str | None) -> str:
    name = (character_name or "").strip()
    return name if name else "user"


def memory_search(
    query: str,
    character_name: str | None = None,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"error": "query 不能为空"}
    agent_id = _resolve_agent_id(character_name)
    try:
        mem = _get_mem0()
        results = mem.search(q, user_id=agent_id, limit=limit)
        return {
            "agent_id": agent_id,
            "query": q,
            "count": len(results),
            "memories": results,
        }
    except Exception as e:
        logger.exception("memory_search 失败")
        return {"error": str(e)}


def memory_remember(
    content: str,
    character_name: str | None = None,
) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        return {"error": "content 不能为空"}
    agent_id = _resolve_agent_id(character_name)
    try:
        mem = _get_mem0()
        mem.add(text, user_id=agent_id)
        return {"ok": True, "agent_id": agent_id, "content": text}
    except Exception as e:
        logger.exception("memory_remember 失败")
        return {"error": str(e)}


def memory_forget(memory_id: str) -> dict[str, Any]:
    mid = (memory_id or "").strip()
    if not mid:
        return {"error": "memory_id 不能为空"}
    try:
        mem = _get_mem0()
        mem.delete(mid)
        return {"ok": True, "memory_id": mid}
    except Exception as e:
        logger.exception("memory_forget 失败")
        return {"error": str(e)}


# ── LLM tools ──────────────────────────────────────────────────────

@tool(
    name="memory_search",
    description=(
        "从长期记忆库中按关键词检索与指定人物相关的记忆（偏好、事实、约定等）。"
        "回答涉及跨会话/跨轮次信息时应先调用。"
        "参数 query：检索语句；character_name：要查的人物名（可选，默认 user）；limit：最多返回条数（默认 10）。"
    ),
)
def _tool_memory_search(
    query: str,
    character_name: str = "user",
    limit: int = 10,
) -> dict[str, Any]:
    return memory_search(query, character_name=character_name, limit=limit)


@tool(
    name="memory_remember",
    description=(
        "将一条重要信息存入长期记忆。content：要保存的事实/偏好/约定；"
        "character_name：属于哪个人物（可选，默认 user）。"
    ),
)
def _tool_memory_remember(
    content: str,
    character_name: str = "user",
) -> dict[str, Any]:
    return memory_remember(content, character_name=character_name)


@tool(
    name="memory_forget",
    description=(
        "删除一条长期记忆。memory_id 来自 memory_search 返回的 id。"
    ),
)
def _tool_memory_forget(memory_id: str) -> dict[str, Any]:
    return memory_forget(memory_id)
