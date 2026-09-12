"""Resolve character sprites and their mutable voice metadata."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml

from core.media.asset_tags import tag_contents

from ..lookup import AssetCandidate, AssetLookupResult
from .asset import AssetResolver, ResolvedAsset, asset_candidates

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResolvedSpriteAsset(ResolvedAsset):
    """A configured sprite enriched with voice playback metadata."""

    voice_type: str | None = None
    voice_path: str = ""
    voice_text: str = ""

    @property
    def sprite(self) -> Any | None:
        return self.value


class SpriteAssetResolver:
    """Resolve a sprite id and attach its current voice configuration."""

    def __init__(
        self, characters_path: str | Path = "data/config/characters.yaml"
    ) -> None:
        self._characters_path = Path(characters_path)
        self._resolver = AssetResolver()

    def candidates(self, character: Any) -> tuple[AssetCandidate, ...]:
        sprites = getattr(character, "sprites", None) or []
        tags = tag_contents(getattr(character, "emotion_tags", ""), len(sprites))
        return asset_candidates(sprites, tags=tags)

    def resolve(
        self,
        character: Any,
        candidates: Sequence[AssetCandidate],
        result: AssetLookupResult,
    ) -> ResolvedSpriteAsset:
        resolved = self._resolver.resolve(candidates, result)
        if not resolved.found:
            return ResolvedSpriteAsset(asset_id=resolved.asset_id)

        sprite = resolved.value
        voice_type = self._value(sprite, "voice_type")
        voice_path = str(self._value(sprite, "voice_path", "") or "").strip()
        voice_text = str(self._value(sprite, "voice_text", "") or "")
        yaml_voice = self._read_voice_config(
            str(getattr(character, "name", "")), int(resolved.index)
        )
        if yaml_voice is not None and yaml_voice[1]:
            voice_type, voice_path, voice_text = yaml_voice
        return ResolvedSpriteAsset(
            asset_id=resolved.asset_id,
            index=resolved.index,
            value=sprite,
            path=resolved.path,
            voice_type=voice_type,
            voice_path=voice_path,
            voice_text=voice_text,
        )

    def _read_voice_config(
        self, character_name: str, sprite_index: int
    ) -> tuple[str | None, str, str] | None:
        if not self._characters_path.is_file():
            return None
        try:
            with self._characters_path.open("r", encoding="utf-8") as file:
                characters = yaml.safe_load(file) or []
            for character in characters:
                if not isinstance(character, dict) or character.get("name") != character_name:
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
