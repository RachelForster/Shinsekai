"""Project a selected character asset for both stage events and snapshots."""

from dataclasses import dataclass
from typing import Any

from application.media.resource_urls import ResourceUrls
from config.character_assets import get_character_assets, get_character_avatar_type
from core.sprite.selection import sprite_entry_path


@dataclass(frozen=True, slots=True)
class CharacterVisual:
    url: str
    avatar_type: str
    model_url: str
    scale: float

    def event_fields(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "avatarType": self.avatar_type,
            "modelUrl": self.model_url,
            "scale": self.scale,
        }

    def snapshot_fields(self) -> dict[str, Any]:
        fields = self.event_fields()
        fields["path"] = fields.pop("url")
        return fields


def resolve_character_visual(
    character: Any, index: int, urls: ResourceUrls
) -> CharacterVisual:
    assets = get_character_assets(character)
    if index < 0:
        raise IndexError("Sprite index must be non-negative")
    path = sprite_entry_path(assets.sprites[index])
    kind = get_character_avatar_type(character)
    if kind == "static":
        url, model_url = urls.media_url(path), ""
    else:
        if not assets.model_path:
            raise ValueError("Model entry path is empty")
        url = urls.avatar_url(assets.model_path, path)
        model_url = urls.avatar_url(assets.model_path, assets.model_path)
    scale = (
        character.get("sprite_scale", 1.0)
        if isinstance(character, dict)
        else getattr(character, "sprite_scale", 1.0)
    )
    return CharacterVisual(url, kind, model_url, float(scale or 1.0))
