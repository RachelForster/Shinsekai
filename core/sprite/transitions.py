"""Validate directed transitions without relying on mutable sprite indices."""

from config.sprite_files import sprite_field as field, sprite_fingerprint
from core.sprite.selection import resolve_runtime_path, sprite_entry_path

TRANSITION_FRAME_COUNT = 22


def valid_transitions(character):
    paths = {sprite_entry_path(sprite) for sprite in field(character, "sprites", [])}
    for edge in field(character, "sprite_transitions", []) or []:
        start, end = field(edge, "from_path"), field(edge, "to_path")
        if start == end or start not in paths or end not in paths:
            continue
        try:
            clip = resolve_runtime_path(field(edge, "path", ""))
            if (
                clip.suffix.lower() == ".webm"
                and clip.is_file()
                and sprite_fingerprint(start) == field(edge, "from_fingerprint")
                and sprite_fingerprint(end) == field(edge, "to_fingerprint")
            ):
                yield edge
        except (OSError, ValueError):
            continue
