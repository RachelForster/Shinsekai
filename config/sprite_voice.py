from __future__ import annotations

from typing import Any, MutableMapping


VALID_SPRITE_VOICE_TYPES = {"fallback", "preset", "reference"}


def normalize_sprite_voice_types(character_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Normalize legacy sprite voice semantics while reading characters."""
    sprites = character_data.get("sprites")
    if not isinstance(sprites, list):
        return character_data
    for sprite in sprites:
        if not isinstance(sprite, dict):
            continue
        voice_type = str(sprite.get("voice_type") or "").strip().lower()
        if voice_type in VALID_SPRITE_VOICE_TYPES:
            sprite["voice_type"] = voice_type
            continue
        voice_path = str(sprite.get("voice_path") or "").strip()
        if not voice_path:
            continue
        voice_text = str(sprite.get("voice_text") or "").strip()
        sprite["voice_type"] = "reference" if voice_text else "fallback"
    return character_data
