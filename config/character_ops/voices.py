"""Static sprite voice binding, text/type updates, and safe file cleanup."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
from typing import Any, Optional, Union

from config.character_ops.target import CharacterPersistenceTarget
from config.schema import Sprite
from config.sprite_files import sprite_field


def voice_filename_for_sprite(
    sprite_data: Union[Sprite, dict[str, Any]],
    sprite_index: int,
    file_ext: str,
) -> str:
    """Build a collision-free voice filename derived from the sprite asset path."""
    sprite_path = str(sprite_field(sprite_data, "path", "") or "")
    sprite_stem = Path(sprite_path).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", sprite_stem).strip("._-")
    if not safe_stem:
        safe_stem = f"sprite_{sprite_index:02d}"
    digest_source = sprite_path or safe_stem or str(sprite_index)
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:10]
    return f"voice_{safe_stem}_{digest}{file_ext}"


def _is_path_inside_directory(path: str, directory: str) -> bool:
    try:
        Path(path).resolve(strict=False).relative_to(Path(directory).resolve(strict=False))
        return True
    except (OSError, ValueError):
        return False


def _updated_sprite(sprite: Any, **changes: Any) -> Any:
    if isinstance(sprite, Sprite):
        return sprite.model_copy(update=changes)
    return {**sprite, **changes}


def upload_character_sprite_voice(
    target: CharacterPersistenceTarget,
    character_name: str,
    sprite_index: int,
    voice_file: str,
    voice_text: str,
    voice_type: str = "",
    *,
    voice_dir: str | Path,
) -> tuple[str, Optional[str]]:
    """Copy a reference/preset voice clip for one sprite and update persistence."""
    if not character_name:
        return "请先选择角色！", None
    character = target.get_by_name(character_name)
    if not character:
        return f"找不到角色: {character_name}", None
    sprites = list(character.sprites or [])
    if not sprites or sprite_index < 0 or sprite_index >= len(sprites):
        return "立绘不存在！", None

    sprite_data = sprites[sprite_index]
    original_voice_path = str(sprite_field(sprite_data, "voice_path", "") or "")
    if (not voice_file) and (not original_voice_path):
        return "请选择语音文件！", None

    voice_char_dir = os.path.join(str(voice_dir), character.sprite_prefix)
    Path(voice_char_dir).mkdir(parents=True, exist_ok=True)
    file_ext = Path(voice_file).suffix
    voice_filename = voice_filename_for_sprite(sprite_data, sprite_index, file_ext)
    voice_path = os.path.join(voice_char_dir, voice_filename)
    shutil.copyfile(voice_file, voice_path)

    changes: dict[str, Any] = {
        "voice_path": voice_path,
        "voice_text": voice_text,
    }
    if voice_type:
        changes["voice_type"] = voice_type
    sprites[sprite_index] = _updated_sprite(sprite_data, **changes)

    try:
        target.save_character(character.model_copy(update={"sprites": sprites}))
    except Exception as exc:
        if (
            not getattr(exc, "published", False)
            and os.path.abspath(voice_path) != os.path.abspath(original_voice_path or "")
            and os.path.isfile(voice_path)
        ):
            try:
                os.remove(voice_path)
            except OSError:
                pass
        raise

    if (
        original_voice_path
        and os.path.abspath(original_voice_path) != os.path.abspath(voice_path)
        and _is_path_inside_directory(original_voice_path, voice_char_dir)
    ):
        try:
            if os.path.isfile(original_voice_path):
                os.remove(original_voice_path)
        except OSError:
            pass

    return f"语音已上传到立绘 {sprite_index + 1}！", voice_path


def get_character_sprite_voice(
    target: CharacterPersistenceTarget,
    character_name: str,
    sprite_index: int,
) -> tuple[Optional[str], str]:
    """Read voice file path and transcript text for a single sprite index."""
    if not character_name or sprite_index is None:
        return None, ""
    character = target.get_by_name(character_name)
    if not character or not character.sprites or sprite_index < 0 or sprite_index >= len(character.sprites):
        return None, ""
    sprite_data = character.sprites[sprite_index]
    if isinstance(sprite_data, Sprite):
        return sprite_data.voice_path, sprite_data.voice_text or ""
    return sprite_data.get("voice_path", None), sprite_data.get("voice_text", "")


def save_character_sprite_voice_text(
    target: CharacterPersistenceTarget,
    character_name: str,
    sprite_index: int,
    voice_text: str,
) -> str:
    """Update only the transcript text attached to one sprite's voice."""
    if not character_name:
        return "请先选择角色！"
    character = target.get_by_name(character_name)
    if not character:
        return f"找不到角色: {character_name}"
    sprites = list(character.sprites or [])
    if not sprites or sprite_index < 0 or sprite_index >= len(sprites):
        return "立绘不存在！"
    sprites[sprite_index] = _updated_sprite(
        sprites[sprite_index],
        voice_text=voice_text if voice_text else None,
    )
    target.save_character(character.model_copy(update={"sprites": sprites}))
    return "语音文字已保存"


def save_character_sprite_voice_type(
    target: CharacterPersistenceTarget,
    character_name: str,
    sprite_index: int,
    voice_type: str,
) -> str:
    """Update only the voice routing mode (``preset`` / ``reference`` / ``fallback``)."""
    if not character_name:
        return "请先选择角色！"
    character = target.get_by_name(character_name)
    if not character:
        return f"找不到角色: {character_name}"
    sprites = list(character.sprites or [])
    if not sprites or sprite_index < 0 or sprite_index >= len(sprites):
        return "立绘不存在！"
    sprites[sprite_index] = _updated_sprite(
        sprites[sprite_index],
        voice_type=voice_type if voice_type else None,
    )
    target.save_character(character.model_copy(update={"sprites": sprites}))
    return "语音类型已保存"


def delete_character_sprite_voice(
    target: CharacterPersistenceTarget,
    character_name: str,
    sprite_index: int,
) -> str:
    """Unlink and delete a single sprite's voice clip."""
    if not character_name:
        return "请先选择角色！"
    character = target.get_by_name(character_name)
    if not character:
        return f"找不到角色: {character_name}"
    sprites = list(character.sprites or [])
    if not sprites or sprite_index < 0 or sprite_index >= len(sprites):
        return "立绘不存在！"

    sprite_data = sprites[sprite_index]
    voice_path = (
        sprite_data.voice_path
        if isinstance(sprite_data, Sprite)
        else sprite_data.get("voice_path", None)
    )
    sprites[sprite_index] = _updated_sprite(
        sprite_data,
        voice_path=None,
        voice_text=None,
    )
    target.save_character(character.model_copy(update={"sprites": sprites}))

    if voice_path and os.path.isfile(voice_path):
        try:
            os.remove(voice_path)
        except OSError:
            pass
    return f"已删除立绘 {sprite_index + 1} 的语音"


__all__ = [
    "delete_character_sprite_voice",
    "get_character_sprite_voice",
    "save_character_sprite_voice_text",
    "save_character_sprite_voice_type",
    "upload_character_sprite_voice",
    "voice_filename_for_sprite",
]
