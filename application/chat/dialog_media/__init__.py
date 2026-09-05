"""Strategies used while preparing dialog media for presentation."""

from .lookup import (
    AssetCandidate,
    AssetCatalog,
    AssetIdMatch,
    AssetLookupRequest,
    AssetLookupResult,
    AssetLookupStrategy,
    CompositeAssetLookupStrategy,
    create_asset_lookup_strategy,
    MessageAssetIdLookupStrategy,
    VectorDatabaseAssetLookupStrategy,
)
from .models import TtsGenerationRequest
from .resolver import (
    AssetResolver,
    ResolvedAsset,
    ResolvedSpriteAsset,
    SpriteAssetResolver,
    asset_candidates,
)
from .catalogs import build_session_asset_catalogs
from .tts_generation import DefaultTtsGenerationStrategy, TtsGenerationStrategy

__all__ = [
    "AssetCandidate",
    "AssetCatalog",
    "AssetIdMatch",
    "AssetLookupRequest",
    "AssetLookupResult",
    "AssetLookupStrategy",
    "AssetResolver",
    "asset_candidates",
    "build_session_asset_catalogs",
    "CompositeAssetLookupStrategy",
    "create_asset_lookup_strategy",
    "DefaultTtsGenerationStrategy",
    "MessageAssetIdLookupStrategy",
    "ResolvedAsset",
    "ResolvedSpriteAsset",
    "SpriteAssetResolver",
    "TtsGenerationRequest",
    "TtsGenerationStrategy",
    "VectorDatabaseAssetLookupStrategy",
]
