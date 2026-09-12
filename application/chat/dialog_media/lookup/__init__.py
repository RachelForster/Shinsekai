"""Strategies that rank configured assets for a dialog message."""

from .base import (
    AssetCandidate,
    AssetCatalog,
    AssetIdMatch,
    AssetLookupRequest,
    AssetLookupResult,
    AssetLookupStrategy,
)
from .composite import CompositeAssetLookupStrategy
from .factory import create_asset_lookup_strategy
from .message_asset_id import MessageAssetIdLookupStrategy
from .vector_database import VectorDatabaseAssetLookupStrategy

__all__ = [
    "AssetCandidate",
    "AssetCatalog",
    "AssetIdMatch",
    "AssetLookupRequest",
    "AssetLookupResult",
    "AssetLookupStrategy",
    "CompositeAssetLookupStrategy",
    "create_asset_lookup_strategy",
    "MessageAssetIdLookupStrategy",
    "VectorDatabaseAssetLookupStrategy",
]
