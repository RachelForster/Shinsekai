"""Strategies for resolving a dialog message to a configured sprite."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

from .models import SpriteLookupRequest, SpriteMatch

logger = logging.getLogger(__name__)


class SpriteLookupStrategy(ABC):
    """Select a sprite for a character dialog message."""

    @abstractmethod
    def lookup(self, request: SpriteLookupRequest) -> SpriteMatch:
        """Return the selected sprite and its voice metadata."""


class ConfigSpriteLookupStrategy(SpriteLookupStrategy):
    """Resolve the one-based sprite id stored in the dialog message."""

    def __init__(
        self, characters_path: str | Path = "data/config/characters.yaml"
    ) -> None:
        self._characters_path = Path(characters_path)

    def lookup(self, request: SpriteLookupRequest) -> SpriteMatch:
        asset_id = str(
            request.message.asset_id if request.message.asset_id is not None else "-1"
        )
        sprites = getattr(request.character, "sprites", None) or []
        try:
            index = int(asset_id) - 1
            if index < 0 or index >= len(sprites):
                raise IndexError
            sprite = sprites[index]
        except (TypeError, ValueError, IndexError):
            return SpriteMatch(asset_id=asset_id)

        voice_type = self._value(sprite, "voice_type")
        voice_path = str(self._value(sprite, "voice_path", "") or "").strip()
        voice_text = str(self._value(sprite, "voice_text", "") or "")

        yaml_voice = self._read_voice_config(
            str(getattr(request.character, "name", "")), index
        )
        if yaml_voice is not None and yaml_voice[1]:
            voice_type, voice_path, voice_text = yaml_voice

        return SpriteMatch(
            asset_id=asset_id,
            index=index,
            sprite=sprite,
            voice_type=voice_type,
            voice_path=str(voice_path or "").strip(),
            voice_text=str(voice_text or ""),
        )

    def _read_voice_config(
        self, character_name: str, sprite_index: int
    ) -> tuple[str | None, str, str] | None:
        """Read mutable voice fields from disk instead of a process-local cache."""
        if not self._characters_path.is_file():
            return None
        try:
            with self._characters_path.open("r", encoding="utf-8") as file:
                characters = yaml.safe_load(file) or []
            for character in characters:
                if (
                    not isinstance(character, dict)
                    or character.get("name") != character_name
                ):
                    continue
                sprites = character.get("sprites") or []
                if 0 <= sprite_index < len(sprites):
                    sprite = sprites[sprite_index]
                    if isinstance(sprite, dict):
                        return (
                            sprite.get("voice_type"),
                            str(sprite.get("voice_path") or "").strip(),
                            str(sprite.get("voice_text") or ""),
                        )
                return None
        except Exception:
            logger.debug(
                "Failed to read sprite voice metadata for character=%s sprite_index=%s",
                character_name,
                sprite_index,
                exc_info=True,
            )
        return None

    @staticmethod
    def _value(sprite: Any, key: str, default: Any = None) -> Any:
        if isinstance(sprite, dict):
            return sprite.get(key, default)
        return getattr(sprite, key, default)
