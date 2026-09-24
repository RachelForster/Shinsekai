"""Validation for the player character selected by a chat template."""


def resolve_player(config, names, value) -> str:
    name = str(value or '').strip()
    if not name:
        return ''
    character = config.get_character_by_name(name)
    if character is None or character.name not in names:
        raise ValueError('主控人物必须是已选择的有效角色。')
    return character.name
