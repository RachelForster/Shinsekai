"""Static sprite, mouth-sync, transition clip, and avatar bank operations."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any, Optional
from uuid import uuid4

from config.character_ops.profile import clamp_portrait_sprite_index
from config.character_ops.target import CharacterPersistenceTarget, _with_character_lock
from config.schema import (
    Character,
    DEFAULT_SPRITE_GROUP,
    ModelSprites,
    Sprite,
    SpriteTransition,
)
from config.sprite_files import sprite_field, sprite_fingerprint
from config.sprite_groups import normalize_sprite_group_list
from config.sprite_mouth import read_manifest
from sdk.asset_tags import numbered_tags, tag_contents
from sdk.path_utils import safe_child_path


def _sprite_path(sprite: Sprite | dict[str, Any]) -> str:
    return sprite.path if isinstance(sprite, Sprite) else str(sprite.get("path", "") or "")


@_with_character_lock
def upload_character_sprites(
    target: CharacterPersistenceTarget,
    character_name: str,
    sprite_files: list[Any],
    emotion_tags: str,
    *,
    upload_dir: str | Path,
    sprite_tags: Optional[list[str]] = None,
    sprite_mouths: Optional[list[Optional[str]]] = None,
    replace_index: Optional[int] = None,
    expected_path: Optional[str] = None,
    replacements: Optional[list[tuple[int, str]]] = None,
    group: Optional[str] = None,
) -> tuple[str, list[str], str]:
    """Upload or replace static sprites for ``character_name`` and persist tags."""
    del emotion_tags  # Preserved in signature for legacy caller compatibility.
    if not character_name:
        return "请先选择或创建角色！", [], ""
    if not sprite_files:
        return "请选择要上传的图片！", [], ""

    if sprite_tags is not None and len(sprite_tags) != len(sprite_files):
        raise ValueError("Each sprite requires one tag entry")
    if sprite_mouths is not None:
        if len(sprite_mouths) != len(sprite_files):
            raise ValueError("每张生成结果需要一个口型条目")
        for file, manifest in zip(sprite_files, sprite_mouths):
            if manifest and read_manifest(manifest)["sourceFingerprint"] != sprite_fingerprint(file.name):
                raise ValueError("动态立绘已变化，请重新匹配口型")

    character = target.get_by_name(character_name)
    if character is None:
        from config.character_ops.profile import resolve_mutable_character

        character = resolve_mutable_character(target, character_name)
    if not character:
        return f"找不到角色: {character_name}", [], ""

    char_dir = os.path.join(str(upload_dir), character.sprite_prefix)
    Path(char_dir).mkdir(parents=True, exist_ok=True)

    existing_sprites = list(character.sprites or [])
    num_existing = len(existing_sprites)
    if replace_index is not None:
        if replacements is not None or len(sprite_files) != 1:
            raise ValueError("请选择一张有效的原立绘进行替换")
        replacements = [(replace_index, str(expected_path or ""))]
    if replacements is not None and len(replacements) != len(sprite_files):
        raise ValueError("每张生成结果需要一个替换目标")

    seen_targets: set[int] = set()
    for index, path in replacements or []:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < num_existing:
            raise ValueError("请选择一张有效的原立绘进行替换")
        if index in seen_targets:
            raise ValueError("同一原立绘只能选择一个结果替换")
        seen_targets.add(index)
        if path != sprite_field(existing_sprites[index], "path", ""):
            raise ValueError("原立绘已改变或尚未保存，请刷新角色后重新选择")

    cleaned_group = str(group or "").strip()
    stored_group = None if not cleaned_group or cleaned_group == DEFAULT_SPRITE_GROUP else cleaned_group
    new_sprites: list[Sprite | dict[str, Any]] = []
    tags_to_add = ""
    copied_paths: list[Path] = []

    try:
        for i, file in enumerate(sprite_files):
            filename = os.path.basename(file.name)
            if replacements is not None:
                filename = f"{uuid4().hex}{Path(filename).suffix}"
            dest_path = os.path.join(char_dir, filename)
            shutil.copyfile(file.name, dest_path)
            copied_paths.append(Path(dest_path))

            updates: dict[str, Any] = {"path": dest_path}
            if sprite_mouths is not None:
                updates["mouth_sync"] = sprite_mouths[i]
            if replacements is None and stored_group is not None:
                updates["group"] = stored_group

            new_sprite: Sprite | dict[str, Any]
            if replacements is not None:
                original = existing_sprites[replacements[i][0]]
                new_sprite = (
                    original.model_copy(update=updates)
                    if isinstance(original, Sprite)
                    else Sprite.model_validate({**original, **updates})
                )
            else:
                new_sprite = Sprite.model_validate(updates)
            new_sprites.append(new_sprite)

            tag = sprite_tags[i] if sprite_tags is not None else ""
            tags_to_add += f"立绘 {num_existing + i + 1}：{tag}\n"

        next_sprites = list(existing_sprites)
        next_groups = list(character.sprite_groups or [])
        if replacements is not None:
            for (index, _), sprite in zip(replacements, new_sprites):
                next_sprites[index] = sprite
        else:
            next_sprites.extend(new_sprites)
            if stored_group is not None and stored_group not in next_groups:
                next_groups = normalize_sprite_group_list([*next_groups, stored_group])

        current_tags = character.emotion_tags or ""
        if current_tags and not current_tags.endswith("\n"):
            current_tags += "\n"
        if replacements is not None:
            tags = tag_contents(character.emotion_tags or "", num_existing)
            if sprite_tags is not None:
                for (index, _), tag in zip(replacements, sprite_tags):
                    tags[index] = tag
            next_tags = numbered_tags("立绘", tags)
        elif sprite_tags is not None:
            next_tags = numbered_tags(
                "立绘", tag_contents(current_tags, num_existing) + sprite_tags
            )
        else:
            next_tags = current_tags + tags_to_add

        updated = character.model_copy(
            update={
                "sprites": next_sprites,
                "emotion_tags": next_tags,
                "sprite_groups": next_groups,
            }
        )
        target.save_character(updated)
    except Exception as exc:
        if not getattr(exc, "published", False):
            for path in copied_paths:
                path.unlink(missing_ok=True)
        raise

    all_paths = [_sprite_path(s) for s in updated.sprites]
    return f"成功为 {character_name} 上传 {len(sprite_files)} 张立绘！", all_paths, updated.emotion_tags


@_with_character_lock
def delete_all_character_sprites(
    target: CharacterPersistenceTarget,
    character_name: str,
    *,
    upload_dir: str | Path,
    voice_dir: str | Path,
) -> tuple[str, list[str], str]:
    """Delete all static sprites and their static voices, preserving model banks."""
    if not character_name:
        return "请先选择角色！", [], ""
    character = target.get_by_name(character_name)
    if not character:
        return f"找不到角色: {character_name}", [], ""

    char_dir = safe_child_path(Path(upload_dir), character.sprite_prefix)
    char_voice_dir = safe_child_path(Path(voice_dir), character.sprite_prefix)
    if char_dir == Path(upload_dir).resolve() or char_voice_dir == Path(voice_dir).resolve():
        raise PermissionError("Character asset directory must not be the shared root")

    if char_dir.is_dir():
        for child in char_dir.iterdir():
            if child.name.lower() in {"avatars", "avatar-voices"}:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(safe_child_path(char_dir, child.name))
            else:
                child.unlink()
        if not any(char_dir.iterdir()):
            char_dir.rmdir()

    if char_voice_dir.exists():
        shutil.rmtree(char_voice_dir)

    updated = character.model_copy(
        update={
            "sprites": [],
            "emotion_tags": "",
            "portrait_sprite_index": 0,
        }
    )
    target.save_character(updated)
    return f"已删除 {character_name} 的所有立绘！", [], ""


@_with_character_lock
def delete_single_character_sprite(
    target: CharacterPersistenceTarget,
    character_name: str,
    sprite_index: int,
) -> tuple[str, list[str], str]:
    """Delete one static sprite, its bound voice file, and shift tags and portrait index."""
    if not character_name:
        return "请先选择角色！", [], ""
    character = target.get_by_name(character_name)
    if not character:
        return f"找不到角色: {character_name}", [], ""

    sprites = list(character.sprites or [])
    if not sprites or sprite_index < 0 or sprite_index >= len(sprites):
        remaining = [_sprite_path(s) for s in sprites]
        return "立绘不存在！", remaining, character.emotion_tags

    sprite_data = sprites[sprite_index]
    s_path = _sprite_path(sprite_data)
    v_path = (
        sprite_data.voice_path
        if isinstance(sprite_data, Sprite)
        else sprite_data.get("voice_path", "")
    )
    if s_path and os.path.isfile(s_path):
        os.remove(s_path)
    if v_path and os.path.isfile(v_path):
        os.remove(v_path)

    sprites.pop(sprite_index)
    current_portrait = int(getattr(character, "portrait_sprite_index", 0) or 0)
    if sprite_index < current_portrait:
        current_portrait -= 1
    next_portrait = clamp_portrait_sprite_index(current_portrait, len(sprites))

    tags_lines = character.emotion_tags.strip().split("\n") if character.emotion_tags else []
    if sprite_index < len(tags_lines):
        tags_lines.pop(sprite_index)
    next_tags = ""
    for i, line in enumerate(tags_lines):
        parts = line.split("：") if "：" in line else line.split(":")
        tag_text = parts[-1].strip() if len(parts) > 1 else ""
        next_tags += f"立绘 {i + 1}：{tag_text}\n"

    updated = character.model_copy(
        update={
            "sprites": sprites,
            "portrait_sprite_index": next_portrait,
            "emotion_tags": next_tags,
        }
    )
    target.save_character(updated)
    remaining_paths = [_sprite_path(s) for s in updated.sprites]
    return f"已删除 {character_name} 的第 {sprite_index + 1} 张立绘！", remaining_paths, next_tags


@_with_character_lock
def save_character_avatar_bank(
    target: CharacterPersistenceTarget,
    name: str,
    avatar_type: str,
    bank: ModelSprites,
    *,
    activate: bool = False,
) -> Character:
    """Persist one validated avatar bank without replacing other avatar types or static assets."""
    character = target.get_by_name(name)
    if character is None:
        raise KeyError(name)
    validated_banks = Character(
        name=character.name,
        color=character.color,
        sprite_prefix=character.sprite_prefix,
        avatars={avatar_type: bank},
    ).avatars
    updates: dict[str, Any] = {
        "avatars": {**dict(character.avatars or {}), **validated_banks},
    }
    if activate:
        updates["avatar_type"] = avatar_type
    updated = character.model_copy(update=updates)
    target.save_character(updated)
    return updated


@_with_character_lock
def save_character_sprite_mouths(
    target: CharacterPersistenceTarget,
    name: str,
    results: list[tuple[int, str, str | None]],
) -> Character:
    """Attach or clear mouth-sync manifests on static sprites atomically."""
    character = target.get_by_name(name)
    if character is None:
        raise ValueError("角色不存在")
    next_sprites = list(character.sprites or [])
    for index, source, path in results:
        if not 0 <= index < len(next_sprites) or str(sprite_field(next_sprites[index], "path")) != source:
            raise ValueError("立绘列表已变化，请重新选择")
        if path and read_manifest(path)["sourceFingerprint"] != sprite_fingerprint(source):
            raise ValueError("来源立绘已变化，请重新制作口型")
        sprite = next_sprites[index]
        next_sprites[index] = (
            {**sprite, "mouth_sync": path}
            if isinstance(sprite, dict)
            else sprite.model_copy(update={"mouth_sync": path})
        )
    updated = character.model_copy(update={"sprites": next_sprites})
    target.save_character(updated)
    return updated


@_with_character_lock
def save_character_sprite_transitions(
    target: CharacterPersistenceTarget,
    name: str,
    results: list[dict[str, Any]],
    *,
    upload_dir: str | Path,
) -> Character:
    """Copy approved transition clips, replace directed edges atomically, and retain originals."""
    character = target.get_by_name(name)
    if character is None:
        raise KeyError(name)
    directory = safe_child_path(Path(upload_dir), f"{character.sprite_prefix}/transitions")
    directory.mkdir(parents=True, exist_ok=True)

    edges = {(edge.from_path, edge.to_path): edge for edge in (character.sprite_transitions or [])}
    copied: list[Path] = []
    try:
        for result in results:
            destination = directory / f"{uuid4().hex}.webm"
            copied.append(destination)
            shutil.copyfile(result["path"], destination)
            edge = SpriteTransition(
                from_path=result["fromPath"],
                to_path=result["toPath"],
                path=destination.as_posix(),
                from_fingerprint=result["fromFingerprint"],
                to_fingerprint=result["toFingerprint"],
                frame_count=result["frameCount"],
                h3_resolution=result.get("h3Resolution", "workflow"),
            )
            edges[(edge.from_path, edge.to_path)] = edge
        updated = character.model_copy(update={"sprite_transitions": list(edges.values())})
        target.save_character(updated)
    except Exception as exc:
        if not getattr(exc, "published", False):
            for path in copied:
                path.unlink(missing_ok=True)
        raise
    return updated


__all__ = [
    "delete_all_character_sprites",
    "delete_single_character_sprite",
    "save_character_avatar_bank",
    "save_character_sprite_mouths",
    "save_character_sprite_transitions",
    "upload_character_sprites",
]
