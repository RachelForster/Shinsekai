"""mem0 runtime loading and status management."""

from __future__ import annotations

import importlib.util
import logging
import os
import threading
import time
from typing import Any

from core.model_assets.service import download_model_asset
from sdk.exception.types import (
    download_error_from_exception,
    runtime_dependency_error_from_exception,
    runtime_dependency_error_from_module,
)
from sdk.tool_registry import ToolNotReady

from ai.memory.config import (
    EMBEDDING_MODEL_ASSET,
    build_mem0_config,
    is_embedding_model_cached,
)
from ai.memory.constants import EMBEDDING_MODEL
from ai.memory.tasks import current_mem0_task, set_mem0_task

logger = logging.getLogger(__name__)


def _configure_mem0_environment() -> None:
    # mem0 otherwise starts separate hosted/OSS PostHog clients and an
    # additional telemetry vector store. Keep desktop memory local unless the
    # user explicitly opts in before launch.
    os.environ.setdefault("MEM0_TELEMETRY", "False")


_configure_mem0_environment()

_mem0: Any = None
_mem0_load_error: BaseException | None = None
_mem0_loading = False
_loading_started_at: float = 0.0
_lock = threading.Lock()

_LOADING_FIRST_MSG = (
    "记忆系统正在后台初始化（embedding + 向量库），首次约需 2-5 分钟，后续约 10-30 秒。"
    "请直接告诉用户「记忆系统正在初始化，请稍等片刻」，不要重复调用本工具。"
)


def _preload_embedding_model() -> str:
    result = download_model_asset(EMBEDDING_MODEL_ASSET, update_task=set_mem0_task)
    snapshot_path = result.get("path")
    if not snapshot_path:
        raise RuntimeError("The mem0 embedding model snapshot could not be located after download.")
    return str(snapshot_path)


def _dependency_from_error(error: BaseException) -> dict[str, Any]:
    return runtime_dependency_error_from_exception(error) or runtime_dependency_error_from_module("mem0")


def _missing_dependency_status(dependency: dict[str, Any]) -> dict[str, Any]:
    task = current_mem0_task()
    return {
        "status": "missing_dependency",
        "message": dependency["message"],
        "moduleName": dependency["moduleName"],
        "packageName": dependency["packageName"],
        **({"task": task} if task else {}),
    }


def _module_is_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (AttributeError, ImportError, ValueError):
        return False


def _create_mem0_instance(memory_type: Any, snapshot_path: str) -> Any:
    config = build_mem0_config()
    logger.info(
        "mem0 后台初始化: llm.provider=%s embedder.provider=%s",
        config["llm"]["provider"],
        config["embedder"]["provider"],
    )
    config["embedder"]["config"]["model"] = snapshot_path
    return memory_type.from_config(config)


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
        stage = "dependency"
        try:
            from mem0 import Memory

            stage = "download"
            snapshot_path = _preload_embedding_model()
            stage = "initialize"
            set_mem0_task(
                phase="initialize",
                status="running",
                message="Initializing long-term memory.",
                progress=0.96,
            )
            mem = _create_mem0_instance(Memory, snapshot_path)
            with _lock:
                _mem0 = mem
            set_mem0_task(
                phase="completed",
                status="succeeded",
                message="mem0 embedding model is ready.",
                progress=1,
            )
            logger.info("mem0 后台加载完成")
        except ModuleNotFoundError as exc:
            dependency = _dependency_from_error(exc)
            package_name = str(dependency["packageName"])
            logger.exception("mem0 后台加载失败: 缺少运行时依赖 %s", package_name)
            with _lock:
                _mem0_load_error = exc
            user_message = f"长期记忆缺少 {package_name}，请先安装运行时依赖。"
            set_mem0_task(
                error=str(exc),
                errorCode="missing_dependency",
                errorUserMessage=user_message,
                message=str(dependency["message"]),
                notice=user_message,
                noticeKind="error",
                phase="failed",
                progress=None,
                status="failed",
            )
        except Exception as exc:
            logger.exception("mem0 后台加载失败")
            with _lock:
                _mem0_load_error = exc
            if stage == "download":
                presented_error = download_error_from_exception(
                    exc,
                    source="huggingface",
                    url=EMBEDDING_MODEL,
                )
                error_code = presented_error["errorType"]
                user_message = presented_error["userMessage"]
                notice = presented_error["message"]
                http_status = presented_error["statusCode"]
            else:
                error_code = "memory_initialization_failed"
                user_message = f"长期记忆初始化失败：{exc}"
                notice = str(exc)
                http_status = None
            set_mem0_task(
                error=str(exc),
                errorCode=error_code,
                errorUserMessage=user_message,
                httpStatus=http_status,
                message=user_message,
                notice=notice,
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
    load_error = _mem0_load_error
    if isinstance(load_error, ModuleNotFoundError):
        dependency = _dependency_from_error(load_error)
        if not _module_is_available(str(dependency["moduleName"])):
            return _missing_dependency_status(dependency)

        # A dependency installer invalidates import caches before the next
        # status read. Clear only the exact error we inspected so an error from
        # a concurrent loader cannot be lost.
        with _lock:
            recovered = _mem0_load_error is load_error
            if recovered:
                _mem0_load_error = None
        if not recovered:
            return check_mem0_status(start_loading=start_loading)
    if _mem0_load_error is not None:
        task = current_mem0_task()
        result: dict[str, Any]
        if task and task.get("errorUserMessage"):
            result = {"status": "error", "message": str(task["errorUserMessage"]), "task": task}
        else:
            result = {"status": "error", "message": str(_mem0_load_error), **({"task": task} if task else {})}
        if not start_loading:
            return result
        start_mem0_loading()
        task = current_mem0_task()
        return {
            "status": "loading",
            "modelCached": is_embedding_model_cached(),
            **({"task": task} if task else {}),
        }
    try:
        import mem0  # noqa: F401

        if not start_loading:
            return {
                "status": "not_started",
                "modelCached": is_embedding_model_cached(),
            }
        start_mem0_loading()
        task = current_mem0_task()
        return {
            "status": "loading",
            "modelCached": is_embedding_model_cached(),
            **({"task": task} if task else {}),
        }
    except ImportError as exc:
        dependency = runtime_dependency_error_from_exception(exc)
        if dependency is None:
            task = current_mem0_task()
            return {"status": "error", "message": str(exc), **({"task": task} if task else {})}
        return _missing_dependency_status(dependency)
