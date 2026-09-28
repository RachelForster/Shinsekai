"""统一读取角色当前形象类型的资源视图。

这是共享层唯一的取资源入口：提示词、语义索引、资源解析、条目语音、标签编辑
都要经过它，不直接读 ``character.sprites`` / ``character.emotion_tags``。
"""

from __future__ import annotations

from typing import Any

from config.schema import ModelSprites

STATIC_AVATAR_TYPE = "static"


def get_character_assets(character: Any, avatar_type: str) -> ModelSprites:
    """返回当前形象类型的 ``ModelSprites`` 视图，不复制或改写角色数据。

    - ``static``：返回根级 sprites / emotion_tags，model_path 为空。
    - 其他：返回 ``character.avatars[avatar_type]``（边界已校验未知 id）。
    """
    avatar_type = str(avatar_type or "").strip().lower() or STATIC_AVATAR_TYPE
    if avatar_type == STATIC_AVATAR_TYPE:
        return ModelSprites(
            model_path="",
            sprites=list(getattr(character, "sprites", None) or []),
            emotion_tags=getattr(character, "emotion_tags", "") or "",
        )
    avatars = getattr(character, "avatars", None) or {}
    if avatar_type not in avatars:
        raise KeyError(f"unknown avatar format: {avatar_type}")
    return avatars[avatar_type]
