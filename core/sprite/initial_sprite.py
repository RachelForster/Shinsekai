from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def sprite_entry_path(sprite: object) -> str:
    if isinstance(sprite, dict):
        return str(sprite.get("path") or "")
    return str(getattr(sprite, "path", "") or "")


def resolve_runtime_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve(strict=False)


def find_character_sprite_by_path(
    config: Any,
    raw_path: str,
) -> tuple[str, int] | None:
    if not raw_path:
        return None
    target_key = os.path.normcase(str(resolve_runtime_path(raw_path)))
    for character in config.config.characters:
        for index, sprite in enumerate(character.sprites or []):
            sprite_path = sprite_entry_path(sprite)
            if not sprite_path:
                continue
            candidate_key = os.path.normcase(str(resolve_runtime_path(sprite_path)))
            if candidate_key == target_key:
                return character.name, index
    return None


def initial_sprite_path_for_characters(
    config: Any,
    raw_path: str,
    character_names: list[str] | None,
) -> str:
    selected_names = [str(name).strip() for name in (character_names or []) if str(name).strip()]
    default_path = ""
    if selected_names:
        character = config.get_character_by_name(selected_names[0])
        if character and character.sprites:
            default_path = sprite_entry_path(character.sprites[0])

    requested_path = str(raw_path or "").strip()
    if not requested_path:
        return default_path
    matched = find_character_sprite_by_path(config, requested_path)
    if matched is not None and selected_names and matched[0] not in selected_names:
        return default_path
    return requested_path


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
