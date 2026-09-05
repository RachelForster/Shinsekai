"""Ordered composition of asset lookup strategies."""

from __future__ import annotations

from collections.abc import Sequence

from .base import AssetLookupRequest, AssetLookupResult, AssetLookupStrategy


class CompositeAssetLookupStrategy(AssetLookupStrategy):
    """Return the first non-empty result from an ordered strategy chain."""

    def __init__(self, strategies: Sequence[AssetLookupStrategy]) -> None:
        if not strategies:
            raise ValueError("at least one asset lookup strategy is required")
        self._strategies = tuple(strategies)

    @property
    def strategies(self) -> tuple[AssetLookupStrategy, ...]:
        return self._strategies

    def lookup(self, request: AssetLookupRequest) -> AssetLookupResult:
        for strategy in self._strategies:
            result = strategy.lookup(request)
            if result.matches:
                return result
        return AssetLookupResult()
