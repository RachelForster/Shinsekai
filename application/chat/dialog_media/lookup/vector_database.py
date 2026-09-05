"""Asset lookup backed by the configured vector database."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from .base import AssetIdMatch, AssetLookupRequest, AssetLookupResult, AssetLookupStrategy

logger = logging.getLogger(__name__)

SearchAssets = Callable[..., Sequence[dict[str, Any]]]


def _search_assets(**kwargs: Any) -> Sequence[dict[str, Any]]:
    from ai.memory.media_assets import search_media_assets

    return search_media_assets(**kwargs)


class VectorDatabaseAssetLookupStrategy(AssetLookupStrategy):
    """Rank asset ids by comparing ``vibe`` with indexed asset tags."""

    def __init__(
        self,
        search: SearchAssets | None = None,
        *,
        limit: int = 3,
        minimum_score: float | None = None,
    ) -> None:
        self._search = search or _search_assets
        self._limit = max(1, int(limit))
        self._minimum_score = minimum_score

    def lookup(self, request: AssetLookupRequest) -> AssetLookupResult:
        vibe = str(request.vibe or "").strip()
        tagged = tuple(candidate for candidate in request.candidates if candidate.tags.strip())
        if not vibe or not tagged:
            return AssetLookupResult()
        try:
            rows = self._search(
                scope=request.scope,
                vibe=vibe,
                candidates=tagged,
                limit=min(self._limit, len(tagged)),
            )
        except Exception:
            logger.warning(
                "Semantic asset lookup failed for scope=%s",
                request.scope,
                exc_info=True,
            )
            return AssetLookupResult()

        candidate_ids = {candidate.asset_id for candidate in request.candidates}
        matches: list[AssetIdMatch] = []
        seen: set[str] = set()
        for row in rows:
            asset_id = str(row.get("asset_id") or "").strip()
            if not asset_id or asset_id not in candidate_ids or asset_id in seen:
                continue
            raw_score = row.get("score")
            try:
                score = float(raw_score) if raw_score is not None else None
            except (TypeError, ValueError):
                score = None
            if (
                self._minimum_score is not None
                and score is not None
                and score < self._minimum_score
            ):
                continue
            seen.add(asset_id)
            matches.append(AssetIdMatch(asset_id=asset_id, score=score))
        return AssetLookupResult(matches=tuple(matches))
