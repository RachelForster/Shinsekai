"""Build the media lookup chain selected for a chat session."""

from .base import AssetLookupStrategy
from .composite import CompositeAssetLookupStrategy
from .message_asset_id import MessageAssetIdLookupStrategy
from .vector_database import VectorDatabaseAssetLookupStrategy


def create_asset_lookup_strategy(mode: str) -> AssetLookupStrategy:
    direct = MessageAssetIdLookupStrategy()
    if str(mode or "").strip().lower() != "semantic":
        return direct
    return CompositeAssetLookupStrategy(
        (VectorDatabaseAssetLookupStrategy(), direct)
    )
