"""
mem0 长期记忆 — 每个角色的记忆用 agent_id=character_name 隔离，
LLM / Embedding / 向量库配置从项目 ConfigManager 自动派生。

安装: pip install mem0ai

模型加载策略：
首次调用任意记忆工具时，在后台线程启动 mem0 / embedding 模型加载，
同步返回 ``{"status": "loading"}`` 给 LLM（不阻塞聊天）。
LLM 收到此状态后应稍后重试；加载完成后工具正常返回结果。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from config.config_manager import ConfigManager
from sdk.tool_registry import ToolNotReady, tool

logger = logging.getLogger(__name__)

_mem0: Any = None
_mem0_load_error: BaseException | None = None
_mem0_loading = False
_loading_started_at: float = 0.0
_lock = threading.Lock()

_LOADING_FIRST_MSG = (
    "记忆系统正在后台初始化（embedding + 向量库），首次约需 2-5 分钟，后续约 10-30 秒。"
    "请直接告诉用户「记忆系统正在初始化，请稍等片刻」，不要重复调用本工具。"
)


def _loading_status_message() -> str:
    """动态生成加载状态消息，包含已等待时长。"""
    if _loading_started_at > 0:
        elapsed = int(time.time() - _loading_started_at)
        if elapsed < 60:
            return (
                f"记忆系统仍在加载中（已等待 {elapsed} 秒）。"
                "请直接告诉用户「记忆系统正在初始化，预计还需 1-4 分钟」，不要重复调用本工具。"
            )
        else:
            minutes = elapsed // 60
            seconds = elapsed % 60
            return (
                f"记忆系统仍在加载中（已等待 {minutes} 分 {seconds} 秒），"
                "还在下载/加载模型。请告诉用户再等 1-2 分钟，不要重复调用本工具。"
            )
    return _LOADING_FIRST_MSG


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
    # ChatGPT 用 OpenAI embedding；其他供应商用本地 HuggingFace 英文模型
    _embedding_dims = 384
    if _provider_lower == "chatgpt" and api_key:
        _embedding_dims = 1536
        embedder_config: dict[str, Any] = {
            "provider": "openai",
            "config": {
                "model": "text-embedding-3-small",
                "embedding_dims": _embedding_dims,
                "api_key": api_key,
            },
        }
    else:
        embedder_config = {
            "provider": "huggingface",
            "config": {
                "model": "sentence-transformers/all-MiniLM-L6-v2",
                "embedding_dims": _embedding_dims,
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


def _start_mem0_loading() -> None:
    """在后台线程启动 mem0 初始化，不阻塞调用方。"""
    global _mem0_loading, _loading_started_at
    with _lock:
        if _mem0 is not None or _mem0_loading:
            return
        _mem0_loading = True
        _loading_started_at = time.time()

    def _load() -> None:
        global _mem0, _mem0_loading, _mem0_load_error
        try:
            print("[mem0] 后台线程开始加载…")
            from mem0 import Memory
            config = _build_mem0_config()
            print(f"[mem0] llm.provider={config['llm']['provider']} embedder.provider={config['embedder']['provider']}")
            logger.info(
                "mem0 后台初始化: llm.provider=%s embedder.provider=%s",
                config["llm"]["provider"],
                config["embedder"]["provider"],
            )
            print("[mem0] 正在初始化 Memory.from_config（首次会下载 embedding 模型）…")
            mem = Memory.from_config(config)
            with _lock:
                _mem0 = mem
            print("[mem0] 后台加载完成，记忆系统已就绪")
            logger.info("mem0 后台加载完成")
        except ModuleNotFoundError:
            print("[mem0] mem0ai 未安装！")
            logger.exception("mem0 后台加载失败: mem0ai 未安装")
            with _lock:
                _mem0_load_error = ModuleNotFoundError("No module named 'mem0'")
        except Exception:
            print("[mem0] 后台加载失败！详见日志")
            logger.exception("mem0 后台加载失败")
        else:
            # 加载成功 → 通知宿主清除冷却 + 推送聊天通知
            try:
                from sdk.tool_registry import notify_tool_ready
                notify_tool_ready("memory", "记忆系统已就绪，可以继续使用。")
            except Exception:
                logger.exception("mem0 就绪通知失败")
        finally:
            with _lock:
                _mem0_loading = False

    print("[mem0] 启动后台加载线程…")
    t = threading.Thread(target=_load, name="mem0-loader", daemon=True)
    t.start()
    logger.info("mem0 后台加载线程已启动")


def _get_mem0() -> Any:
    """获取 mem0 实例（阻塞直到加载完成）。

    供 settings UI 等可接受等待的环境使用。
    工具调用请使用 :func:`_ensure_mem0` 以避免阻塞聊天。
    """
    global _mem0, _mem0_load_error
    if _mem0 is not None:
        return _mem0

    _start_mem0_loading()

    while _mem0 is None and _mem0_loading:
        time.sleep(0.5)

    if _mem0 is None:
        if isinstance(_mem0_load_error, ModuleNotFoundError):
            raise _mem0_load_error
        raise RuntimeError("mem0 加载失败")
    return _mem0


def check_mem0_status() -> dict[str, Any]:
    """检查 mem0 是否可用，不阻塞。

    返回状态字典：
    - ``{"status": "ready"}`` — 已就绪
    - ``{"status": "loading"}`` — 正在后台加载
    - ``{"status": "missing_dependency", "moduleName": "mem0", "packageName": "mem0ai"}`` — 未安装
    - ``{"status": "error", "message": "..."}`` — 加载失败（非缺少依赖）
    """
    global _mem0, _mem0_loading, _mem0_load_error
    if _mem0 is not None:
        return {"status": "ready"}
    if _mem0_loading:
        return {"status": "loading"}
    if isinstance(_mem0_load_error, ModuleNotFoundError):
        return {"status": "missing_dependency", "moduleName": "mem0", "packageName": "mem0ai"}
    if _mem0_load_error is not None:
        return {"status": "error", "message": str(_mem0_load_error)}
    # 尚未尝试加载，检查 mem0 是否可导入
    try:
        import mem0  # noqa: F401
        return {"status": "not_started"}
    except ImportError:
        return {"status": "missing_dependency", "moduleName": "mem0", "packageName": "mem0ai"}


def _ensure_mem0() -> Any:
    """确保 mem0 可用：已就绪则返回实例；否则启动后台加载并抛出 ToolNotReady。"""
    if _mem0 is not None:
        return _mem0
    _start_mem0_loading()
    raise ToolNotReady(_loading_status_message())


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
    mem = _ensure_mem0()
    agent_id = _resolve_agent_id(character_name)
    try:
        results = mem.search(q, filters={"user_id": agent_id}, limit=limit)
        # mem0 新版返回 {"results": [...]} 结构
        if isinstance(results, dict) and "results" in results:
            mems = results["results"]
        elif isinstance(results, list):
            mems = results
        else:
            mems = []
        return {
            "agent_id": agent_id,
            "query": q,
            "count": len(mems),
            "memories": mems,
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
    mem = _ensure_mem0()
    agent_id = _resolve_agent_id(character_name)
    try:
        mem.add(text, user_id=agent_id, infer=False)
        return {"ok": True, "agent_id": agent_id, "content": text}
    except Exception as e:
        logger.exception("memory_remember 失败")
        return {"error": str(e)}


def memory_forget(memory_id: str) -> dict[str, Any]:
    mid = (memory_id or "").strip()
    if not mid:
        return {"error": "memory_id 不能为空"}
    mem = _ensure_mem0()
    try:
        mem.delete(mid)
        return {"ok": True, "memory_id": mid}
    except Exception as e:
        logger.exception("memory_forget 失败")
        return {"error": str(e)}


# ── LLM tools ──────────────────────────────────────────────────────

@tool(
    name="memory_search",
    group="memory",
    description=(
        "Search YOUR memory. "
        "character_name: YOUR OWN full name from dialog (the character who is speaking). "
        "When you are playing a character, use that character's name. "
        "query: English keywords. Call BEFORE using cross-session info. "
        "NOTE: first call may return status:'loading' (model initializing, 2-5 min). "
        "If you get status:'loading', follow the message instruction — do NOT retry this tool or any memory_* tool."
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
    group="memory",
    description=(
        "Save a fact to YOUR memory. "
        "character_name: YOUR OWN full name from dialog (the character who is speaking). "
        "When you are playing 狛枝凪斗, use '狛枝凪斗', NOT 'user'. "
        "content: the fact IN ENGLISH. "
        "Only use character_name='user' for facts about the human user, not about yourself. "
        "NOTE: first call may return status:'loading'. If so, follow the message — do NOT retry any memory_* tool."
    ),
)
def _tool_memory_remember(
    content: str,
    character_name: str = "user",
) -> dict[str, Any]:
    return memory_remember(content, character_name=character_name)


@tool(
    name="memory_forget",
    group="memory",
    description=(
        "Delete a memory entry. memory_id comes from a memory_search result's id field. "
        "NOTE: first call may return status:'loading'. If so, follow the message — do NOT retry any memory_* tool."
    ),
)
def _tool_memory_forget(memory_id: str) -> dict[str, Any]:
    return memory_forget(memory_id)
