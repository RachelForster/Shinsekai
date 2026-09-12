"""Resolve selected asset identifiers against authoritative configuration."""

from .asset import AssetResolver, ResolvedAsset, asset_candidates
from .sprite import ResolvedSpriteAsset, SpriteAssetResolver

__all__ = [
    "AssetResolver",
    "ResolvedAsset",
    "ResolvedSpriteAsset",
    "SpriteAssetResolver",
    "asset_candidates",
]
