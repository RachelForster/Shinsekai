from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from sdk.path_contract import (
    project_root as configured_project_root,
    resolve_project_path,
    resolve_runtime_asset_path,
    validate_exact_path_text,
)


_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_WINDOWS_DRIVE_RELATIVE_RE = re.compile(r"^[A-Za-z]:[^\\/]")


def sprite_entry_path(sprite: object) -> str:
    if isinstance(sprite, dict):
        return str(sprite.get("path") or "")
    return str(getattr(sprite, "path", "") or "")


def _character_name(character: object) -> str:
    if isinstance(character, dict):
        return str(character.get("name") or "")
    return str(getattr(character, "name", "") or "")


def _character_sprites(character: object) -> list[Any]:
    sprites = character.get("sprites") if isinstance(character, dict) else getattr(character, "sprites", None)
    return list(sprites) if isinstance(sprites, (list, tuple)) else []


def resolve_runtime_path(raw_path: str, *, project_root: str | Path | None = None) -> Path:
    root = (
        resolve_project_path(".", root=project_root)
        if project_root is not None
        else configured_project_root()
    )
    return resolve_runtime_asset_path(raw_path, root=root)


def _sprite_path_key(raw_path: str, *, project_root: str | Path | None = None) -> str:
    """Normalize path identity using the host filesystem's case semantics."""
    raw = str(raw_path or "")
    if (
        not raw
        or raw != raw.strip()
        or _WINDOWS_DRIVE_RELATIVE_RE.match(raw)
        or any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in raw
        )
    ):
        raise ValueError("sprite path is empty, ambiguous, or non-portable")
    validate_exact_path_text(
        raw,
        field="sprite path",
        allow_non_native_absolute=True,
    )
    if _WINDOWS_ABSOLUTE_RE.match(raw) or raw.startswith(("\\\\", "//")):
        # A persisted Windows path can still be compared on another host
        # without anchoring it to that host's cwd.  Operational access remains
        # strict in ``resolve_runtime_path``.
        return os.path.normcase(raw).replace("\\", "/")
    return os.path.normcase(
        str(resolve_runtime_path(raw, project_root=project_root))
    ).replace("\\", "/")


def find_character_sprite_by_path(
    config: Any,
    raw_path: str,
    *,
    project_root: str | Path | None = None,
) -> tuple[str, int] | None:
    if not raw_path:
        return None
    target_key = _sprite_path_key(raw_path, project_root=project_root)
    for character in getattr(config.config, "characters", None) or []:
        for index, sprite in enumerate(_character_sprites(character)):
            sprite_path = sprite_entry_path(sprite)
            if not sprite_path:
                continue
            try:
                candidate_key = _sprite_path_key(
                    sprite_path,
                    project_root=project_root,
                )
            except (OSError, RuntimeError, ValueError):
                continue
            if candidate_key == target_key:
                return _character_name(character), index
    return None


def initial_sprite_path_for_characters(
    config: Any,
    raw_path: str,
    character_names: list[str] | None,
    *,
    project_root: str | Path | None = None,
) -> str:
    selected_names = [name.strip() for name in (character_names or []) if isinstance(name, str) and name.strip()]
    default_path = ""
    if selected_names:
        character = config.get_character_by_name(selected_names[0])
        sprites = _character_sprites(character) if character else []
        if sprites:
            default_path = sprite_entry_path(sprites[0])

    requested_path = str(raw_path or "")
    if not requested_path:
        return default_path
    matched = find_character_sprite_by_path(config, requested_path, project_root=project_root)
    if matched is not None and matched[0] not in selected_names:
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
