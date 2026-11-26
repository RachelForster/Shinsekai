"""Cohesive background domain operations decoupled from persistence backends and pandas."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import wraps
import os
from pathlib import Path
import shutil
from threading import RLock
from typing import Any, Optional, Protocol, TypeVar, runtime_checkable

from config.character_ops.target import _sync_pydantic_model_in_place
from config.schema import Background, Sprite
from i18n import err_tr, tr

_F = TypeVar("_F", bound=Callable[..., Any])
_PROTECTED_BACKGROUND_FIELDS = frozenset({"id", "sprites", "bgm_list"})

BACKGROUND_MUTATION_LOCK = RLock()


def _with_background_lock(fn: _F) -> _F:
    """Serialize background read-modify-write mutations across direct and legacy callers."""

    @wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        with BACKGROUND_MUTATION_LOCK:
            return fn(*args, **kwargs)

    return _wrapped  # type: ignore[return-value]


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
        custom_save: bool = False,
    ) -> None:
        self._cm = config_manager
        self._save_fn = save_fn or config_manager.save_background_config
        self._custom_save = custom_save or (
            "save_background_config" in getattr(config_manager, "__dict__", {})
        )
        self._seen_by_id: dict[str, Background] = {}

    def _row_backend(self) -> Any | None:
        if self._custom_save:
            return None
        backend = getattr(self._cm, "active_backend", None)
        return backend if backend is not None and hasattr(backend, "put_background") else None

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
        backend = self._row_backend()
        if backend is not None:
            return list(backend.list_backgrounds())
        items = self._backgrounds_list()
        if items is not None:
            return list(items)
        return list(self._seen_by_id.values())

    def get_by_id(self, bg_id: str) -> Background | None:
        cleaned = str(bg_id or "").strip()
        if not cleaned:
            return None
        backend = self._row_backend()
        if backend is not None:
            return self._remember(backend.get_background_by_id(cleaned))
        for item in self.list_all():
            if str(getattr(item, "id", "") or "") == cleaned:
                return self._remember(item)
        return self._seen_by_id.get(cleaned)

    def get_by_name(self, name: str) -> Background | None:
        backend = self._row_backend()
        if backend is not None:
            return self._remember(backend.get_background_by_name(name))
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
        backend = self._row_backend()
        if backend is not None:
            items = self._backgrounds_list()
            mem_entry = self._find_list_entry(items, background) if items is not None else None
            backend.put_background(background)
            if mem_entry is not None:
                _sync_pydantic_model_in_place(mem_entry, background)
            refresh = getattr(self._cm, "refresh_backgrounds", None)
            if callable(refresh):
                refresh()
            return

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
        backend = self._row_backend()
        if backend is not None:
            deleted = bool(backend.delete_background(background.id))
            if deleted:
                refresh = getattr(self._cm, "refresh_backgrounds", None)
                if callable(refresh):
                    refresh()
            return deleted

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


def _allocate_unique_background_prefix(
    requested_prefix: str,
    existing_backgrounds: list[Background],
) -> str:
    used = {
        str(getattr(item, "sprite_prefix", "") or "").strip().lower()
        for item in existing_backgrounds
        if str(getattr(item, "sprite_prefix", "") or "").strip()
    }
    cleaned = str(requested_prefix or "").strip()
    base = cleaned if cleaned and cleaned.lower() != "temp" else ""
    if base:
        if base.lower() not in used:
            return base
        suffix = 2
        while f"{base}_{suffix}".lower() in used:
            suffix += 1
        return f"{base}_{suffix}"
    if cleaned.lower() == "temp" and "temp" not in used:
        return "temp"
    index = 1
    while f"bg_{index}" in used:
        index += 1
    return f"bg_{index}"


def _other_backgrounds_sharing_prefix(
    target: BackgroundPersistenceTarget,
    sprite_prefix: str,
    *,
    exclude_id: str | None = None,
    exclude_name: str = "",
) -> list[Background]:
    normalized = str(sprite_prefix or "").strip().lower()
    if not normalized:
        return []
    others: list[Background] = []
    for item in target.list_all():
        if exclude_id and getattr(item, "id", None) == exclude_id:
            continue
        if exclude_name and item.name == exclude_name:
            continue
        if str(getattr(item, "sprite_prefix", "") or "").strip().lower() == normalized:
            others.append(item)
    return others


def _unlink_unshared_files(paths: list[str], retained_paths: set[str]) -> None:
    retained_norm = {os.path.normcase(os.path.abspath(p)) for p in retained_paths if p}
    for raw in paths:
        if not raw:
            continue
        norm = os.path.normcase(os.path.abspath(raw))
        if norm in retained_norm:
            continue
        if os.path.isfile(raw):
            try:
                os.remove(raw)
            except OSError:
                pass


@_with_background_lock
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
        raise BackgroundProfileError(tr("crud.common.name_empty"))

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
                raise BackgroundProfileError(tr("crud.bg.duplicate_name", name=raw_name))

        merged = existing.model_dump(mode="python")
        for key, value in patch.items():
            if key in _PROTECTED_BACKGROUND_FIELDS:
                continue
            merged[key] = value
        raw_prefix = patch["sprite_prefix"] if "sprite_prefix" in patch else existing.sprite_prefix
        next_prefix = str(raw_prefix or "temp").strip() or "temp"
        existing_prefix = str(existing.sprite_prefix or "").strip()
        if next_prefix.lower() != existing_prefix.lower():
            if _other_backgrounds_sharing_prefix(
                target,
                next_prefix,
                exclude_id=getattr(existing, "id", None),
                exclude_name=existing.name,
            ):
                raise BackgroundProfileError(tr("crud.bg.prefix_in_use", prefix=next_prefix))
        merged["id"] = existing.id
        merged["name"] = raw_name
        merged["sprite_prefix"] = next_prefix
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
    merged["sprite_prefix"] = _allocate_unique_background_prefix(
        str(patch.get("sprite_prefix") or ""),
        list(target.list_all()),
    )
    merged["sprites"] = []
    merged["bgm_list"] = []
    validated = Background.model_validate(merged)
    target.save_background(validated)
    return validated, None, True


@_with_background_lock
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
        return err_tr("crud.bg.select_to_delete"), current_names

    background = target.get_by_name(name)
    if background is None:
        return err_tr("crud.bg.not_found", name=name), current_names

    if not target.delete_background_record(background):
        return err_tr("crud.bg.not_found", name=name), current_names

    remaining = list(target.list_all())
    new_names = [b.name for b in remaining]
    sprite_prefix = str(background.sprite_prefix or "").strip()
    if not sprite_prefix:
        return tr("crud.bg.deleted_unloaded"), new_names

    sharing = [
        item
        for item in remaining
        if str(getattr(item, "sprite_prefix", "") or "").strip().lower() == sprite_prefix.lower()
    ]
    if sharing:
        retained_sprites = {_sprite_path(s) for item in sharing for s in (item.sprites or [])}
        retained_bgms = {str(p) for item in sharing for p in (item.bgm_list or []) if p}
        _unlink_unshared_files([_sprite_path(s) for s in (background.sprites or [])], retained_sprites)
        _unlink_unshared_files([str(p) for p in (background.bgm_list or []) if p], retained_bgms)
    else:
        for base_dir in (upload_dir, bgm_dir):
            target_dir = Path(base_dir) / sprite_prefix
            if target_dir.exists():
                shutil.rmtree(target_dir)
    return tr("crud.bg.deleted", name=name), new_names


@_with_background_lock
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
        return err_tr("crud.bg.select_or_create"), [], ""
    if not sprite_files:
        return err_tr("crud.bg.select_images"), [], ""

    background = target.get_by_name(background_name)
    if not background:
        return err_tr("crud.bg.not_found", name=background_name), [], ""

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
    return tr("crud.bg.images_uploaded", name=background_name, count=len(sprite_files)), all_paths, updated.bg_tags


@_with_background_lock
def delete_all_background_sprites(
    target: BackgroundPersistenceTarget,
    background_name: str,
    *,
    upload_dir: str | Path,
) -> tuple[str, list[str], str]:
    """Delete all scene images for ``background_name``."""
    if not background_name:
        return err_tr("crud.bg.select_first"), [], ""
    background = target.get_by_name(background_name)
    if not background:
        return err_tr("crud.bg.not_found", name=background_name), [], ""

    sharing = _other_backgrounds_sharing_prefix(
        target,
        background.sprite_prefix,
        exclude_id=getattr(background, "id", None),
        exclude_name=background.name,
    )
    if sharing:
        retained = {_sprite_path(s) for item in sharing for s in (item.sprites or [])}
        _unlink_unshared_files([_sprite_path(s) for s in (background.sprites or [])], retained)
    else:
        bg_dir = os.path.join(str(upload_dir), background.sprite_prefix)
        if os.path.exists(bg_dir):
            shutil.rmtree(bg_dir)

    updated = background.model_copy(update={"sprites": [], "bg_tags": ""})
    target.save_background(updated)
    return tr("crud.bg.images_cleared", name=background_name), [], ""


@_with_background_lock
def delete_single_background_sprite(
    target: BackgroundPersistenceTarget,
    background_name: str,
    sprite_index: int,
) -> tuple[str, list[str], str]:
    """Delete one scene image by index and re-number scene tags."""
    if not background_name:
        return err_tr("crud.bg.select_first"), [], ""
    background = target.get_by_name(background_name)
    if not background:
        return err_tr("crud.bg.not_found", name=background_name), [], ""

    sprites = list(background.sprites or [])
    if not sprites or sprite_index < 0 or sprite_index >= len(sprites):
        remaining = [_sprite_path(s) for s in sprites]
        return err_tr("crud.bg.image_not_found"), remaining, background.bg_tags

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
    return tr("crud.bg.image_deleted", name=background_name, index=sprite_index + 1), remaining, next_tags


@_with_background_lock
def save_background_image_tags_op(
    target: BackgroundPersistenceTarget,
    background_name: str,
    bg_tags: str,
) -> Background:
    """Persist updated scene image tags for ``background_name``."""
    if not background_name:
        raise BackgroundProfileError(tr("crud.bg.select_or_create"))
    if not bg_tags:
        raise BackgroundProfileError(tr("crud.bg.tags_empty"))
    background = target.get_by_name(background_name)
    if not background:
        raise BackgroundProfileError(tr("crud.bg.not_found", name=background_name))
    updated = background.model_copy(update={"bg_tags": bg_tags})
    target.save_background(updated)
    return updated


@_with_background_lock
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
        return err_tr("crud.bg.select_or_create"), [], ""
    if not bgm_files:
        return err_tr("crud.bg.select_bgm"), [], ""
    background = target.get_by_name(background_name)
    if not background:
        return err_tr("crud.bg.not_found", name=background_name), [], ""

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
        tr("crud.bg.bgm_uploaded", name=background_name, count=len(bgm_files)),
        list(updated.bgm_list),
        updated.bgm_tags,
    )


@_with_background_lock
def delete_all_background_bgms(
    target: BackgroundPersistenceTarget,
    background_name: str,
    *,
    bgm_dir: str | Path,
) -> tuple[str, list[str], str]:
    """Delete all BGM files and metadata for ``background_name``."""
    if not background_name:
        return err_tr("crud.bg.select_first"), [], ""
    background = target.get_by_name(background_name)
    if not background:
        return err_tr("crud.bg.not_found", name=background_name), [], ""

    sharing = _other_backgrounds_sharing_prefix(
        target,
        background.sprite_prefix,
        exclude_id=getattr(background, "id", None),
        exclude_name=background.name,
    )
    if sharing:
        retained = {str(p) for item in sharing for p in (item.bgm_list or []) if p}
        _unlink_unshared_files([str(p) for p in (background.bgm_list or []) if p], retained)
    else:
        dest_dir = os.path.join(str(bgm_dir), background.sprite_prefix)
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)

    updated = background.model_copy(update={"bgm_list": [], "bgm_tags": ""})
    target.save_background(updated)
    return tr("crud.bg.bgm_cleared", name=background_name), [], ""


@_with_background_lock
def delete_single_background_bgm(
    target: BackgroundPersistenceTarget,
    background_name: str,
    bgm_index: int,
) -> tuple[str, list[str], str]:
    """Delete a single BGM track by index and re-number BGM tags."""
    if not background_name:
        return err_tr("crud.bg.select_first"), [], ""
    background = target.get_by_name(background_name)
    if not background:
        return err_tr("crud.bg.not_found", name=background_name), [], ""

    bgm_list = list(getattr(background, "bgm_list", None) or [])
    bgm_tags = str(getattr(background, "bgm_tags", "") or "")
    if not bgm_list or bgm_index < 0 or bgm_index >= len(bgm_list):
        return err_tr("crud.bg.bgm_not_found"), bgm_list, bgm_tags

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
        tr("crud.bg.bgm_deleted", name=background_name, index=bgm_index + 1),
        list(updated.bgm_list),
        next_tags,
    )


@_with_background_lock
def save_background_bgm_tags_op(
    target: BackgroundPersistenceTarget,
    background_name: str,
    bgm_tags: str,
) -> Background:
    """Persist updated BGM tags for ``background_name``."""
    if not background_name:
        raise BackgroundProfileError(tr("crud.bg.select_or_create"))
    if not bgm_tags:
        raise BackgroundProfileError(tr("crud.bg.bgm_tags_empty"))
    background = target.get_by_name(background_name)
    if not background:
        raise BackgroundProfileError(tr("crud.bg.not_found", name=background_name))
    updated = background.model_copy(update={"bgm_tags": bgm_tags})
    target.save_background(updated)
    return updated


__all__ = [
    "BACKGROUND_MUTATION_LOCK",
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
