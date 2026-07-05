"""User-facing memory operations."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from ai.memory.runtime import ensure_mem0, get_mem0

logger = logging.getLogger(__name__)
_MEMORY_SERVICE_URL_ENV = "SHINSEKAI_MEMORY_SERVICE_URL"
_MEMORY_SERVICE_TOKEN_ENV = "SHINSEKAI_MEMORY_SERVICE_TOKEN"
_MEMORY_SERVICE_OWNER_ENV = "SHINSEKAI_MEMORY_SERVICE_OWNER"
_MEMORY_SERVICE_TOKEN_HEADER = "X-Shinsekai-Bridge-Token"
_MEMORY_SERVICE_READY_MESSAGE = "记忆系统已就绪，可以继续使用。"
_MEMORY_SERVICE_READY_POLL_INTERVAL_SEC = 2.0
_MEMORY_SERVICE_READY_POLL_TIMEOUT_SEC = 300.0
_service_monitor_lock = threading.Lock()
_service_monitor_active = False
_mem0_operation_lock = threading.RLock()


def _resolve_agent_id(character_name: str | None) -> str:
    name = (character_name or "").strip()
    return name if name else "user"


def _memory_row(row: Any) -> dict[str, str]:
    if isinstance(row, dict):
        return {
            "id": str(row.get("id") or ""),
            "memory": str(row.get("memory") or row.get("content") or ""),
        }
    return {"id": "", "memory": str(row)}


def _memory_service_url() -> str:
    if str(os.environ.get(_MEMORY_SERVICE_OWNER_ENV) or "").strip() == "1":
        return ""
    return str(os.environ.get(_MEMORY_SERVICE_URL_ENV) or "").strip().rstrip("/")


def _memory_service_request(endpoint: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    base_url = _memory_service_url()
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
        with urllib.request.urlopen(request, timeout=60) as response:
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
        return {"error": f"memory service returned invalid JSON: {exc}"}
    result = data if isinstance(data, dict) else {"result": data}
    if result.get("status") == "loading":
        _start_memory_service_ready_monitor()
    return result


def _start_memory_service_ready_monitor() -> None:
    global _service_monitor_active
    if not _memory_service_url():
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
                status = _memory_service_request("status", {})
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


def memory_list(character_name: str | None = None, *, limit: int = 200) -> dict[str, Any]:
    agent_id = _resolve_agent_id(character_name)
    service_result = _memory_service_request("list", {"name": agent_id, "limit": limit})
    if service_result is not None:
        return service_result
    mem = get_mem0()
    with _mem0_operation_lock:
        raw = mem.get_all(filters={"user_id": agent_id}, limit=limit)
    rows = raw.get("results", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    memories = [_memory_row(row) for row in rows]
    return {"agentId": agent_id, "count": len(memories), "memories": memories}


def memory_search(
    query: str,
    character_name: str | None = None,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"error": "query 不能为空"}
    service_result = _memory_service_request(
        "search",
        {"query": q, "characterName": _resolve_agent_id(character_name), "limit": limit},
    )
    if service_result is not None:
        return service_result
    mem = ensure_mem0()
    agent_id = _resolve_agent_id(character_name)
    try:
        with _mem0_operation_lock:
            results = mem.search(q, filters={"user_id": agent_id}, limit=limit)
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
    service_result = _memory_service_request(
        "remember",
        {"content": text, "characterName": _resolve_agent_id(character_name)},
    )
    if service_result is not None:
        return service_result
    mem = ensure_mem0()
    agent_id = _resolve_agent_id(character_name)
    try:
        with _mem0_operation_lock:
            mem.add(text, user_id=agent_id, infer=False)
        return {"ok": True, "agent_id": agent_id, "content": text}
    except Exception as e:
        logger.exception("memory_remember 失败")
        return {"error": str(e)}


def memory_remember_and_list(
    content: str,
    character_name: str | None = None,
) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        return {"error": "memory content is required"}
    result = memory_remember(text, character_name=character_name)
    if isinstance(result, dict) and result.get("error"):
        return result
    if isinstance(result, dict) and result.get("status") == "loading":
        return result
    return memory_list(character_name)


def memory_forget(memory_id: str) -> dict[str, Any]:
    mid = (memory_id or "").strip()
    if not mid:
        return {"error": "memory_id 不能为空"}
    service_result = _memory_service_request("forget", {"memoryId": mid})
    if service_result is not None:
        return service_result
    mem = ensure_mem0()
    try:
        with _mem0_operation_lock:
            mem.delete(mid)
        return {"ok": True, "memory_id": mid}
    except Exception as e:
        logger.exception("memory_forget 失败")
        return {"error": str(e)}


def memory_forget_and_list(
    memory_id: str,
    character_name: str | None = None,
) -> dict[str, Any]:
    mid = (memory_id or "").strip()
    if not mid:
        return {"error": "memory id is required"}
    result = memory_forget(mid)
    if isinstance(result, dict) and result.get("error"):
        return result
    if isinstance(result, dict) and result.get("status") == "loading":
        return result
    return memory_list(character_name)
