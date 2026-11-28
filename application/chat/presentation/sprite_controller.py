"""Stage sprite slot LRU, portrait, reaction, and motion controller."""

from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from application.media.resource_urls import ResourceUrls
from config.character_assets import get_character_assets
from config.config_manager import character_name_key
from core.messaging.stage_effects import (
    character_motion_duration_ms,
    normalize_character_motion,
)
from core.paths import resource_path
from core.sprite.selection import resolve_runtime_path, sprite_entry_path

from .character_visual import _resolve_portrait_crop, image_visual_identity


class StageSpriteController:
    """Own sprite slot allocation and emit sprite, portrait, reaction, and motion events."""

    def __init__(
        self,
        *,
        emit: Callable[[dict[str, Any]], None],
        resource_urls: ResourceUrls,
        max_sprite_slots: int = 3,
        character_lookup: Callable[[str], Any],
        visual_resolver: Callable[[Any, int | None, ResourceUrls], Any],
    ) -> None:
        self._emit = emit
        self._resource_urls = resource_urls
        try:
            normalized_slot_count = int(max_sprite_slots)
        except (TypeError, ValueError):
            normalized_slot_count = 3
        self.max_sprite_slots = max(1, normalized_slot_count)
        self._character_lookup = character_lookup
        self._visual_resolver = visual_resolver
        self.sprite_lru: OrderedDict[str, int] = OrderedDict()

    def get_or_create_slot(self, character_name: str) -> int:
        """Mirror the legacy Qt SpritePanel character-to-slot LRU."""
        if character_name in self.sprite_lru:
            slot = self.sprite_lru.pop(character_name)
            self.sprite_lru[character_name] = slot
            return slot

        used_slots = set(self.sprite_lru.values())
        if len(used_slots) < self.max_sprite_slots:
            slot = next(
                index for index in range(self.max_sprite_slots) if index not in used_slots
            )
        else:
            _oldest_character, slot = self.sprite_lru.popitem(last=False)
        self.sprite_lru[character_name] = slot
        return slot

    def clear_slots(self) -> None:
        self.sprite_lru.clear()

    def resolve_replay_sprite(self, character: Any, preferred_index: int | None):
        assets = get_character_assets(character)
        if assets.model_path and not resource_path(assets.model_path).is_file():
            return None
        indices = list(range(len(assets.sprites)))
        if preferred_index in indices:
            indices.remove(preferred_index)
            indices.insert(0, preferred_index)
        for index in indices:
            path = sprite_entry_path(assets.sprites[index])
            try:
                if not path or not resource_path(path).is_file():
                    continue
                return self._visual_resolver(character, index, self._resource_urls)
            except (OSError, ValueError):
                continue
        return None

    def update_sprite(
        self,
        character_name: str,
        sprite_id: int | None,
        *,
        slot: int | None = None,
        display_name: str = "",
    ) -> None:
        try:
            character_config = self._character_lookup(character_name)
            if character_config is None:
                raise ValueError(f"未找到角色配置: {character_name}")
            visual = (
                self.resolve_replay_sprite(character_config, sprite_id)
                if slot is not None
                else self._visual_resolver(
                    character_config, sprite_id, self._resource_urls
                )
            )
            if visual is None:
                return
        except Exception as e:
            print(f"StreamingUIUpdateManager: 立绘解析失败: {e}")
            return
        stage_name = (
            str(display_name or "").strip()
            or str(getattr(character_config, "name", "") or character_name)
        )
        display_slot = self.get_or_create_slot(stage_name) if slot is None else slot
        self._emit(
            {
                "type": "sprite.show",
                "characterName": stage_name,
                **visual.event_fields(),
                "slot": display_slot,
            }
        )

    def update_player_portrait(self, character_name: str, sprite_id: int) -> None:
        try:
            character_config = self._character_lookup(character_name)
            if character_config is None:
                raise ValueError(f"未找到角色配置: {character_name}")
            sprite = character_config.sprites[sprite_id]
            image_path = str(
                Path(sprite.get("path", ""))
                if isinstance(sprite, dict)
                else Path(getattr(sprite, "path", ""))
            )
        except Exception as error:
            print(f"StreamingUIUpdateManager: 主控头像解析失败: {error}")
            return
        crop = (
            sprite.get("portrait_crop")
            if isinstance(sprite, dict)
            else getattr(sprite, "portrait_crop", None)
        )
        crop = crop or getattr(character_config, "portrait_crop", None)
        self._emit(
            {
                "type": "player.portrait.show",
                "characterName": character_name,
                "url": self._resource_urls.media_url(image_path),
                "crop": (
                    crop.model_dump()
                    if hasattr(crop, "model_dump")
                    else (crop or {"x": 0.5, "y": 0.2, "zoom": 1})
                ),
            }
        )

    def update_sprite_from_path(
        self,
        image_path: str,
        *,
        character_name: str = "",
        scale: float = 1.0,
    ) -> bool:
        path = str(image_path or "").strip()
        if not path:
            return False
        resolved_character_name = character_name or Path(path).stem or "initial"
        portrait_crop: dict[str, float] | None = None
        if character_name:
            try:
                character_config = self._character_lookup(character_name)
                if character_config is not None:
                    target_norm = os.path.normcase(str(resolve_runtime_path(path)))
                    matched_sprite = next(
                        (
                            item
                            for item in getattr(character_config, "sprites", []) or []
                            if os.path.normcase(
                                str(resolve_runtime_path(sprite_entry_path(item)))
                            )
                            == target_norm
                        ),
                        None,
                    )
                    portrait_crop = _resolve_portrait_crop(
                        character_config, matched_sprite
                    )
            except Exception:
                portrait_crop = None
        self._emit(
            {
                "type": "sprite.show",
                "characterName": resolved_character_name,
                "identityKey": image_visual_identity(path),
                "url": self._resource_urls.media_url(path),
                "scale": float(scale or 1.0),
                "slot": self.get_or_create_slot(resolved_character_name),
                "avatarType": "static",
                "modelUrl": "",
                **({"portraitCrop": portrait_crop} if portrait_crop else {}),
            }
        )
        return True

    def remove_character_sprite(self, character_name: str) -> None:
        name_key = character_name_key(character_name)
        character_name = next(
            (name for name in self.sprite_lru if character_name_key(name) == name_key),
            character_name,
        )
        self.sprite_lru.pop(character_name, None)
        self._emit({"type": "sprite.remove", "characterName": character_name})

    def post_sprite_reaction(
        self,
        character_name: str,
        text: str,
        *,
        duration_ms: int = 3600,
    ) -> None:
        cleaned = str(text or "").strip()
        if not cleaned:
            return
        self._emit(
            {
                "type": "sprite.reaction",
                "characterName": str(character_name or "").strip(),
                "text": cleaned[:80],
                "durationMs": max(800, int(duration_ms or 3600)),
            }
        )

    def post_sprite_motion(self, character_name: str, motion: str) -> None:
        normalized = normalize_character_motion(motion)
        name = str(character_name or "").strip()
        if not normalized or not name:
            return
        self._emit(
            {
                "type": "sprite.motion",
                "characterName": name,
                "motion": normalized,
                "durationMs": character_motion_duration_ms(normalized),
            }
        )
