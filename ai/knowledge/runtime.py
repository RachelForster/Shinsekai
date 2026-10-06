"""Lazy runtime for the isolated knowledge Mem0 instance."""

from __future__ import annotations

import importlib.util
import os
import logging
import threading
import time
from typing import Any

from core.model_assets.service import download_model_asset
from sdk.exception.types import (
    download_error_from_exception,
    runtime_dependency_error_from_exception,
    runtime_dependency_error_from_module,
)

from ai.memory.config import (
    EMBEDDING_MODEL_ASSET,
    embedding_model_snapshot_path,
)
from ai.memory.constants import EMBEDDING_MODEL
from ai.knowledge.config import build_knowledge_mem0_config
from ai.knowledge.tasks import current_mem0_task, set_mem0_task

logger = logging.getLogger(__name__)

def _configure_mem0_environment() -> None:
    """Match Memory's local-by-default telemetry policy; preserve opt-in."""
    os.environ.setdefault("MEM0_TELEMETRY", "False")


_configure_mem0_environment()

_mem0: Any = None
_mem0_load_error: BaseException | None = None
_mem0_loading = False
_lock = threading.Lock()



def _preload_embedding_model() -> str:
    snapshot = embedding_model_snapshot_path()
    if snapshot is not None:
        set_mem0_task(phase="reload", message="Loading cached Knowledge embedding model.")
        return str(snapshot)
    set_mem0_task(phase="download", message="Downloading Knowledge embedding model.")
    result = download_model_asset(EMBEDDING_MODEL_ASSET, update_task=set_mem0_task)
    snapshot_path = str(result.get("path") or "").strip()
    if not snapshot_path:
        raise RuntimeError("knowledge embedding model snapshot is unavailable")
    return snapshot_path


def _create_mem0_instance(memory_type: Any, snapshot_path: str) -> Any:
    config = build_knowledge_mem0_config()
    config["embedder"]["config"]["model"] = snapshot_path
    return memory_type.from_config(config)


def _dependency_from_error(error: BaseException) -> dict[str, Any]:
    return runtime_dependency_error_from_exception(error) or runtime_dependency_error_from_module("mem0")


def _module_is_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (AttributeError, ImportError, ValueError):
        return False


def _missing_dependency_status(dependency: dict[str, Any]) -> dict[str, Any]:
    task = current_mem0_task()
    return {**dependency, "status": "missing_dependency", **({"task": task} if task else {})}


def _record_loading_error(exc: Exception, stage: str) -> None:
    global _mem0_load_error
    dependency = runtime_dependency_error_from_exception(exc)
    if isinstance(exc, ModuleNotFoundError):
        dependency = _dependency_from_error(exc)
    http_status = None
    if dependency is not None:
        error_code = "missing_dependency"
        user_message = f"资料缺少 {dependency['packageName']}，请先安装运行时依赖。"
        notice = str(dependency["message"])
    elif stage == "download":
        presented = download_error_from_exception(exc, source="huggingface", url=EMBEDDING_MODEL)
        error_code = presented["errorType"]
        user_message = presented["userMessage"]
        notice = presented["message"]
        http_status = presented["statusCode"]
    else:
        error_code = "knowledge_initialization_failed"
        user_message = f"资料初始化失败：{exc}"
        notice = str(exc)
    with _lock:
        _mem0_load_error = exc
        set_mem0_task(
            error=str(exc), errorCode=error_code, errorUserMessage=user_message,
            httpStatus=http_status, message=user_message, notice=notice,
            noticeKind="error", phase="failed", progress=None, status="failed",
        )


def start_mem0_loading(*, retry: bool = False) -> None:
    """Start Knowledge initialization in the background; failures require explicit retry."""
    global _mem0_loading, _mem0_load_error
    with _lock:
        if _mem0 is not None or _mem0_loading:
            return
        if _mem0_load_error is not None and not retry:
            return
        _mem0_load_error = None
        set_mem0_task(
            reset=True, status="running", phase="dependency", progress=None,
            message="Loading Knowledge dependencies.", error="", errorCode="",
            errorUserMessage="", httpStatus=None, notice="", noticeKind="info",
        )
        _mem0_loading = True

    def _load() -> None:
        global _mem0, _mem0_loading
        stage = "dependency"
        try:
            _configure_mem0_environment()
            from mem0 import Memory

            stage = "download"
            snapshot_path = _preload_embedding_model()
            stage = "initialize"
            set_mem0_task(
                phase="initialize", status="running", progress=0.96,
                message="Initializing knowledge.",
            )
            store = _create_mem0_instance(Memory, snapshot_path)
            with _lock:
                set_mem0_task(
                    phase="completed", status="succeeded", progress=1.0,
                    message="Knowledge is ready.",
                )
                _mem0 = store
        except Exception as exc:
            logger.exception("Knowledge initialization failed")
            _record_loading_error(exc, stage)
        finally:
            with _lock:
                _mem0_loading = False

    try:
        threading.Thread(target=_load, name="knowledge-loader", daemon=True).start()
    except Exception as exc:
        _record_loading_error(exc, "initialize")
        with _lock:
            _mem0_loading = False
        logger.exception("Could not start Knowledge loader")
        raise

_GET_MEM0_TIMEOUT_SEC = 600  # 10 minutes — covers worst-case first-time model download

def get_mem0() -> Any:
    """Return the Knowledge instance, waiting up to ten minutes for background loading."""
    start_mem0_loading()
    deadline = time.monotonic() + _GET_MEM0_TIMEOUT_SEC
    while True:
        with _lock:
            if _mem0 is not None:
                return _mem0
            loading = _mem0_loading
            error = _mem0_load_error
        if not loading:
            if error is not None:
                raise error
            raise RuntimeError("Knowledge mem0 loading failed")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Knowledge mem0 加载超时（{_GET_MEM0_TIMEOUT_SEC} 秒）。请检查网络连接和模型下载状态。")
        time.sleep(min(0.5, remaining))


def check_mem0_status(*, start_loading: bool = True, retry: bool = False) -> dict[str, Any]:
    """Report Knowledge availability without implicitly retrying failed initialization."""
    with _lock:
        ready = _mem0 is not None
        loading = _mem0_loading
        error = _mem0_load_error
        task = current_mem0_task()
    task_fields = {"task": task} if task else {}
    if ready:
        return {"status": "ready", "modelCached": True, **task_fields}
    if loading:
        return {"status": "loading", "modelCached": embedding_model_snapshot_path() is not None, **task_fields}
    if error is not None:
        dependency = (_dependency_from_error(error) if isinstance(error, ModuleNotFoundError)
                      else runtime_dependency_error_from_exception(error))
        if dependency is not None and not _module_is_available(str(dependency["moduleName"])):
            return _missing_dependency_status(dependency)
        if not retry:
            message = str(task.get("errorUserMessage") or error) if task else str(error)
            return {"status": "error", "error": str(error), "message": message, **task_fields}
    _configure_mem0_environment()
    try:
        importlib.import_module("mem0")
    except ImportError as exc:
        dependency = (_dependency_from_error(exc) if isinstance(exc, ModuleNotFoundError)
                      else runtime_dependency_error_from_exception(exc))
        if dependency is not None:
            return _missing_dependency_status(dependency)
        return {"status": "error", "message": str(exc), **task_fields}
    cached = embedding_model_snapshot_path() is not None
    if not start_loading and not retry:
        return {"status": "not_started", "modelCached": cached, **task_fields}
    if retry:
        start_mem0_loading(retry=True)
    else:
        start_mem0_loading()
    task = current_mem0_task()
    return {"status": "loading", "modelCached": cached, **({"task": task} if task else {})}
