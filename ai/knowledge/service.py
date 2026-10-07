"""HTTP client for the bridge-owned knowledge runtime."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)
_KNOWLEDGE_SERVICE_URL_ENV = "SHINSEKAI_KNOWLEDGE_SERVICE_URL"
_KNOWLEDGE_SERVICE_OWNER_ENV = "SHINSEKAI_KNOWLEDGE_SERVICE_OWNER"
_KNOWLEDGE_SERVICE_TIMEOUT_ENV = "SHINSEKAI_KNOWLEDGE_SERVICE_TIMEOUT_SEC"
_KNOWLEDGE_SERVICE_DEFAULT_TIMEOUT_SEC = 60.0
_KNOWLEDGE_SERVICE_TOKEN_ENV = "SHINSEKAI_MEMORY_SERVICE_TOKEN"
_KNOWLEDGE_SERVICE_TOKEN_HEADER = "X-Shinsekai-Bridge-Token"


def _knowledge_service_url() -> str:
    if str(os.environ.get(_KNOWLEDGE_SERVICE_OWNER_ENV) or "").strip() == "1":
        return ""
    return str(os.environ.get(_KNOWLEDGE_SERVICE_URL_ENV) or "").strip().rstrip("/")


def _knowledge_service_timeout_sec() -> float:
    raw = str(os.environ.get(_KNOWLEDGE_SERVICE_TIMEOUT_ENV) or "").strip()
    if not raw:
        return _KNOWLEDGE_SERVICE_DEFAULT_TIMEOUT_SEC
    try:
        timeout = float(raw)
    except ValueError:
        logger.warning("invalid %s=%r; using default timeout", _KNOWLEDGE_SERVICE_TIMEOUT_ENV, raw)
        return _KNOWLEDGE_SERVICE_DEFAULT_TIMEOUT_SEC
    if timeout <= 0:
        logger.warning("non-positive %s=%r; using default timeout", _KNOWLEDGE_SERVICE_TIMEOUT_ENV, raw)
        return _KNOWLEDGE_SERVICE_DEFAULT_TIMEOUT_SEC
    return timeout


def request_knowledge_service(endpoint: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    base_url = _knowledge_service_url()
    if not base_url:
        return None
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    token = str(os.environ.get(_KNOWLEDGE_SERVICE_TOKEN_ENV) or "").strip()
    if token:
        headers[_KNOWLEDGE_SERVICE_TOKEN_HEADER] = token
    try:
        request = urllib.request.Request(
            f"{base_url}/{endpoint}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST",
        )
        with urllib.request.urlopen(request, timeout=_knowledge_service_timeout_sec()) as response:
            result = json.loads(response.read(1024 * 1024).decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("knowledge service returned a non-object JSON response")
        return result
    except urllib.error.HTTPError as exc:
        logger.exception("Knowledge service request %s failed", endpoint)
        try:
            detail = exc.read(4096).decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        message = f"knowledge service HTTP {exc.code}: {detail or exc.reason}"
        return {"error": message}
    except Exception as exc:
        logger.exception("Knowledge service request %s failed", endpoint)
        return {"error": str(exc)}


def knowledge_service_status(*, start_loading: bool = False, retry: bool = False) -> dict[str, Any] | None:
    """Query the bridge-owned runtime; never initialize a local store."""
    return request_knowledge_service("status", {"startLoading": start_loading, "retry": retry})
