"""Validation for the player character selected by a chat template."""

from typing import Any

from config.schema import (
    SELF_PERSONA_NAME,
    find_self_persona,
    is_self_persona,
    is_self_persona_id,
    is_self_persona_name,
)
from core.chat_history.text import sanitize_user_display_name


def _get_self_persona(config: Any) -> Any | None:
    getter_self = getattr(config, "get_self_persona", None)
    if callable(getter_self):
        return getter_self()
    characters = getattr(getattr(config, "config", None), "characters", None)
    if characters is not None:
        found = find_self_persona(characters)
        if found is not None:
            return found
    getter = getattr(config, "get_character_by_name", None)
    return getter(SELF_PERSONA_NAME) if callable(getter) else None


def resolve_player(config, names, value) -> str:
    name = str(value or "").strip()
    if not name:
        return ""
    character = _get_self_persona(config) if is_self_persona_id(name) else config.get_character_by_name(name)
    if character is None:
        raise ValueError("主控人物必须是已选择的有效角色。")
    if not is_self_persona(character) and character.name not in names:
        raise ValueError("主控人物必须是已选择的有效角色。")
    return character.name


def resolve_player_display_name(config, player_name: str, user_display_name: str = "") -> str:
    """Display a chosen name while keeping the player and memory IDs stable."""
    cleaned_player = str(player_name or "").strip()
    get_character = getattr(config, "get_character_by_name", None)
    if cleaned_player:
        selected = (
            _get_self_persona(config)
            if is_self_persona_id(cleaned_player)
            else (get_character(cleaned_player) if callable(get_character) else None)
        )
        if selected is not None:
            if not is_self_persona(selected):
                return selected.name
            if not is_self_persona_name(getattr(selected, "name", "")):
                return sanitize_user_display_name(selected.name) or selected.name
        elif not is_self_persona_name(cleaned_player) and not is_self_persona_id(cleaned_player):
            return cleaned_player

    explicit = sanitize_user_display_name(user_display_name)
    if explicit:
        return explicit

    persona = _get_self_persona(config)
    if persona is not None:
        persona_name = str(getattr(persona, "name", "") or "").strip()
        if persona_name and not is_self_persona_name(persona_name):
            return sanitize_user_display_name(persona_name) or persona_name
        display_name = sanitize_user_display_name(getattr(persona, "display_name", ""))
        return display_name or cleaned_player
    return cleaned_player
