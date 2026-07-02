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
from sdk.exception.types import download_error_from_exception
from sdk.tool_registry import ToolNotReady, tool

logger = logging.getLogger(__name__)

_mem0: Any = None
_mem0_load_error: BaseException | None = None
_mem0_loading = False
_loading_started_at: float = 0.0
_lock = threading.Lock()
_mem0_task: dict[str, Any] | None = None

_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_EMBEDDING_DIMS = 384
_VECTOR_COLLECTION = "character_memories_multilingual_minilm"


def _new_mem0_task(*, phase: str, status: str, message: str, progress: float | None) -> dict[str, Any]:
    now = int(time.time() * 1000)
    return {
        "createdAt": now,
        "error": "",
        "id": "mem0-embedding-model",
        "kind": "model-download",
        "logs": [],
        "message": message,
        "phase": phase,
        "progress": progress,
        "result": None,
        "status": status,
        "title": "mem0 embedding model",
        "updatedAt": now,
    }


def _set_mem0_task(**changes: Any) -> None:
    global _mem0_task
    now = int(time.time() * 1000)
    with _lock:
        task = dict(
            _mem0_task
            or _new_mem0_task(
                phase="queued",
                status="queued",
                message="Preparing mem0 embedding model.",
                progress=0,
            )
        )
        task.update(changes)
        task["updatedAt"] = now
        _mem0_task = task


def _current_mem0_task() -> dict[str, Any] | None:
    with _lock:
        return dict(_mem0_task) if _mem0_task is not None else None

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
    # Use a local multilingual MiniLM embedder for fast Chinese/English retrieval.
    embedder_config: dict[str, Any] = {
        "provider": "huggingface",
        "config": {
            "model": _EMBEDDING_MODEL,
            "embedding_dims": _EMBEDDING_DIMS,
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
                "collection_name": _VECTOR_COLLECTION,
                "embedding_model_dims": _EMBEDDING_DIMS,
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
    global _mem0_loading, _loading_started_at, _mem0_load_error
    with _lock:
        if _mem0 is not None or _mem0_loading:
            return
        _mem0_loading = True
        _mem0_load_error = None
        _loading_started_at = time.time()
    cached = _is_embedding_model_cached()
    _set_mem0_task(
        error="",
        errorCode="",
        errorUserMessage="",
        httpStatus=None,
        phase="reload" if cached else "download",
        notice="",
        noticeKind="info",
        status="running",
        message="Loading cached mem0 embedding model." if cached else "Downloading mem0 embedding model.",
        progress=None,
    )

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
            _set_mem0_task(
                phase="completed",
                status="succeeded",
                message="mem0 embedding model is ready.",
                progress=1,
            )
            print("[mem0] 后台加载完成，记忆系统已就绪")
            logger.info("mem0 后台加载完成")
        except ModuleNotFoundError:
            print("[mem0] mem0ai 未安装！")
            logger.exception("mem0 后台加载失败: mem0ai 未安装")
            with _lock:
                _mem0_load_error = ModuleNotFoundError("No module named 'mem0'")
            _set_mem0_task(
                error="No module named 'mem0'",
                errorCode="missing_dependency",
                errorUserMessage="长期记忆缺少 mem0ai，请先安装运行时依赖。",
                message="mem0ai is not installed.",
                notice="长期记忆缺少 mem0ai，请先安装运行时依赖。",
                noticeKind="error",
                phase="failed",
                progress=None,
                status="failed",
            )
        except Exception as exc:
            print("[mem0] 后台加载失败！详见日志")
            logger.exception("mem0 后台加载失败")
            download_error = download_error_from_exception(
                exc,
                source="huggingface",
                url=_EMBEDDING_MODEL,
            )
            with _lock:
                _mem0_load_error = exc
            _set_mem0_task(
                error=str(exc),
                errorCode=download_error["errorType"],
                errorUserMessage=download_error["userMessage"],
                httpStatus=download_error["statusCode"],
                message=download_error["userMessage"],
                notice=download_error["message"],
                noticeKind="error",
                phase="failed",
                progress=None,
                status="failed",
            )
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


def _is_embedding_model_cached() -> bool:
    """Check whether the HuggingFace sentence-transformers model is already cached.

    When cached, loading takes ~10-30s instead of 2-5 min (first download).
    """
    try:
        _cache_home = os.environ.get(
            "HF_HOME",
            os.path.join(str(Path.home()), ".cache", "huggingface", "hub"),
        )
        _model_dir = os.path.join(
            _cache_home,
            f"models--{_EMBEDDING_MODEL.replace('/', '--')}",
        )
        return os.path.isdir(_model_dir)
    except Exception:
        return False


def check_mem0_status() -> dict[str, Any]:
    """检查 mem0 是否可用，不阻塞。

    返回状态字典：
    - ``{"status": "ready"}`` — 已就绪
    - ``{"status": "loading"}`` — 正在后台加载
    - ``{"status": "not_started", "modelCached": true/false}`` — 尚未启动加载
    - ``{"status": "missing_dependency", "moduleName": "mem0", "packageName": "mem0ai"}`` — 未安装
    - ``{"status": "error", "message": "..."}`` — 加载失败（非缺少依赖）
    """
    global _mem0, _mem0_loading, _mem0_load_error
    if _mem0 is not None:
        task = _current_mem0_task()
        return {"status": "ready", **({"task": task} if task else {})}
    if _mem0_loading:
        task = _current_mem0_task()
        return {
            "status": "loading",
            "modelCached": _is_embedding_model_cached(),
            **({"task": task} if task else {}),
        }
    if isinstance(_mem0_load_error, ModuleNotFoundError):
        task = _current_mem0_task()
        return {
            "status": "missing_dependency",
            "moduleName": "mem0",
            "packageName": "mem0ai",
            **({"task": task} if task else {}),
        }
    if _mem0_load_error is not None:
        task = _current_mem0_task()
        if task and task.get("errorUserMessage"):
            return {"status": "error", "message": str(task["errorUserMessage"]), "task": task}
        return {"status": "error", "message": str(_mem0_load_error), **({"task": task} if task else {})}
    # 尚未尝试加载，检查 mem0 是否可导入
    try:
        import mem0  # noqa: F401
        # 触发后台加载（非阻塞），这样后续轮询可以看到 loading → ready 的过渡
        _start_mem0_loading()
        task = _current_mem0_task()
        return {
            "status": "loading",
            "modelCached": _is_embedding_model_cached(),
            **({"task": task} if task else {}),
        }
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
        "query: Chinese or English keywords. Call BEFORE using cross-session info. "
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
        "content: the fact in Chinese or English. "
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
