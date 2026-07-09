"""mem0 runtime loading and status management."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from core.model_assets.downloads import preload_huggingface_snapshot
from sdk.exception.types import download_error_from_exception
from sdk.tool_registry import ToolNotReady

from ai.memory.config import build_mem0_config, is_embedding_model_cached
from ai.memory.constants import EMBEDDING_MODEL
from ai.memory.tasks import current_mem0_task, set_mem0_task

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


def _preload_embedding_model(*, cached: bool) -> None:
    preload_huggingface_snapshot(
        EMBEDDING_MODEL,
        cached=cached,
        update_task=set_mem0_task,
        download_message="Downloading mem0 embedding model",
        cached_message="Loading cached mem0 embedding model.",
        load_message="Loading mem0 embedding model.",
    )


def _loading_status_message() -> str:
    if _loading_started_at > 0:
        elapsed = int(time.time() - _loading_started_at)
        if elapsed < 60:
            return (
                f"记忆系统仍在加载中（已等待 {elapsed} 秒）。"
                "请直接告诉用户「记忆系统正在初始化，预计还需 1-4 分钟」，不要重复调用本工具。"
            )
        minutes = elapsed // 60
        seconds = elapsed % 60
        return (
            f"记忆系统仍在加载中（已等待 {minutes} 分 {seconds} 秒），"
            "还在下载/加载模型。请告诉用户再等 1-2 分钟，不要重复调用本工具。"
        )
    return _LOADING_FIRST_MSG


def start_mem0_loading() -> None:
    """Start mem0 initialization in a background thread."""
    global _mem0_loading, _loading_started_at, _mem0_load_error
    with _lock:
        if _mem0 is not None or _mem0_loading:
            return
        _mem0_loading = True
        _mem0_load_error = None
        _loading_started_at = time.time()

    cached = is_embedding_model_cached()
    set_mem0_task(
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

            config = build_mem0_config()
            print(f"[mem0] llm.provider={config['llm']['provider']} embedder.provider={config['embedder']['provider']}")
            logger.info(
                "mem0 后台初始化: llm.provider=%s embedder.provider=%s",
                config["llm"]["provider"],
                config["embedder"]["provider"],
            )
            print("[mem0] 正在初始化 Memory.from_config（首次会下载 embedding 模型）…")
            _preload_embedding_model(cached=cached)
            mem = Memory.from_config(config)
            with _lock:
                _mem0 = mem
            set_mem0_task(
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
            set_mem0_task(
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
                url=EMBEDDING_MODEL,
            )
            with _lock:
                _mem0_load_error = exc
            set_mem0_task(
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


_GET_MEM0_TIMEOUT_SEC = 600  # 10 minutes — covers worst-case first-time model download


def get_mem0() -> Any:
    """Return the mem0 instance, waiting for background initialization.

    Blocks until mem0 is ready or a fatal error occurs, with a timeout
    to prevent indefinite hangs if the download stalls.
    Prefer :func:`ensure_mem0` for non-blocking callers.
    """
    global _mem0, _mem0_load_error
    if _mem0 is not None:
        return _mem0

    start_mem0_loading()

    waited = 0.0
    while _mem0 is None and _mem0_loading:
        time.sleep(0.5)
        waited += 0.5
        if waited >= _GET_MEM0_TIMEOUT_SEC:
            raise TimeoutError(
                f"mem0 加载超时（已等待 {int(waited)} 秒 / {_GET_MEM0_TIMEOUT_SEC} 秒上限）。"
                "请检查网络连接和 HuggingFace 模型下载是否正常。"
            )

    if _mem0 is None:
        if isinstance(_mem0_load_error, ModuleNotFoundError):
            raise _mem0_load_error
        raise RuntimeError("mem0 加载失败")
    return _mem0


def ensure_mem0() -> Any:
    """Return mem0 if ready; otherwise start loading and raise ToolNotReady."""
    if _mem0 is not None:
        return _mem0
    start_mem0_loading()
    raise ToolNotReady(_loading_status_message())


def check_mem0_status(*, start_loading: bool = True) -> dict[str, Any]:
    """Return the current mem0 availability and model loading status."""
    global _mem0, _mem0_loading, _mem0_load_error
    if _mem0 is not None:
        task = current_mem0_task()
        return {"status": "ready", "modelCached": True, **({"task": task} if task else {})}
    if _mem0_loading:
        task = current_mem0_task()
        return {
            "status": "loading",
            "modelCached": is_embedding_model_cached(),
            **({"task": task} if task else {}),
        }
    if isinstance(_mem0_load_error, ModuleNotFoundError):
        task = current_mem0_task()
        return {
            "status": "missing_dependency",
            "moduleName": "mem0",
            "packageName": "mem0ai",
            **({"task": task} if task else {}),
        }
    if _mem0_load_error is not None:
        task = current_mem0_task()
        result: dict[str, Any]
        if task and task.get("errorUserMessage"):
            result = {"status": "error", "message": str(task["errorUserMessage"]), "task": task}
        else:
            result = {"status": "error", "message": str(_mem0_load_error), **({"task": task} if task else {})}
        # Restart loading on status check so the next poll picks up a
        # "loading" state and carries through to ready (or back to error).
        if start_loading:
            start_mem0_loading()
        return result
    try:
        import mem0  # noqa: F401

        if not start_loading:
            task = current_mem0_task()
            return {
                "status": "not_started",
                "modelCached": is_embedding_model_cached(),
                **({"task": task} if task else {}),
            }
        start_mem0_loading()
        task = current_mem0_task()
        return {
            "status": "loading",
            "modelCached": is_embedding_model_cached(),
            **({"task": task} if task else {}),
        }
    except ImportError:
        task = current_mem0_task()
        return {
            "status": "missing_dependency",
            "moduleName": "mem0",
            "packageName": "mem0ai",
            **({"task": task} if task else {}),
        }
