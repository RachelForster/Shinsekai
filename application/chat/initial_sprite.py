"""Initial-sprite selection and presentation use cases."""

from __future__ import annotations

from typing import Any

from core.sprite.selection import (
    find_character_sprite_by_path as find_sprite_in_characters,
    resolve_initial_sprite_path,
    resolve_runtime_path,
    sprite_entry_path,
)


def _characters(config: Any) -> list[object]:
    return list(getattr(getattr(config, "config", None), "characters", None) or [])


def find_character_sprite_by_path(
    config: Any,
    raw_path: str,
) -> tuple[str, int] | None:
    return find_sprite_in_characters(_characters(config), raw_path)


def initial_sprite_path_for_characters(
    config: Any,
    raw_path: str,
    character_names: list[str] | None,
) -> str:
    selected_names = [
        name.strip()
        for name in (character_names or [])
        if isinstance(name, str) and name.strip()
    ]
    default_path = ""
    if selected_names:
        character = config.get_character_by_name(selected_names[0])
        sprites = getattr(character, "sprites", None) if character else None
        if isinstance(character, dict):
            sprites = character.get("sprites")
        if isinstance(sprites, (list, tuple)) and sprites:
            default_path = sprite_entry_path(sprites[0])

    return resolve_initial_sprite_path(
        _characters(config),
        raw_path,
        selected_names,
        default_path=default_path,
    )


def display_initial_sprite(
    raw_path: str,
    *,
    config: Any,
    ui_updates: Any,
) -> bool:
    if not raw_path:
        return False
    matched = find_character_sprite_by_path(config, raw_path)
    if matched is not None:
        character_name, sprite_index = matched
        ui_updates.update_sprite(character_name, sprite_index)
        return True

    resolved = resolve_runtime_path(raw_path)
    character_name = resolved.stem or "initial"
    return bool(
        ui_updates.update_sprite_from_path(
            str(resolved),
            character_name=character_name,
            scale=1.0,
        )
    )
