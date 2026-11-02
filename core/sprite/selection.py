from __future__ import annotations

from collections.abc import Iterable
import os
from pathlib import Path
from config.character_assets import get_character_assets, iter_character_asset_banks

from sdk.path_utils import normalize_path_identity


def sprite_entry_path(sprite: object) -> str:
    if isinstance(sprite, dict):
        return str(sprite.get("path") or "")
    return str(getattr(sprite, "path", "") or "")


def _character_name(character: object) -> str:
    if isinstance(character, dict):
        return str(character.get("name") or "")
    return str(getattr(character, "name", "") or "")


def resolve_runtime_path(raw_path: str) -> Path:
    return normalize_path_identity(raw_path, field="initial sprite path")


def _sprite_path_key(raw_path: str) -> str:
    """Normalize path identity using the host filesystem's case semantics."""
    return os.path.normcase(str(resolve_runtime_path(raw_path))).replace("\\", "/")


def find_character_sprite_by_path(
    characters: Iterable[object],
    raw_path: str,
    *,
    include_inactive: bool = False,
) -> tuple[str, int] | None:
    if not raw_path:
        return None
    target_key = _sprite_path_key(raw_path)
    for character in characters:
        banks = (
            (assets for _, assets in iter_character_asset_banks(character))
            if include_inactive
            else (get_character_assets(character),)
        )
        for bank in banks:
            for index, sprite in enumerate(bank.sprites):
                sprite_path = sprite_entry_path(sprite)
                if sprite_path and _sprite_path_key(sprite_path) == target_key:
                    return _character_name(character), index
    return None


def resolve_initial_sprite_path(
    characters: Iterable[object],
    raw_path: str,
    character_names: Iterable[object] | None,
    *,
    default_path: str = "",
) -> str:
    selected_names = [
        name.strip()
        for name in (character_names or [])
        if isinstance(name, str) and name.strip()
    ]

    requested_path = str(raw_path or "").strip()
    if not requested_path:
        return default_path
    characters = list(characters)
    matched = find_character_sprite_by_path(characters, requested_path)
    if matched is not None:
        return requested_path if matched[0] in selected_names else default_path
    if find_character_sprite_by_path(characters, requested_path, include_inactive=True) is not None:
        return default_path
    return requested_path
