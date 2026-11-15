"""Validation for the player character selected by a chat template."""

from config.schema import SELF_PERSONA_NAME, is_self_persona_name
from core.chat_history.text import sanitize_user_display_name


def resolve_player(config, names, value) -> str:
    name = str(value or '').strip()
    if not name:
        return ''
    character = config.get_character_by_name(name)
    if character is None:
        raise ValueError('主控人物必须是已选择的有效角色。')
    if not is_self_persona_name(character.name) and character.name not in names:
        raise ValueError('主控人物必须是已选择的有效角色。')
    return character.name


def resolve_player_display_name(config, player_name: str, user_display_name: str = "") -> str:
    """Display a chosen name while keeping the player and memory IDs stable."""
    if player_name and not is_self_persona_name(player_name):
        return player_name
    explicit = sanitize_user_display_name(user_display_name)
    if explicit:
        return explicit
    get_character = getattr(config, "get_character_by_name", None)
    persona = get_character(SELF_PERSONA_NAME) if callable(get_character) else None
    display_name = sanitize_user_display_name(getattr(persona, "display_name", ""))
    return display_name or player_name
