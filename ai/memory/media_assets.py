"""Mem0-backed index for tagged sprites, scenes, and BGM assets."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from collections.abc import Sequence
from typing import Any

from ai.memory.operations import _memory_service_request, _mem0_operation_lock
from ai.memory.runtime import ensure_mem0

logger = logging.getLogger(__name__)

_MEDIA_AGENT_ID = "semantic-media"
_MEDIA_SCOPE_PREFIX = "__shinsekai_media__"
_MAX_CANDIDATES = 500


def _scope_id(scope: str) -> str:
    normalized = " ".join(str(scope or "").strip().casefold().split())
    if not normalized:
        raise ValueError("asset scope is required")
    return f"{_MEDIA_SCOPE_PREFIX}:{normalized}"


def _candidate_rows(candidates: Sequence[Any]) -> list[dict[str, str]]:
    if len(candidates) > _MAX_CANDIDATES:
        raise ValueError(f"asset candidate count exceeds {_MAX_CANDIDATES}")
    rows: list[dict[str, str]] = []
    for item in candidates:
        if isinstance(item, dict):
            asset_id = str(item.get("asset_id") or "").strip()
            path = str(item.get("path") or "").strip()
            tags = str(item.get("tags") or "").strip()
        else:
            asset_id = str(getattr(item, "asset_id", "") or "").strip()
            path = str(getattr(item, "path", "") or "").strip()
            tags = str(getattr(item, "tags", "") or "").strip()
        if asset_id and tags:
            rows.append({"asset_id": asset_id, "path": path, "tags": tags})
    return rows


def _fingerprint(rows: Sequence[dict[str, str]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _pagination(method: Any, limit: int) -> dict[str, int]:
    parameters = inspect.signature(method).parameters
    return {"top_k": limit} if "top_k" in parameters else {"limit": limit}


def _results(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        rows = raw.get("results", [])
    else:
        rows = raw
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    return metadata if isinstance(metadata, dict) else row


def _filters(scope_id: str, fingerprint: str | None = None) -> dict[str, str]:
    filters = {"user_id": scope_id, "agent_id": _MEDIA_AGENT_ID}
    if fingerprint:
        filters["run_id"] = fingerprint
    return filters


def _ensure_index(mem: Any, scope_id: str, rows: Sequence[dict[str, str]]) -> str:
    fingerprint = _fingerprint(rows)
    current_filters = _filters(scope_id, fingerprint)
    existing = _results(
        mem.get_all(filters=current_filters, **_pagination(mem.get_all, _MAX_CANDIDATES))
    )
    existing_ids = {
        str(_metadata(row).get("asset_id") or "").strip() for row in existing
    }
    for row in rows:
        if row["asset_id"] in existing_ids:
            continue
        mem.add(
            row["tags"],
            user_id=scope_id,
            agent_id=_MEDIA_AGENT_ID,
            run_id=fingerprint,
            metadata={
                "asset_id": row["asset_id"],
                "asset_path": row["path"],
                "catalog_fingerprint": fingerprint,
            },
            infer=False,
        )
    return fingerprint


def _local_search(
    *,
    scope: str,
    vibe: str,
    candidates: Sequence[Any],
    limit: int,
) -> list[dict[str, Any]]:
    rows = _candidate_rows(candidates)
    query = str(vibe or "").strip()
    if not rows or not query:
        return []
    mem = ensure_mem0()
    scope_id = _scope_id(scope)
    with _mem0_operation_lock:
        fingerprint = _ensure_index(mem, scope_id, rows)
        raw = mem.search(
            query,
            filters=_filters(scope_id, fingerprint),
            **_pagination(mem.search, max(1, min(int(limit), len(rows)))),
        )
    matches = []
    for row in _results(raw):
        metadata = _metadata(row)
        asset_id = str(metadata.get("asset_id") or "").strip()
        if asset_id:
            matches.append({"asset_id": asset_id, "score": row.get("score")})
    return matches


def search_media_assets(
    *,
    scope: str,
    vibe: str,
    candidates: Sequence[Any],
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Index current candidates and return Mem0 matches for ``vibe``."""

    rows = _candidate_rows(candidates)
    payload = {
        "scope": str(scope or ""),
        "vibe": str(vibe or ""),
        "candidates": rows,
        "limit": max(1, int(limit)),
    }
    service_result = _memory_service_request("asset-search", payload)
    if service_result is not None:
        matches = service_result.get("matches", []) if isinstance(service_result, dict) else []
        return [row for row in matches if isinstance(row, dict)]
    return _local_search(**payload)


def media_asset_search_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a bridge request and return a stable JSON response."""

    matches = _local_search(
        scope=str(payload.get("scope") or ""),
        vibe=str(payload.get("vibe") or ""),
        candidates=payload.get("candidates") if isinstance(payload.get("candidates"), list) else [],
        limit=max(1, min(int(payload.get("limit") or 3), 20)),
    )
    return {"matches": matches}
