"""Static vector slice index for tagged sprites, scenes, and BGM assets."""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from collections.abc import Sequence
from typing import Any

from ai.memory.engine import HybridMemoryEngine
from ai.memory.operations import _mem0_operation_lock, _memory_service_request
from ai.memory.runtime import ensure_mem0
from sdk.adapters.memory import NAMESPACE_MEDIA_ASSET, VectorSliceEntry

logger = logging.getLogger(__name__)

_MEDIA_AGENT_ID = "semantic-media"
_MEDIA_SCOPE_PREFIX = "__shinsekai_media__"


def _scope_id(scope: str) -> str:
    normalized = " ".join(str(scope or "").strip().casefold().split())
    if not normalized:
        raise ValueError("asset scope is required")
    return f"{_MEDIA_SCOPE_PREFIX}:{normalized}"


def _candidate_rows(candidates: Sequence[Any]) -> list[dict[str, str]]:
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


def _slice_id(scope_id: str, fingerprint: str, asset_id: str) -> str:
    scope_digest = hashlib.sha256(scope_id.encode("utf-8")).hexdigest()[:16]
    return f"{scope_digest}:{fingerprint}:{asset_id}"


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


def _ensure_hybrid_index(
    engine: HybridMemoryEngine,
    scope_id: str,
    rows: Sequence[dict[str, str]],
) -> tuple[str, int]:
    fingerprint = _fingerprint(rows)
    existing_slices = engine.vector_store.list_slices(
        namespace=NAMESPACE_MEDIA_ASSET,
        scope_id=scope_id,
        limit=max(len(rows) * 2, 500),
    )
    has_stale = any(
        str(entry.metadata.get("catalog_fingerprint") or "") != fingerprint
        for entry in existing_slices
    )
    if has_stale:
        engine.vector_store.delete_scope(
            namespace=NAMESPACE_MEDIA_ASSET,
            scope_id=scope_id,
        )
        existing_ids: set[str] = set()
    else:
        existing_ids = {
            str(entry.metadata.get("asset_id") or "").strip()
            for entry in existing_slices
        }

    missing = [row for row in rows if row["asset_id"] not in existing_ids]
    if not missing:
        return fingerprint, 0

    vectors = engine.embedder.embed_documents([row["tags"] for row in missing])
    entries = [
        VectorSliceEntry(
            id=_slice_id(scope_id, fingerprint, row["asset_id"]),
            namespace=NAMESPACE_MEDIA_ASSET,
            scope_id=scope_id,
            text=row["tags"],
            metadata={
                "asset_id": row["asset_id"],
                "asset_path": row["path"],
                "catalog_fingerprint": fingerprint,
            },
            embedding=vectors[idx],
        )
        for idx, row in enumerate(missing)
    ]
    added_count = engine.vector_store.upsert_slices(entries)
    return fingerprint, added_count


def _ensure_index(
    mem: Any, scope_id: str, rows: Sequence[dict[str, str]]
) -> tuple[str, int]:
    if isinstance(mem, HybridMemoryEngine):
        return _ensure_hybrid_index(mem, scope_id, rows)

    fingerprint = _fingerprint(rows)
    current_filters = _filters(scope_id, fingerprint)
    existing = _results(
        mem.get_all(filters=current_filters, **_pagination(mem.get_all, len(rows)))
    )
    existing_ids = {
        str(_metadata(row).get("asset_id") or "").strip() for row in existing
    }
    added_count = 0
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
        added_count += 1
    return fingerprint, added_count


def _catalog_payload(catalog: Any) -> dict[str, Any]:
    if isinstance(catalog, dict):
        scope = catalog.get("scope")
        candidates = catalog.get("candidates")
    else:
        scope = getattr(catalog, "scope", "")
        candidates = getattr(catalog, "candidates", ())
    return {
        "scope": str(scope or ""),
        "candidates": _candidate_rows(
            candidates if isinstance(candidates, (list, tuple)) else ()
        ),
    }


def _local_index_catalogs(catalogs: Sequence[Any]) -> dict[str, int]:
    normalized = [
        catalog
        for catalog in (_catalog_payload(item) for item in catalogs)
        if catalog["scope"] and catalog["candidates"]
    ]
    if not normalized:
        return {"catalogCount": 0, "assetCount": 0, "addedCount": 0}
    mem = ensure_mem0()
    asset_count = 0
    added_count = 0
    with _mem0_operation_lock:
        for catalog in normalized:
            rows = catalog["candidates"]
            asset_count += len(rows)
            _fingerprint_value, added = _ensure_index(
                mem,
                _scope_id(catalog["scope"]),
                rows,
            )
            added_count += added
    return {
        "catalogCount": len(normalized),
        "assetCount": asset_count,
        "addedCount": added_count,
    }


def ensure_media_asset_indexes(catalogs: Sequence[Any]) -> dict[str, int]:
    """Ensure all tagged catalogs exist before semantic lookup begins."""
    payload = {"catalogs": [_catalog_payload(catalog) for catalog in catalogs]}
    service_result = _memory_service_request("asset-index", payload)
    if service_result is not None:
        error = str(service_result.get("error") or "").strip()
        status = str(service_result.get("status") or "").strip()
        if error or status in {"error", "loading", "missing_dependency"}:
            message = str(service_result.get("message") or error or status).strip()
            raise RuntimeError(message or "semantic media indexing failed")
        count_fields = {"catalogCount", "assetCount", "addedCount"}
        if not count_fields.issubset(service_result):
            raise RuntimeError("memory service returned an invalid asset index response")
        return {
            "catalogCount": int(service_result.get("catalogCount") or 0),
            "assetCount": int(service_result.get("assetCount") or 0),
            "addedCount": int(service_result.get("addedCount") or 0),
        }
    return _local_index_catalogs(payload["catalogs"])


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
    bounded_limit = max(1, min(int(limit), len(rows)))

    if isinstance(mem, HybridMemoryEngine):
        with _mem0_operation_lock:
            fingerprint, _added_count = _ensure_hybrid_index(mem, scope_id, rows)
            q_vec = mem.embedder.embed_query(query)
            hits = mem.vector_store.search_slices(
                namespace=NAMESPACE_MEDIA_ASSET,
                scope_ids=(scope_id,),
                query_vector=q_vec,
                keyword_query=query,
                metadata_filter={"catalog_fingerprint": fingerprint},
                limit=bounded_limit,
            )
        return [
            {
                "asset_id": str(hit.entry.metadata.get("asset_id") or "").strip(),
                "score": hit.score,
            }
            for hit in hits
            if str(hit.entry.metadata.get("asset_id") or "").strip()
        ]

    with _mem0_operation_lock:
        fingerprint, _added_count = _ensure_index(mem, scope_id, rows)
        raw = mem.search(
            query,
            filters=_filters(scope_id, fingerprint),
            **_pagination(mem.search, bounded_limit),
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
    """Index current candidates and return semantic matches for ``vibe``."""
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


def media_asset_index_response(payload: dict[str, Any]) -> dict[str, int]:
    """Ensure bridge-owned indexes for a batch of catalogs."""
    catalogs = payload.get("catalogs")
    return _local_index_catalogs(catalogs if isinstance(catalogs, list) else [])
