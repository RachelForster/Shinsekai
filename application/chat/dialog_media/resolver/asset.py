"""Generic configured-asset resolution."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ..lookup import AssetCandidate, AssetLookupResult


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _asset_id_key(value: object) -> str:
    text = str(value if value is not None else "").strip()
    try:
        number = int(text)
    except (TypeError, ValueError):
        return text
    return str(number)


def asset_candidates(
    assets: Sequence[Any],
    *,
    tags: Sequence[str] = (),
    path_of: Callable[[Any], str] | None = None,
) -> tuple[AssetCandidate, ...]:
    """Build stable one-based candidates from a configured asset sequence."""

    get_path = path_of or (lambda item: str(_value(item, "path", "") or ""))
    return tuple(
        AssetCandidate(
            asset_id=str(index + 1),
            index=index,
            value=asset,
            path=get_path(asset),
            tags=str(tags[index] if index < len(tags) else ""),
        )
        for index, asset in enumerate(assets)
    )


@dataclass(frozen=True, slots=True)
class ResolvedAsset:
    """An asset selected from the current configuration."""

    asset_id: str
    index: int | None = None
    value: Any | None = None
    path: str = ""

    @property
    def found(self) -> bool:
        return self.index is not None and self.value is not None


class AssetResolver:
    """Resolve ranked ids while rejecting stale or unknown candidates."""

    def resolve(
        self,
        candidates: Sequence[AssetCandidate],
        result: AssetLookupResult,
        *,
        unresolved_asset_id: str = "-1",
    ) -> ResolvedAsset:
        by_id = {_asset_id_key(candidate.asset_id): candidate for candidate in candidates}
        for match in result.matches:
            candidate = by_id.get(_asset_id_key(match.asset_id))
            if candidate is not None:
                return ResolvedAsset(
                    asset_id=candidate.asset_id,
                    index=candidate.index,
                    value=candidate.value,
                    path=candidate.path,
                )
        fallback_id = result.best.asset_id if result.best is not None else unresolved_asset_id
        return ResolvedAsset(asset_id=str(fallback_id or unresolved_asset_id))
