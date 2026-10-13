"""Transitional configuration and routing for the bridge knowledge service."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)
_KNOWLEDGE_SERVICE_URL_ENV = "SHINSEKAI_KNOWLEDGE_SERVICE_URL"
_KNOWLEDGE_SERVICE_OWNER_ENV = "SHINSEKAI_KNOWLEDGE_SERVICE_OWNER"
_KNOWLEDGE_SERVICE_TIMEOUT_ENV = "SHINSEKAI_KNOWLEDGE_SERVICE_TIMEOUT_SEC"
_KNOWLEDGE_SERVICE_DEFAULT_TIMEOUT_SEC = 60.0
_KNOWLEDGE_SERVICE_TOKEN_ENV = "SHINSEKAI_MEMORY_SERVICE_TOKEN"


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
    # Keep the transport import lazy while AI still owns transitional routing.
    from frontend_bridge_core.routes.knowledge_routes import BridgeKnowledgeHttp

    token = str(os.environ.get(_KNOWLEDGE_SERVICE_TOKEN_ENV) or "").strip()
    return BridgeKnowledgeHttp(
        base_url, token=token, timeout=_knowledge_service_timeout_sec(),
    ).request(endpoint, payload)


def knowledge_service_status(*, start_loading: bool = False, retry: bool = False) -> dict[str, Any] | None:
    """Query the bridge-owned runtime; never initialize a local store."""
    return request_knowledge_service("status", {"startLoading": start_loading, "retry": retry})
