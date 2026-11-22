"""Outfit/costume sprite group mutations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional

from config.character_ops.profile import resolve_mutable_character
from config.character_ops.target import CharacterPersistenceTarget, _with_character_lock
from config.schema import Character, DEFAULT_SPRITE_GROUP
from config.sprite_groups import (
    normalize_sprite_group,
    normalize_sprite_group_list,
    set_sprite_group_value,
    sprite_group_of,
)


@_with_character_lock
def save_character_sprite_groups(
    target: CharacterPersistenceTarget,
    name: str,
    *,
    sprite_groups: Optional[list[str]] = None,
    default_sprite_group: Optional[str] = None,
    fallback_to_default_group: Optional[bool] = None,
    assignments: Optional[dict[int, Optional[str]]] = None,
    rename_from: Optional[str] = None,
    rename_to: Optional[str] = None,
    delete_group: Optional[str] = None,
    avatar_type: Optional[str] = None,
) -> Character:
    """Atomically save sprite outfit groups, assignments, renames, and deletions."""
    if not name or not str(name).strip():
        raise ValueError("角色名称不能为空")
    character = resolve_mutable_character(target, str(name).strip())
    if character is None:
        raise KeyError(f"找不到角色: {name}")

    target_avatar = (
        str(character.avatar_type or "static").strip().lower()
        if avatar_type is None
        else str(avatar_type or "static").strip().lower()
    ) or "static"

    next_avatars = deepcopy(character.avatars or {})
    if target_avatar == "static":
        bank_sprites = list(character.sprites or [])
    else:
        if target_avatar not in next_avatars:
            raise KeyError(f"未知形象类型: {target_avatar}")
        bank_sprites = list(next_avatars[target_avatar].sprites or [])

    next_groups = normalize_sprite_group_list(
        sprite_groups if sprite_groups is not None else character.sprite_groups
    )
    next_default = (
        str(default_sprite_group).strip()
        if default_sprite_group is not None
        else str(character.default_sprite_group or "").strip()
    )
    next_fallback = (
        bool(fallback_to_default_group)
        if fallback_to_default_group is not None
        else bool(character.fallback_to_default_group)
    )

    if rename_from is not None and rename_to is not None:
        src = normalize_sprite_group(rename_from)
        dst = normalize_sprite_group(rename_to)
        if src == DEFAULT_SPRITE_GROUP:
            raise ValueError("默认分组不可重命名")
        if src != dst:
            bank_sprites = [
                set_sprite_group_value(sp, dst) if sprite_group_of(sp) == src else sp
                for sp in bank_sprites
            ]
            next_groups = normalize_sprite_group_list(
                [dst if g == src else g for g in [*next_groups, dst]]
            )
            if next_default and normalize_sprite_group(next_default) == src:
                next_default = "" if dst == DEFAULT_SPRITE_GROUP else dst

    if delete_group is not None:
        removed = normalize_sprite_group(delete_group)
        if removed == DEFAULT_SPRITE_GROUP:
            raise ValueError("默认分组不可删除")
        bank_sprites = [
            set_sprite_group_value(sp, None) if sprite_group_of(sp) == removed else sp
            for sp in bank_sprites
        ]
        next_groups = [g for g in next_groups if g != removed]
        if next_default and normalize_sprite_group(next_default) == removed:
            next_default = ""

    if assignments:
        added_groups: list[str] = []
        for raw_idx, group_val in assignments.items():
            idx = int(raw_idx)
            if not 0 <= idx < len(bank_sprites):
                raise ValueError(f"立绘编号越界: {idx}")
            bank_sprites[idx] = set_sprite_group_value(bank_sprites[idx], group_val)
            norm = normalize_sprite_group(group_val)
            if norm != DEFAULT_SPRITE_GROUP and norm not in next_groups and norm not in added_groups:
                added_groups.append(norm)
        if added_groups:
            next_groups = normalize_sprite_group_list([*next_groups, *added_groups])

    if next_default and normalize_sprite_group(next_default) == DEFAULT_SPRITE_GROUP:
        next_default = DEFAULT_SPRITE_GROUP

    updates: dict[str, Any] = {
        "sprite_groups": next_groups,
        "default_sprite_group": next_default,
        "fallback_to_default_group": next_fallback,
    }
    if target_avatar == "static":
        updates["sprites"] = bank_sprites
    else:
        next_avatars[target_avatar] = next_avatars[target_avatar].model_copy(
            update={"sprites": bank_sprites}
        )
        updates["avatars"] = next_avatars

    updated = character.model_copy(update=updates)
    target.save_character(updated)
    return updated


__all__ = ["save_character_sprite_groups"]
