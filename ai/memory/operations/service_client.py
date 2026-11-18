"""Bridge-owned remote memory service proxy and readiness monitor."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any
import urllib.error
import urllib.request

from ai.memory.operations.context import _package

logger = logging.getLogger(__name__)

_MEMORY_SERVICE_URL_ENV = "SHINSEKAI_MEMORY_SERVICE_URL"
_MEMORY_SERVICE_TOKEN_ENV = "SHINSEKAI_MEMORY_SERVICE_TOKEN"
_MEMORY_SERVICE_OWNER_ENV = "SHINSEKAI_MEMORY_SERVICE_OWNER"
_MEMORY_SERVICE_TIMEOUT_ENV = "SHINSEKAI_MEMORY_SERVICE_TIMEOUT_SEC"
_MEMORY_SERVICE_TOKEN_HEADER = "X-Shinsekai-Bridge-Token"
_MEMORY_SERVICE_READY_MESSAGE = "记忆系统已就绪，可以继续使用。"
_MEMORY_SERVICE_DEFAULT_TIMEOUT_SEC = 60.0
_MEMORY_SERVICE_READY_POLL_INTERVAL_SEC = 2.0
_MEMORY_SERVICE_READY_POLL_TIMEOUT_SEC = 300.0
_service_monitor_lock = threading.Lock()
_service_monitor_active = False


def _memory_service_url() -> str:
    if str(os.environ.get(_MEMORY_SERVICE_OWNER_ENV) or "").strip() == "1":
        return ""
    return str(os.environ.get(_MEMORY_SERVICE_URL_ENV) or "").strip().rstrip("/")


def _memory_service_timeout_sec() -> float:
    raw = str(os.environ.get(_MEMORY_SERVICE_TIMEOUT_ENV) or "").strip()
    if not raw:
        return _MEMORY_SERVICE_DEFAULT_TIMEOUT_SEC
    try:
        timeout = float(raw)
    except ValueError:
        logger.warning("invalid %s=%r; using default timeout", _MEMORY_SERVICE_TIMEOUT_ENV, raw)
        return _MEMORY_SERVICE_DEFAULT_TIMEOUT_SEC
    if timeout <= 0:
        logger.warning("non-positive %s=%r; using default timeout", _MEMORY_SERVICE_TIMEOUT_ENV, raw)
        return _MEMORY_SERVICE_DEFAULT_TIMEOUT_SEC
    return timeout


def _memory_service_request(
    endpoint: str,
    payload: dict[str, Any],
    *,
    monitor_ready: bool = True,
) -> dict[str, Any] | None:
    ops = _package()
    base_url = ops._memory_service_url()
    if not base_url:
        return None

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    token = str(os.environ.get(_MEMORY_SERVICE_TOKEN_ENV) or "").strip()
    if token:
        headers[_MEMORY_SERVICE_TOKEN_HEADER] = token

    request = urllib.request.Request(
        f"{base_url}/{endpoint.strip('/')}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_memory_service_timeout_sec()) as response:
            raw = response.read(1024 * 1024)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(4096).decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        return {"error": f"memory service HTTP {exc.code}: {detail}"}
    except Exception as exc:
        return {"error": f"memory service unavailable: {exc}"}

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        preview = raw[:200].decode("utf-8", errors="replace")
        return {"error": f"memory service returned invalid JSON: {exc}; body={preview!r}"}
    result = data if isinstance(data, dict) else {"result": data}
    if monitor_ready and result.get("status") == "loading":
        ops._start_memory_service_ready_monitor()
    return result


def memory_service_status(
    *,
    start_loading: bool,
    monitor_ready: bool = True,
) -> dict[str, Any] | None:
    """Return bridge-owned memory status without loading engine in this process."""
    return _package()._memory_service_request(
        "status",
        {"startLoading": bool(start_loading)},
        monitor_ready=monitor_ready,
    )


def _start_memory_service_ready_monitor() -> None:
    global _service_monitor_active
    ops = _package()
    if not ops._memory_service_url():
        return
    with _service_monitor_lock:
        if _service_monitor_active:
            return
        _service_monitor_active = True

    def _monitor() -> None:
        global _service_monitor_active
        deadline = time.monotonic() + _MEMORY_SERVICE_READY_POLL_TIMEOUT_SEC
        try:
            while time.monotonic() < deadline:
                time.sleep(_MEMORY_SERVICE_READY_POLL_INTERVAL_SEC)
                status = ops._memory_service_request("status", {})
                if not isinstance(status, dict):
                    continue
                if status.get("status") == "ready":
                    try:
                        from sdk.tool_registry import notify_tool_ready

                        notify_tool_ready("memory", _MEMORY_SERVICE_READY_MESSAGE)
                    except Exception:
                        logger.exception("memory service ready notification failed")
                    return
                if status.get("status") in {"error", "missing_dependency"}:
                    return
        finally:
            with _service_monitor_lock:
                _service_monitor_active = False

    threading.Thread(target=_monitor, name="memory-service-ready-monitor", daemon=True).start()
