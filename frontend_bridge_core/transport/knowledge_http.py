"""Outbound knowledge HTTP adapter with explicit connection settings."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Sequence

logger = logging.getLogger(__name__)


def request_knowledge_search(
    query: str, *, character_names: Sequence[str], limit: int = 5,
) -> dict[str, Any]:
    result = _request("search", {
        "query": query, "characterNames": list(character_names), "limit": limit,
    })
    return result if result is not None else {"error": "Knowledge service is unavailable"}


def request_knowledge_status(*, start_loading: bool = False, retry: bool = False) -> dict[str, Any] | None:
    return _request("status", {"startLoading": start_loading, "retry": retry})


def _request(endpoint: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    settings = _connection_settings()
    if settings is None:
        return None
    base_url, token, timeout = settings
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["X-Shinsekai-Bridge-Token"] = token
    try:
        request = urllib.request.Request(
            f"{base_url}/{endpoint}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
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


def _connection_settings() -> tuple[str, str, float] | None:
    url = str(os.environ.get("SHINSEKAI_KNOWLEDGE_SERVICE_URL") or "").strip().rstrip("/")
    if not url or str(os.environ.get("SHINSEKAI_KNOWLEDGE_SERVICE_OWNER") or "").strip() == "1":
        return None
    raw_timeout = str(os.environ.get("SHINSEKAI_KNOWLEDGE_SERVICE_TIMEOUT_SEC") or "").strip()
    try:
        timeout = float(raw_timeout) if raw_timeout else 60.0
        if not 0 < timeout < float("inf"):
            raise ValueError("timeout must be finite and positive")
    except ValueError:
        logger.warning("Invalid knowledge service timeout; using 60 seconds")
        timeout = 60.0
    return url, str(os.environ.get("SHINSEKAI_MEMORY_SERVICE_TOKEN") or "").strip(), timeout
