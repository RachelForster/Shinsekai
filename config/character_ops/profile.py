"""Model-merge character profile CRUD, rename validation, and lightweight scalar mutations."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
import shutil
from typing import Any

from config.character_ops.relations import (
    parse_relation_graph,
    rename_relation_graph_owner,
)
from config.character_ops.target import (
    CharacterPersistenceTarget,
    CharacterProfileError,
)
from config.schema import (
    Character,
    PortraitCrop,
    SELF_PERSONA_NAME,
    SELF_PERSONA_SPRITE_PREFIX,
    is_self_persona_name,
)
from config.sprite_groups import normalize_sprite_group_list, set_sprite_group_value

_PROTECTED_PROFILE_FIELDS = frozenset(
    {"id", "sprites", "sprite_transitions", "is_builtin", "pinned", "undeletable"}
)


def clamp_portrait_sprite_index(value: Any, sprite_count: int) -> int:
    """Clamp the selected portrait sprite index to the valid sprite range."""
    try:
        index = int(value or 0)
    except (TypeError, ValueError):
        index = 0
    if sprite_count <= 0:
        return 0
    return max(0, min(index, sprite_count - 1))


def resolve_mutable_character(
    target: CharacterPersistenceTarget,
    name: str,
) -> Character | None:
    """Resolve an existing character for mutation, materializing self-persona if needed."""
    if is_self_persona_name(name):
        return target.ensure_self_persona()
    return target.get_by_name(name)


def _normalize_patch_value(key: str, value: Any) -> Any:
    if key == "sprite_groups" and value is not None:
        return normalize_sprite_group_list(value)
    if key == "default_sprite_group" and value is not None:
        return str(value).strip()
    if key == "relation_graph" and value is not None:
        return parse_relation_graph(value)
    return value


def _apply_sprite_patch_metadata(
    sprites: list[Any],
    patch_sprites: Any,
    sprite_portrait_crops: Mapping[int, Any] | None,
    sprite_group_map: Mapping[int, str | None] | None,
) -> list[Any]:
    merged_sprites = list(deepcopy(sprites or []))
    if isinstance(patch_sprites, list):
        for idx, item in enumerate(patch_sprites):
            if not (0 <= idx < len(merged_sprites) and isinstance(item, Mapping)):
                continue
            if "portrait_crop" in item:
                raw_crop = item["portrait_crop"]
                crop_val = PortraitCrop.model_validate(raw_crop) if raw_crop else None
                sp = merged_sprites[idx]
                merged_sprites[idx] = (
                    {**sp, "portrait_crop": crop_val.model_dump() if crop_val else None}
                    if isinstance(sp, dict)
                    else sp.model_copy(update={"portrait_crop": crop_val})
                )
            if "group" in item:
                merged_sprites[idx] = set_sprite_group_value(merged_sprites[idx], item.get("group"))
    for idx, crop in (sprite_portrait_crops or {}).items():
        if 0 <= idx < len(merged_sprites):
            crop_val = PortraitCrop.model_validate(crop) if isinstance(crop, Mapping) else crop
            sp = merged_sprites[idx]
            merged_sprites[idx] = (
                {**sp, "portrait_crop": crop_val.model_dump() if crop_val else None}
                if isinstance(sp, dict)
                else sp.model_copy(update={"portrait_crop": crop_val})
            )
    for idx, group_val in (sprite_group_map or {}).items():
        if 0 <= idx < len(merged_sprites):
            merged_sprites[idx] = set_sprite_group_value(merged_sprites[idx], group_val)
    return merged_sprites


def _validate_prefix_uniqueness(
    target: CharacterPersistenceTarget,
    prefix: str,
    *,
    raw_name: str,
    trimmed_edit_as: str,
    existing: Character | None,
) -> None:
    if not prefix:
        return
    owner_ref_name = existing.name if existing is not None else (trimmed_edit_as or raw_name)
    if prefix == SELF_PERSONA_SPRITE_PREFIX and not is_self_persona_name(owner_ref_name):
        raise CharacterProfileError(
            f"立绘目录名「{prefix}」已被系统角色「{SELF_PERSONA_NAME}」占用！"
        )
    for candidate in target.list_all():
        c_prefix = str(getattr(candidate, "sprite_prefix", "") or "").strip()
        if not c_prefix or c_prefix != prefix:
            continue
        if existing is not None:
            same_id = (
                getattr(candidate, "id", None) is not None
                and getattr(candidate, "id", None) == getattr(existing, "id", None)
            )
            if candidate is not existing and not same_id and candidate.name != existing.name:
                raise CharacterProfileError(
                    f"立绘目录名「{prefix}」已被角色「{candidate.name}」占用！"
                )
        elif trimmed_edit_as:
            if candidate.name != trimmed_edit_as:
                raise CharacterProfileError(
                    f"立绘目录名「{prefix}」已被角色「{candidate.name}」占用！"
                )
        elif not (is_self_persona_name(raw_name) and is_self_persona_name(candidate.name)):
            raise CharacterProfileError(
                f"立绘目录名「{prefix}」已被角色「{candidate.name}」占用！"
            )


def save_character_patch(
    target: CharacterPersistenceTarget,
    patch: Mapping[str, Any],
    *,
    original_name: str | None = None,
    target_id: str | None = None,
    sprite_portrait_crops: Mapping[int, Any] | None = None,
    sprite_group_map: Mapping[int, str | None] | None = None,
) -> tuple[Character, str | None, bool]:
    """Create or update a character via model-merge without fixed per-field parameter lists."""
    raw_name = str(patch.get("name") or "").strip()
    if not raw_name:
        raise CharacterProfileError("名称不能为空！")

    trimmed_edit_as = str(original_name).strip() if original_name else ""
    cleaned_id = str(target_id or patch.get("id") or "").strip()

    if trimmed_edit_as and is_self_persona_name(trimmed_edit_as) and not is_self_persona_name(raw_name):
        raise CharacterProfileError("内置「自设」人物不可重命名！")
    if trimmed_edit_as and not is_self_persona_name(trimmed_edit_as) and is_self_persona_name(raw_name):
        raise CharacterProfileError("不能将其他角色重命名为「自设」！")

    existing: Character | None = target.get_by_id(cleaned_id) if cleaned_id else None
    if existing is None and trimmed_edit_as:
        existing = resolve_mutable_character(target, trimmed_edit_as)
    if existing is None:
        existing = resolve_mutable_character(target, raw_name)

    if existing is not None:
        if is_self_persona_name(existing.name) and not is_self_persona_name(raw_name):
            raise CharacterProfileError("内置「自设」人物不可重命名！")
        if not is_self_persona_name(existing.name) and is_self_persona_name(raw_name):
            raise CharacterProfileError("不能将其他角色重命名为「自设」！")
        if getattr(existing, "undeletable", False) and existing.name != raw_name:
            raise CharacterProfileError(f"内置角色「{existing.name}」不可重命名！")
        taken = (
            None
            if is_self_persona_name(raw_name) and is_self_persona_name(existing.name)
            else target.get_by_name(raw_name)
        )
        if taken is not None and taken is not existing:
            same_id = (
                getattr(taken, "id", None) is not None
                and getattr(taken, "id", None) == getattr(existing, "id", None)
            )
            if not same_id:
                raise CharacterProfileError(f"名称「{raw_name}」已与其他角色重复！")

    raw_prefix = (
        patch["sprite_prefix"]
        if "sprite_prefix" in patch
        else (existing.sprite_prefix if existing is not None else "")
    )
    prefix = str(raw_prefix or "").strip()
    if is_self_persona_name(raw_name) and not prefix:
        prefix = SELF_PERSONA_SPRITE_PREFIX

    _validate_prefix_uniqueness(
        target,
        prefix,
        raw_name=raw_name,
        trimmed_edit_as=trimmed_edit_as,
        existing=existing,
    )

    if existing is not None:
        merged = existing.model_dump(mode="python")
        for key, value in patch.items():
            if key in _PROTECTED_PROFILE_FIELDS:
                continue
            if key == "display_name" and not is_self_persona_name(raw_name):
                continue
            merged[key] = _normalize_patch_value(key, value)
        if existing.name != raw_name and "relation_graph" not in patch:
            merged["relation_graph"] = rename_relation_graph_owner(
                existing.relation_graph, existing.name, raw_name
            )
        merged_sprites = _apply_sprite_patch_metadata(
            list(existing.sprites or []),
            patch.get("sprites"),
            sprite_portrait_crops,
            sprite_group_map,
        )
        merged["sprites"] = merged_sprites
        merged["id"] = existing.id
        merged["name"] = raw_name
        merged["sprite_prefix"] = prefix
        if "portrait_sprite_index" in patch and patch["portrait_sprite_index"] is not None:
            merged["portrait_sprite_index"] = clamp_portrait_sprite_index(
                patch["portrait_sprite_index"], len(merged_sprites)
            )
        validated = Character.model_validate(merged)
        renamed_from = existing.name if existing.name != validated.name else None
        target.save_character(validated)
        return validated, renamed_from, False

    merged = {
        key: _normalize_patch_value(key, value)
        for key, value in patch.items()
        if key not in _PROTECTED_PROFILE_FIELDS
    }
    if not is_self_persona_name(raw_name):
        merged.pop("display_name", None)
    merged["name"] = raw_name
    merged["sprite_prefix"] = prefix
    merged["color"] = (
        str(patch["color"])
        if "color" in patch and patch["color"] is not None
        else "#d07d7d"
    )
    merged["sprites"] = []
    merged["portrait_sprite_index"] = (
        0
        if patch.get("portrait_sprite_index") is None
        else clamp_portrait_sprite_index(patch["portrait_sprite_index"], 0)
    )
    validated = Character.model_validate(merged)
    target.save_character(validated)
    return validated, None, True


def delete_character_and_assets(
    target: CharacterPersistenceTarget,
    name: str,
    *,
    upload_dir: str | Path,
    voice_dir: str | Path,
    model_dir: str | Path,
) -> tuple[str, list[str]]:
    """Delete a character record and remove its managed asset directories."""
    current_names = [c.name for c in target.list_all()]
    if not name or name == "新角色":
        return "请选择要删除的角色！", current_names
    if is_self_persona_name(name):
        return "内置「自设」人物不可删除！", current_names

    character = target.get_by_name(name)
    if character is None:
        return f"找不到角色: {name}", current_names
    if getattr(character, "undeletable", False):
        return f"内置角色「{character.name}」不可删除！", current_names

    if not target.delete_character_record(character):
        return f"找不到角色: {name}", current_names

    new_names = [c.name for c in target.list_all()]
    sprite_prefix = str(character.sprite_prefix or "").strip()
    if not sprite_prefix:
        return "已删除角色", new_names

    for base_dir in (upload_dir, voice_dir, model_dir):
        char_dir = Path(base_dir) / sprite_prefix
        if char_dir.exists():
            shutil.rmtree(char_dir)
    return f"角色 {name} 已删除！", new_names


def save_character_emotion_tags_op(
    target: CharacterPersistenceTarget,
    name: str,
    emotion_tags: str,
) -> Character:
    """Persist updated static sprite emotion tags for ``name``."""
    cleaned_name = str(name or "").strip()
    if not cleaned_name:
        raise CharacterProfileError("请先选择或创建角色！")
    if not emotion_tags:
        raise CharacterProfileError("请输入情绪标注！")
    character = target.get_by_name(cleaned_name)
    if character is None:
        raise CharacterProfileError(f"找不到角色: {cleaned_name}")
    updated = character.model_copy(update={"emotion_tags": emotion_tags})
    target.save_character(updated)
    return updated


def save_character_sprite_scale_op(
    target: CharacterPersistenceTarget,
    name: str,
    scale: float,
) -> Character:
    """Persist sprite display scale for ``name``."""
    cleaned_name = str(name or "").strip()
    if not cleaned_name:
        raise CharacterProfileError("名称不能为空！")
    character = target.get_by_name(cleaned_name)
    if character is None:
        raise CharacterProfileError(f"找不到角色: {cleaned_name}")
    updated = character.model_copy(update={"sprite_scale": float(scale)})
    target.save_character(updated)
    return updated


__all__ = [
    "clamp_portrait_sprite_index",
    "delete_character_and_assets",
    "resolve_mutable_character",
    "save_character_emotion_tags_op",
    "save_character_patch",
    "save_character_sprite_scale_op",
]
