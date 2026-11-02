"""Lookup using the asset id explicitly emitted by the model."""

from __future__ import annotations

from .base import AssetIdMatch, AssetLookupRequest, AssetLookupResult, AssetLookupStrategy


class MessageAssetIdLookupStrategy(AssetLookupStrategy):
    """Return the legacy ``sprite``/``asset_id`` value unchanged."""

    def lookup(self, request: AssetLookupRequest) -> AssetLookupResult:
        asset_id = str(request.explicit_asset_id or "").strip()
        if not asset_id:
            return AssetLookupResult()
        return AssetLookupResult(matches=(AssetIdMatch(asset_id=asset_id),))
