"""Bound character catalog lookup shared across chat presentation adapters."""

from __future__ import annotations

import threading
from typing import Any

_config_manager = None
_catalog_lock = threading.RLock()
_bound_character_catalog: Any = None


def bind_presentation_character_catalog(catalog: Any | None) -> None:
    """Bind or clear a narrow ``CharacterCatalogPort`` for presentation lookups."""
    with _catalog_lock:
        global _bound_character_catalog
        _bound_character_catalog = catalog


def _get_config_manager():
    global _config_manager
    if _config_manager is None:
        from config.config_manager import ConfigManager

        _config_manager = ConfigManager()
    return _config_manager


def get_character_by_name(name: str):
    """Resolve a character configuration by name from the bound catalog or config fallback."""
    with _catalog_lock:
        catalog = _bound_character_catalog
    if catalog is not None:
        get_by_name = getattr(catalog, "get_by_name", None)
        if callable(get_by_name):
            found = get_by_name(name)
            if found is not None:
                return found
        folded = str(name or "").strip().casefold()
        list_all = getattr(catalog, "list_all", None)
        if folded and callable(list_all):
            for character in list_all():
                if str(getattr(character, "name", "")).strip().casefold() == folded:
                    return character
        if callable(get_by_name) or callable(list_all):
            return None
    try:
        return _get_config_manager().get_character_by_name(name)
    except ModuleNotFoundError:
        return None
