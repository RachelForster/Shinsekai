from __future__ import annotations

from typing import Any, MutableMapping


def normalize_sprite_voice_types(character_data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Normalize legacy sprite voice semantics while reading characters."""
    sprites = character_data.get("sprites")
    if not isinstance(sprites, list):
        return character_data
    for sprite in sprites:
        if not isinstance(sprite, dict):
            continue
        voice_path = str(sprite.get("voice_path") or "").strip()
        if not voice_path:
            continue
        voice_text = str(sprite.get("voice_text") or "").strip()
        if voice_text:
            sprite["voice_type"] = str(sprite.get("voice_type") or "reference").strip().lower() or "reference"
        else:
            sprite["voice_type"] = "fallback"
    return character_data
