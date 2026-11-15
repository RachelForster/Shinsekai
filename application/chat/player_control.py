"""Validation for the player character selected by a chat template."""

from config.schema import is_self_persona_name


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
