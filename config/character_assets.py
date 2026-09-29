"""统一读取角色当前形象类型的资源视图。

这是共享层唯一的取资源入口：提示词、语义索引、资源解析、条目语音、标签编辑
都要经过它，不直接读 ``character.sprites`` / ``character.emotion_tags``。
"""

from __future__ import annotations

from typing import Any, Iterator

from config.schema import ModelSprites

STATIC_AVATAR_TYPE = "static"


def _value(character: Any, field: str, default: Any = None) -> Any:
    return character.get(field, default) if isinstance(character, dict) else getattr(character, field, default)


def get_character_avatar_type(character: Any) -> str:
    return str(_value(character, "avatar_type", STATIC_AVATAR_TYPE) or "").strip().lower() or STATIC_AVATAR_TYPE


def get_character_assets(character: Any, avatar_type: str | None = None) -> ModelSprites:
    """返回当前形象类型的 ``ModelSprites`` 视图，不复制或改写角色数据。

    - ``static``：返回根级 sprites / emotion_tags，model_path 为空。
    - 其他：返回 ``character.avatars[avatar_type]``（边界已校验未知 id）。
    - 不传 avatar_type：读取角色当前选中的类型。
    """
    avatar_type = (
        get_character_avatar_type(character)
        if avatar_type is None
        else str(avatar_type or "").strip().lower() or STATIC_AVATAR_TYPE
    )
    if avatar_type == STATIC_AVATAR_TYPE:
        # This is a read-only view, not a configuration validation boundary.
        # Revalidation would clone dict sprites and reject legacy lightweight objects.
        return ModelSprites.model_construct(
            model_path="",
            sprites=list(_value(character, "sprites", None) or []),
            emotion_tags=_value(character, "emotion_tags", "") or "",
        )
    avatars = _value(character, "avatars", None) or {}
    if avatar_type not in avatars:
        raise KeyError(f"unknown avatar format: {avatar_type}")
    value = avatars[avatar_type]
    return ModelSprites.model_construct(**value) if isinstance(value, dict) else value


def iter_character_asset_banks(character: Any) -> Iterator[tuple[str, ModelSprites]]:
    """Include inactive banks when recognizing paths saved before a format switch."""
    yield STATIC_AVATAR_TYPE, get_character_assets(character, STATIC_AVATAR_TYPE)
    for kind in _value(character, "avatars", None) or {}:
        yield kind, get_character_assets(character, kind)
