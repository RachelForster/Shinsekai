"""Project a selected character asset for both stage events and snapshots."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from application.media.resource_urls import ResourceUrls
from config.character_assets import get_character_assets, get_character_avatar_type
from config.config_manager import character_name_key
from core.sprite.mouth.manifest import valid_mouth_sync
from core.sprite.selection import resolve_runtime_path, sprite_entry_path
from core.sprite.transition_presentation import transition_presentation
from core.sprite.transitions import field, valid_transitions


def image_visual_identity(raw_path: str) -> str:
    """Identify an unowned image before transport URLs and display labels are added."""
    path = os.path.normcase(str(resolve_runtime_path(raw_path))).replace("\\", "/")
    return f"image:{path}"


def _resolve_portrait_crop(character: Any, sprite_entry: Any) -> dict[str, float] | None:
    sprite_crop = (
        sprite_entry.get("portrait_crop")
        if isinstance(sprite_entry, dict)
        else getattr(sprite_entry, "portrait_crop", None)
    )
    character_crop = (
        character.get("portrait_crop")
        if isinstance(character, dict)
        else getattr(character, "portrait_crop", None)
    )
    crop = sprite_crop or character_crop
    if crop is None:
        return None
    raw = (
        crop.model_dump()
        if hasattr(crop, "model_dump")
        else (dict(crop) if isinstance(crop, dict) else None)
    )
    if not raw:
        return None
    return {
        "x": float(raw.get("x", 0.5)),
        "y": float(raw.get("y", 0.2)),
        "zoom": float(raw.get("zoom", 1.0)),
    }


@dataclass(frozen=True, slots=True)
class CharacterVisual:
    url: str
    avatar_type: str
    model_url: str
    scale: float
    identity_key: str = ""
    transitions: tuple[dict[str, Any], ...] = ()
    mouth_sync: str = ""
    portrait_crop: dict[str, float] | None = None

    def event_fields(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "avatarType": self.avatar_type,
            "modelUrl": self.model_url,
            "scale": self.scale,
            "identityKey": self.identity_key,
            **({"transitions": list(self.transitions)} if self.transitions else {}),
            **({"mouthSync": self.mouth_sync} if self.mouth_sync else {}),
            **({"portraitCrop": dict(self.portrait_crop)} if self.portrait_crop else {}),
        }

    def snapshot_fields(self) -> dict[str, Any]:
        fields = self.event_fields()
        fields.pop("transitions", None)
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
    name = (
        character.get("name", "")
        if isinstance(character, dict)
        else getattr(character, "name", "")
    )
    identity_key = f"character:{character_name_key(name)}" if name else ""
    transitions = (
        tuple(
            {
                "fromUrl": urls.media_url(field(edge, "from_path")),
                "url": urls.media_url(field(edge, "path")),
                **(
                    {"presentation": presentation}
                    if (
                        presentation := transition_presentation(
                            field(edge, "from_path"), field(edge, "path"), path
                        )
                    )
                    else {}
                ),
            }
            for edge in valid_transitions(character)
            if kind == "static" and field(edge, "to_path") == path
        )
        if kind == "static"
        else ()
    )
    mouth_sync = valid_mouth_sync(assets.sprites[index]) if kind == "static" else ""
    if mouth_sync:
        try:
            mouth_sync = Path(mouth_sync).resolve().relative_to(Path.cwd().resolve()).as_posix()
        except ValueError:
            mouth_sync = ""
    portrait_crop = (
        _resolve_portrait_crop(character, assets.sprites[index])
        if kind == "static"
        else None
    )
    return CharacterVisual(
        url, kind, model_url, float(scale or 1.0), identity_key, transitions,
        mouth_sync, portrait_crop,
    )
