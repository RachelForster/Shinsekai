"""Cohesive background domain operations decoupled from persistence backends and pandas."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import os
from pathlib import Path
import shutil
from typing import Any, Optional, Protocol, runtime_checkable

from config.character_ops.target import _sync_pydantic_model_in_place
from config.schema import Background, Sprite

_PROTECTED_BACKGROUND_FIELDS = frozenset({"id", "sprites", "bgm_list"})


class BackgroundProfileError(ValueError):
    """Domain validation or uniqueness conflict raised during background mutations."""


@runtime_checkable
class BackgroundPersistenceTarget(Protocol):
    """Minimal storage contract consumed by domain background operations."""

    def get_by_id(self, bg_id: str) -> Background | None: ...

    def get_by_name(self, name: str) -> Background | None: ...

    def list_all(self) -> Sequence[Background]: ...

    def save_background(self, background: Background) -> None: ...

    def delete_background_record(self, background: Background) -> bool: ...


class ConfigManagerBackgroundTarget:
    """Adapter backing ``BackgroundPersistenceTarget`` with a ``ConfigManager`` or test double."""

    def __init__(
        self,
        config_manager: Any,
        *,
        save_fn: Callable[[], None] | None = None,
    ) -> None:
        self._cm = config_manager
        self._save_fn = save_fn or config_manager.save_background_config
        self._seen_by_id: dict[str, Background] = {}

    def _remember(self, background: Background | None) -> Background | None:
        if background is not None:
            bg_id = str(getattr(background, "id", "") or "").strip()
            if bg_id:
                self._seen_by_id[bg_id] = background
        return background

    def _backgrounds_list(self) -> list[Background] | None:
        try:
            items = self._cm.config.background_list
        except Exception:
            return None
        return items if isinstance(items, list) else None

    def list_all(self) -> list[Background]:
        items = self._backgrounds_list()
        if items is not None:
            return list(items)
        return list(self._seen_by_id.values())

    def get_by_id(self, bg_id: str) -> Background | None:
        cleaned = str(bg_id or "").strip()
        if not cleaned:
            return None
        for item in self.list_all():
            if str(getattr(item, "id", "") or "") == cleaned:
                return self._remember(item)
        return self._seen_by_id.get(cleaned)

    def get_by_name(self, name: str) -> Background | None:
        return self._remember(self._cm.get_background_by_name(name))

    def _find_list_entry(
        self,
        items: list[Background],
        background: Background,
    ) -> Background | None:
        target_id = getattr(background, "id", None)
        for item in items:
            if item is background or (target_id and getattr(item, "id", None) == target_id):
                return item
        for item in items:
            if getattr(item, "name", None) == background.name:
                return item
        return None

    def save_background(self, background: Background) -> None:
        items = self._backgrounds_list()
        if items is not None:
            existing = self._find_list_entry(items, background)
        else:
            bg_id = str(getattr(background, "id", "") or "").strip()
            existing = (self._seen_by_id.get(bg_id) if bg_id else None) or self.get_by_name(background.name)
        if existing is not None:
            prev_dict = dict(existing.__dict__)
            prev_fields = (
                set(existing.__pydantic_fields_set__)
                if hasattr(existing, "__pydantic_fields_set__")
                else None
            )
            _sync_pydantic_model_in_place(existing, background)
            try:
                self._save_fn()
            except Exception as exc:
                if not getattr(exc, "published", False):
                    existing.__dict__.clear()
                    existing.__dict__.update(prev_dict)
                    if prev_fields is not None:
                        object.__setattr__(existing, "__pydantic_fields_set__", prev_fields)
                raise
            return

        if items is None:
            self._save_fn()
            return

        items.append(background)
        try:
            self._save_fn()
        except Exception as exc:
            if not getattr(exc, "published", False):
                try:
                    items.remove(background)
                except ValueError:
                    pass
            raise

    def delete_background_record(self, background: Background) -> bool:
        items = self._backgrounds_list()
        if items is None:
            return False
        existing = self._find_list_entry(items, background)
        if existing is None:
            return False
        items.remove(existing)
        try:
            self._save_fn()
        except Exception as exc:
            if not getattr(exc, "published", False):
                items.append(existing)
            raise
        return True


def _sprite_path(sprite: Sprite | dict[str, Any]) -> str:
    return sprite.path if isinstance(sprite, Sprite) else str(sprite.get("path", "") or "")


def save_background_patch(
    target: BackgroundPersistenceTarget,
    patch: Mapping[str, Any],
    *,
    original_name: Optional[str] = None,
    target_id: Optional[str] = None,
) -> tuple[Background, str | None, bool]:
    """Create or update a background group via model-merge without per-field parameters."""
    raw_name = str(patch.get("name") or "").strip()
    if not raw_name:
        raise BackgroundProfileError("名称不能为空！")

    trimmed_edit_as = str(original_name).strip() if original_name else ""
    cleaned_id = str(target_id or patch.get("id") or "").strip()

    existing = target.get_by_id(cleaned_id) if cleaned_id else None
    if existing is None and trimmed_edit_as:
        existing = target.get_by_name(trimmed_edit_as)
    if existing is None:
        existing = target.get_by_name(raw_name)

    if existing is not None:
        taken = target.get_by_name(raw_name)
        if taken is not None and taken is not existing:
            same_id = (
                getattr(taken, "id", None) is not None
                and getattr(taken, "id", None) == getattr(existing, "id", None)
            )
            if not same_id:
                raise BackgroundProfileError(f"名称「{raw_name}」已与其他背景组重复！")

        merged = existing.model_dump(mode="python")
        for key, value in patch.items():
            if key in _PROTECTED_BACKGROUND_FIELDS:
                continue
            merged[key] = value
        raw_prefix = patch["sprite_prefix"] if "sprite_prefix" in patch else existing.sprite_prefix
        merged["id"] = existing.id
        merged["name"] = raw_name
        merged["sprite_prefix"] = str(raw_prefix or "temp").strip() or "temp"
        validated = Background.model_validate(merged)
        renamed_from = existing.name if existing.name != validated.name else None
        target.save_background(validated)
        return validated, renamed_from, False

    merged = {
        key: value
        for key, value in patch.items()
        if key not in _PROTECTED_BACKGROUND_FIELDS
    }
    merged["name"] = raw_name
    merged["sprite_prefix"] = str(patch.get("sprite_prefix") or "temp").strip() or "temp"
    merged["sprites"] = []
    merged["bgm_list"] = []
    validated = Background.model_validate(merged)
    target.save_background(validated)
    return validated, None, True


def delete_background_and_assets(
    target: BackgroundPersistenceTarget,
    name: str,
    *,
    upload_dir: str | Path,
    bgm_dir: str | Path,
) -> tuple[str, list[str]]:
    """Delete a background group record and its managed image/BGM directories."""
    current_names = [b.name for b in target.list_all()]
    if not name or name == "新背景":
        return "请选择要删除的背景组！", current_names

    background = target.get_by_name(name)
    if background is None:
        return f"找不到背景组: {name}", current_names

    if not target.delete_background_record(background):
        return f"找不到背景组: {name}", current_names

    new_names = [b.name for b in target.list_all()]
    sprite_prefix = str(background.sprite_prefix or "").strip()
    if not sprite_prefix:
        return "已删除背景组", new_names

    for base_dir in (upload_dir, bgm_dir):
        target_dir = Path(base_dir) / sprite_prefix
        if target_dir.exists():
            shutil.rmtree(target_dir)
    return f"背景组 {name} 已删除！", new_names


def upload_background_sprites(
    target: BackgroundPersistenceTarget,
    background_name: str,
    sprite_files: list[Any],
    bg_tags: str,
    *,
    upload_dir: str | Path,
) -> tuple[str, list[str], str]:
    """Copy uploaded background images and persist appended ``Sprite`` entries."""
    del bg_tags  # Signature parity with legacy BackgroundManager.
    if not background_name:
        return "请先选择或创建背景组！", [], ""
    if not sprite_files:
        return "请选择要上传的图片！", [], ""

    background = target.get_by_name(background_name)
    if not background:
        return f"找不到背景组: {background_name}", [], ""

    bg_dir = os.path.join(str(upload_dir), background.sprite_prefix)
    Path(bg_dir).mkdir(parents=True, exist_ok=True)

    sprites = list(background.sprites or [])
    num_existing = len(sprites)
    tags_to_add = ""
    copied_paths: list[Path] = []
    try:
        for i, file in enumerate(sprite_files):
            filename = os.path.basename(file.name)
            dest_path = os.path.join(bg_dir, filename)
            shutil.copyfile(file.name, dest_path)
            copied_paths.append(Path(dest_path))
            sprites.append(Sprite(path=dest_path))
            tags_to_add += f"场景 {num_existing + i + 1}：\n"

        next_tags = (background.bg_tags or "") + tags_to_add
        updated = background.model_copy(update={"sprites": sprites, "bg_tags": next_tags})
        target.save_background(updated)
    except Exception as exc:
        if not getattr(exc, "published", False):
            for path in copied_paths:
                path.unlink(missing_ok=True)
        raise

    all_paths = [_sprite_path(s) for s in updated.sprites]
    return f"成功为 {background_name} 上传 {len(sprite_files)} 张背景图片！", all_paths, updated.bg_tags


def delete_all_background_sprites(
    target: BackgroundPersistenceTarget,
    background_name: str,
    *,
    upload_dir: str | Path,
) -> tuple[str, list[str], str]:
    """Delete all scene images for ``background_name``."""
    if not background_name:
        return "请先选择背景组！", [], ""
    background = target.get_by_name(background_name)
    if not background:
        return f"找不到背景组: {background_name}", [], ""

    bg_dir = os.path.join(str(upload_dir), background.sprite_prefix)
    if os.path.exists(bg_dir):
        shutil.rmtree(bg_dir)

    updated = background.model_copy(update={"sprites": [], "bg_tags": ""})
    target.save_background(updated)
    return f"已删除 {background_name} 的所有背景图片！", [], ""


def delete_single_background_sprite(
    target: BackgroundPersistenceTarget,
    background_name: str,
    sprite_index: int,
) -> tuple[str, list[str], str]:
    """Delete one scene image by index and re-number scene tags."""
    if not background_name:
        return "请先选择背景组！", [], ""
    background = target.get_by_name(background_name)
    if not background:
        return f"找不到背景组: {background_name}", [], ""

    sprites = list(background.sprites or [])
    if not sprites or sprite_index < 0 or sprite_index >= len(sprites):
        remaining = [_sprite_path(s) for s in sprites]
        return "背景图片不存在！", remaining, background.bg_tags

    sprite_data = sprites[sprite_index]
    sprite_path = _sprite_path(sprite_data)
    if sprite_path and os.path.isfile(sprite_path):
        os.remove(sprite_path)
    sprites.pop(sprite_index)

    tags_lines = background.bg_tags.strip().split("\n") if background.bg_tags else []
    if sprite_index < len(tags_lines):
        tags_lines.pop(sprite_index)
    next_tags = ""
    for i, line in enumerate(tags_lines):
        parts = line.split("：") if "：" in line else line.split(":")
        tag_text = parts[-1].strip() if len(parts) > 1 else ""
        next_tags += f"场景 {i + 1}：{tag_text}\n"

    updated = background.model_copy(update={"sprites": sprites, "bg_tags": next_tags})
    target.save_background(updated)
    remaining = [_sprite_path(s) for s in updated.sprites]
    return f"已删除 {background_name} 的第 {sprite_index + 1} 张背景图片！", remaining, next_tags


def save_background_image_tags_op(
    target: BackgroundPersistenceTarget,
    background_name: str,
    bg_tags: str,
) -> Background:
    """Persist updated scene image tags for ``background_name``."""
    if not background_name:
        raise BackgroundProfileError("请先选择或创建背景组！")
    if not bg_tags:
        raise BackgroundProfileError("请输入背景标注！")
    background = target.get_by_name(background_name)
    if not background:
        raise BackgroundProfileError(f"找不到背景组: {background_name}")
    updated = background.model_copy(update={"bg_tags": bg_tags})
    target.save_background(updated)
    return updated


def upload_background_bgms(
    target: BackgroundPersistenceTarget,
    background_name: str,
    bgm_files: list[Any],
    *,
    bgm_dir: str | Path,
    bgm_tags: Optional[str] = None,
) -> tuple[str, list[str], str]:
    """Copy uploaded BGM files and persist the updated list and tags in a single write."""
    if not background_name:
        return "请先选择或创建背景组！", [], ""
    if not bgm_files:
        return "请选择要上传的背景音乐文件！", [], ""
    background = target.get_by_name(background_name)
    if not background:
        return f"找不到背景组: {background_name}", [], ""

    dest_dir = os.path.join(str(bgm_dir), background.sprite_prefix)
    Path(dest_dir).mkdir(parents=True, exist_ok=True)

    bgm_list = list(getattr(background, "bgm_list", None) or [])
    num_existing = len(bgm_list)
    tags_to_add = ""
    copied_paths: list[Path] = []
    try:
        for i, file in enumerate(bgm_files):
            filename = os.path.basename(file.name)
            dest_path = os.path.join(dest_dir, filename)
            shutil.copyfile(file.name, dest_path)
            copied_paths.append(Path(dest_path))
            bgm_list.append(dest_path)
            tags_to_add += f"音乐 {num_existing + i + 1}：\n"

        base_tags = bgm_tags if bgm_tags is not None else (getattr(background, "bgm_tags", "") or "")
        next_tags = base_tags + tags_to_add
        updated = background.model_copy(update={"bgm_list": bgm_list, "bgm_tags": next_tags})
        target.save_background(updated)
    except Exception as exc:
        if not getattr(exc, "published", False):
            for path in copied_paths:
                path.unlink(missing_ok=True)
        raise

    return (
        f"成功为 {background_name} 上传 {len(bgm_files)} 个背景音乐文件！",
        list(updated.bgm_list),
        updated.bgm_tags,
    )


def delete_all_background_bgms(
    target: BackgroundPersistenceTarget,
    background_name: str,
    *,
    bgm_dir: str | Path,
) -> tuple[str, list[str], str]:
    """Delete all BGM files and metadata for ``background_name``."""
    if not background_name:
        return "请先选择背景组！", [], ""
    background = target.get_by_name(background_name)
    if not background:
        return f"找不到背景组: {background_name}", [], ""

    dest_dir = os.path.join(str(bgm_dir), background.sprite_prefix)
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)

    updated = background.model_copy(update={"bgm_list": [], "bgm_tags": ""})
    target.save_background(updated)
    return f"已删除 {background_name} 的所有背景音乐！", [], ""


def delete_single_background_bgm(
    target: BackgroundPersistenceTarget,
    background_name: str,
    bgm_index: int,
) -> tuple[str, list[str], str]:
    """Delete a single BGM track by index and re-number BGM tags."""
    if not background_name:
        return "请先选择背景组！", [], ""
    background = target.get_by_name(background_name)
    if not background:
        return f"找不到背景组: {background_name}", [], ""

    bgm_list = list(getattr(background, "bgm_list", None) or [])
    bgm_tags = str(getattr(background, "bgm_tags", "") or "")
    if not bgm_list or bgm_index < 0 or bgm_index >= len(bgm_list):
        return "背景音乐不存在！", bgm_list, bgm_tags

    bgm_path = bgm_list[bgm_index]
    if bgm_path and os.path.isfile(bgm_path):
        os.remove(bgm_path)
    bgm_list.pop(bgm_index)

    tags_lines = bgm_tags.strip().split("\n") if bgm_tags else []
    if bgm_index < len(tags_lines):
        tags_lines.pop(bgm_index)
    next_tags = ""
    for i, line in enumerate(tags_lines):
        parts = line.split("：") if "：" in line else line.split(":")
        tag_text = parts[-1].strip() if len(parts) > 1 else ""
        next_tags += f"音乐 {i + 1}：{tag_text}\n"

    updated = background.model_copy(update={"bgm_list": bgm_list, "bgm_tags": next_tags})
    target.save_background(updated)
    return (
        f"已删除 {background_name} 的第 {bgm_index + 1} 个背景音乐文件！",
        list(updated.bgm_list),
        next_tags,
    )


def save_background_bgm_tags_op(
    target: BackgroundPersistenceTarget,
    background_name: str,
    bgm_tags: str,
) -> Background:
    """Persist updated BGM tags for ``background_name``."""
    if not background_name:
        raise BackgroundProfileError("请先选择或创建背景组！")
    if not bgm_tags:
        raise BackgroundProfileError("请输入背景音乐标注！")
    background = target.get_by_name(background_name)
    if not background:
        raise BackgroundProfileError(f"找不到背景组: {background_name}")
    updated = background.model_copy(update={"bgm_tags": bgm_tags})
    target.save_background(updated)
    return updated


__all__ = [
    "BackgroundPersistenceTarget",
    "BackgroundProfileError",
    "ConfigManagerBackgroundTarget",
    "delete_all_background_bgms",
    "delete_all_background_sprites",
    "delete_background_and_assets",
    "delete_single_background_bgm",
    "delete_single_background_sprite",
    "save_background_bgm_tags_op",
    "save_background_image_tags_op",
    "save_background_patch",
    "upload_background_bgms",
    "upload_background_sprites",
]
