"""Synchronized domain operations for effect presets and managed media assets."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import contextlib
from functools import wraps
import hashlib
from pathlib import Path
import shutil
from threading import RLock
from typing import Any, Protocol, TypeVar, runtime_checkable

from config.models import Effect
from core.effects.paths import (
    configured_effect_path,
    effect_category_dir,
    effect_dir_for,
    validate_effect_storage_name,
)
from core.media.asset_tags import numbered_tags, tag_content as _tag_text, tag_contents
from core.packaging.zip_io import available_destination, rollback_staged_assets
from core.storage.layout import StorageLayout
from core.storage.stores import EffectCatalogPort
from sdk.path_utils import safe_existing_file_path

_F = TypeVar("_F", bound=Callable[..., Any])

EFFECT_MUTATION_LOCK = RLock()

_PROTECTED_EFFECT_FIELDS = frozenset(
    {
        "id",
        "audio_list",
        "image_list",
        "image_audio_list",
        "ambient_list",
        "ambient_audio_list",
    }
)

_AUDIO_EXTENSIONS = frozenset({".flac", ".m4a", ".mp3", ".ogg", ".wav"})
_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})
_AMBIENT_MEDIA_EXTENSIONS = frozenset(
    {
        ".apng",
        ".gif",
        ".jpeg",
        ".jpg",
        ".m4v",
        ".mov",
        ".mp4",
        ".png",
        ".webm",
        ".webp",
    }
)

_EFFECT_ASSET_LIST_FIELDS: tuple[str, ...] = (
    "audio_list",
    "image_list",
    "image_audio_list",
    "ambient_list",
    "ambient_audio_list",
)


def with_effect_lock(fn: _F) -> _F:
    """Serialize effect read-modify-write mutations across concurrent callers."""

    @wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        with EFFECT_MUTATION_LOCK:
            return fn(*args, **kwargs)

    return _wrapped  # type: ignore[return-value]


@runtime_checkable
class EffectPersistenceTarget(Protocol):
    """Unified persistence contract backed by either SQLite catalog or legacy ConfigManager."""

    def list_all(self) -> list[Any]: ...

    def get_by_id(self, effect_id: str) -> Any | None: ...

    def get_by_name(self, name: str) -> Any | None: ...

    def save_effect(self, effect: Effect, *, replaced: Any = None) -> Effect: ...

    def delete_effect(self, effect: Any) -> None: ...

    def save_imported(self, imported: Sequence[Effect], prepare_dir: Callable[[Effect], None]) -> None: ...


class CatalogEffectTarget:
    """Persistence adapter backed by ``EffectCatalogPort`` with optional ConfigManager sync."""

    def __init__(self, catalog: EffectCatalogPort, config_manager: Any = None) -> None:
        self._catalog = catalog
        self._config_manager = config_manager

    def list_all(self) -> list[Any]:
        return list(self._catalog.list_all())

    def get_by_id(self, effect_id: str) -> Any | None:
        get_fn = getattr(self._catalog, "get", None)
        if callable(get_fn):
            return get_fn(effect_id)
        return None

    def get_by_name(self, name: str) -> Any | None:
        return self._catalog.get_by_name(name)

    def _sync(self) -> None:
        if self._config_manager is None:
            return
        refresh = getattr(self._config_manager, "refresh_effects", None)
        if callable(refresh):
            refresh()
        else:
            self._config_manager.reload()

    def save_effect(self, effect: Effect, *, replaced: Any = None) -> Effect:
        del replaced
        self._catalog.put(effect.id, effect)
        self._sync()
        found = self._catalog.get_by_name(effect.name)
        if found is None:
            raise KeyError(f"effect not found: {effect.name}")
        return found

    def delete_effect(self, effect: Any) -> None:
        self._catalog.delete(effect.id)
        self._sync()

    def save_imported(
        self,
        imported: Sequence[Effect],
        prepare_dir: Callable[[Effect], None],
    ) -> None:
        atomic = getattr(self._catalog, "atomic", None)
        with atomic() if callable(atomic) else contextlib.nullcontext():
            for effect in imported:
                prepare_dir(effect)
                self._catalog.put(effect.id, effect)
        self._sync()


class ConfigManagerEffectTarget:
    """Persistence adapter backed directly by ``ConfigManager`` in-memory effect_list."""

    def __init__(self, config_manager: Any) -> None:
        self._config_manager = config_manager

    def list_all(self) -> list[Any]:
        return list(self._config_manager.config.effect_list)

    def get_by_id(self, effect_id: str) -> Any | None:
        return next(
            (e for e in self._config_manager.config.effect_list if getattr(e, "id", "") == effect_id),
            None,
        )

    def get_by_name(self, name: str) -> Any | None:
        return self._config_manager.get_effect_by_name(name)

    def _sync(self) -> None:
        refresh = getattr(self._config_manager, "refresh_effects", None)
        if callable(refresh):
            refresh()
        else:
            self._config_manager.reload()

    def save_effect(self, effect: Effect, *, replaced: Any = None) -> Effect:
        effects = self._config_manager.config.effect_list
        if replaced is not None:
            next_effects: list[Any] = []
            did_replace = False
            for existing in effects:
                matches = (
                    existing is replaced
                    or getattr(existing, "id", "") == getattr(replaced, "id", "")
                    or str(getattr(existing, "name", "")).lower() == str(getattr(replaced, "name", "")).lower()
                )
                if matches:
                    if not did_replace:
                        next_effects.append(effect)
                        did_replace = True
                else:
                    next_effects.append(existing)
            if not did_replace:
                next_effects.append(effect)
            effects[:] = next_effects
        else:
            effects[:] = [
                existing
                for existing in effects
                if str(getattr(existing, "name", "")).lower() != effect.name.lower()
            ]
            effects.append(effect)
        self._config_manager.save_effect_config()
        self._sync()
        found = self._config_manager.get_effect_by_name(effect.name)
        if found is None:
            raise KeyError(f"effect not found: {effect.name}")
        return found

    def delete_effect(self, effect: Any) -> None:
        self._config_manager.config.effect_list.remove(effect)
        self._config_manager.save_effect_config()

    def save_imported(
        self,
        imported: Sequence[Effect],
        prepare_dir: Callable[[Effect], None],
    ) -> None:
        effects = self._config_manager.config.effect_list
        for effect in imported:
            if effect not in effects:
                effects.append(effect)
            prepare_dir(effect)
        self._config_manager.save_effect_config()
        self._sync()


def file_digest(path: Path) -> str:
    """Return SHA-256 hex digest for ``path``, or ``''`` on read error."""
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def managed_effect_file(effect_dir: Path, project_root: Path, raw_path: str) -> Path | None:
    """Resolve ``raw_path`` if it points to an existing file inside ``effect_dir``."""
    if not raw_path:
        return None
    root = effect_dir.resolve(strict=False)
    try:
        candidate = configured_effect_path(project_root, raw_path)
        return safe_existing_file_path(
            candidate,
            roots=[root],
            field="effect asset path",
        )
    except (OSError, ValueError, FileNotFoundError):
        return None


def all_referenced_effect_paths(
    effect: Any,
    project_root: Path,
    *,
    exclude_field: str | None = None,
    exclude_indexes: set[int] | None = None,
) -> set[Path]:
    """Collect resolved file paths still referenced by ``effect`` across all asset fields."""
    referenced: set[Path] = set()
    skip_indexes = exclude_indexes or set()
    for field_name in _EFFECT_ASSET_LIST_FIELDS:
        values = getattr(effect, field_name, None) or ()
        for index, raw_path in enumerate(values):
            if field_name == exclude_field and index in skip_indexes:
                continue
            text = str(raw_path or "").strip()
            if not text:
                continue
            try:
                referenced.add(configured_effect_path(project_root, text).resolve(strict=False))
            except (OSError, ValueError):
                continue
    return referenced


def unlink_if_unreferenced(
    effect_dir: Path,
    project_root: Path,
    raw_path: str,
    *,
    remaining_paths: set[Path],
) -> None:
    """Delete a managed asset file only when no remaining field references it."""
    target = managed_effect_file(effect_dir, project_root, raw_path)
    if target is None:
        return
    if target.resolve(strict=False) in remaining_paths:
        return
    try:
        target.unlink()
    except OSError:
        pass


def managed_asset_digests(
    effect_dir: Path,
    project_root: Path,
    raw_paths: Sequence[Any] | None,
) -> set[str]:
    """Return content digests for assets currently stored for one field."""
    digests: set[str] = set()
    for raw_path in raw_paths or ():
        target = managed_effect_file(effect_dir, project_root, str(raw_path))
        if target is None:
            continue
        digest = file_digest(target)
        if digest:
            digests.add(digest)
    return digests


def renamed_asset_paths(
    raw_paths: Any,
    old_dir: Path,
    new_dir: Path,
    project_root: Path,
) -> list[Any]:
    """Rewrite stored asset paths after an effect folder rename, preserving subdirectories."""
    if not isinstance(raw_paths, list):
        return list(raw_paths or [])
    old_root = old_dir.resolve(strict=False)
    updated: list[Any] = []
    for raw_path in raw_paths:
        if not isinstance(raw_path, str):
            updated.append(raw_path)
            continue
        try:
            relative = configured_effect_path(project_root, raw_path).relative_to(old_root)
        except (OSError, RuntimeError, ValueError):
            updated.append(raw_path)
        else:
            updated.append((new_dir / relative).as_posix())
    return updated


def move_effect_dir(old_dir: Path, new_dir: Path) -> None:
    """Move ``old_dir`` (including category subdirectories) to ``new_dir`` safely."""
    new_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        old_dir.rename(new_dir)
    except OSError:
        new_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(old_dir, new_dir, dirs_exist_ok=True)
        shutil.rmtree(old_dir, ignore_errors=True)


def _normalize_ambient_layers(raw_layers: Any, count: int) -> list[str]:
    values = list(raw_layers) if isinstance(raw_layers, Sequence) and not isinstance(raw_layers, (str, bytes, bytearray)) else []
    normalized = ["front" if str(item or "").strip().lower() == "front" else "back" for item in values[:count]]
    normalized.extend("back" for _ in range(count - len(normalized)))
    return normalized


def _effect_by_name(target: EffectPersistenceTarget, name: str) -> Any:
    effect = target.get_by_name(name)
    if effect is None:
        raise KeyError(f"effect not found: {name}")
    return effect


def _commit_field_updates(
    target: EffectPersistenceTarget,
    effect: Any,
    updates: Mapping[str, Any],
) -> Effect:
    if hasattr(effect, "model_copy"):
        next_effect = effect.model_copy(update=dict(updates))
    else:
        for field_name, value in updates.items():
            setattr(effect, field_name, value)
        next_effect = effect
    return target.save_effect(next_effect, replaced=effect)


@with_effect_lock
def save_effect_op(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    payload: Mapping[str, Any],
) -> Effect:
    """Create or update an effect preset while guarding protected asset lists & concurrent saves."""
    raw_body = payload.get("effect", payload)
    if not isinstance(raw_body, Mapping):
        raise ValueError("effect payload must be an object")
    body = dict(raw_body)
    name = validate_effect_storage_name(str(body.get("name") or "").strip())
    original_name = str(payload.get("originalName") or "").strip()
    if original_name:
        validate_effect_storage_name(original_name)
    effect_id = str(payload.get("id") or body.get("id") or "").strip()

    existing_effects = target.list_all()
    original = target.get_by_id(effect_id) if effect_id else None
    if original is None and effect_id:
        original = next((e for e in existing_effects if getattr(e, "id", "") == effect_id), None)
    if original is None and original_name:
        original = _effect_by_name(target, original_name)

    if original is not None:
        merged = original.model_dump(mode="python")
        ambient_count = len(original.ambient_list or ())
        for key, value in body.items():
            if key in _PROTECTED_EFFECT_FIELDS:
                continue
            if key == "ambient_layers":
                # Guard parallel ambient_layers against stale autosave payloads whose length
                # no longer matches the authoritative stored ambient_list.
                if (
                    isinstance(value, Sequence)
                    and not isinstance(value, (str, bytes, bytearray))
                    and len(value) == ambient_count
                ):
                    merged["ambient_layers"] = _normalize_ambient_layers(value, ambient_count)
                continue
            merged[key] = value
        merged["ambient_layers"] = _normalize_ambient_layers(
            merged.get("ambient_layers"), ambient_count
        )
        merged["id"] = original.id
        remaining = [
            effect
            for effect in existing_effects
            if effect is not original
            and getattr(effect, "id", "") != original.id
            and effect.name.lower() != original.name.lower()
        ]
        existing_names = {effect.name.lower() for effect in remaining}
        base_name = name
        counter = 1
        while name.lower() in existing_names:
            name = f"{base_name}_{counter}"
            counter += 1
        merged["name"] = name
        updated = Effect.model_validate(merged)
        old_dir = effect_dir_for(layout, original.name)
        new_dir = effect_dir_for(layout, updated.name)
        if old_dir.is_dir() and old_dir != new_dir:
            for list_field in _EFFECT_ASSET_LIST_FIELDS:
                merged[list_field] = renamed_asset_paths(
                    merged.get(list_field), old_dir, new_dir, layout.project_root
                )
            updated = Effect.model_validate(merged)
            move_effect_dir(old_dir, new_dir)
        effect_dir_for(layout, updated.name).mkdir(parents=True, exist_ok=True)
        return target.save_effect(updated, replaced=original)

    existing_match = next(
        (eff for eff in existing_effects if eff.name.lower() == name.lower()),
        None,
    )
    if existing_match is not None and "id" not in body:
        body["id"] = existing_match.id
    updated = Effect.model_validate(body)
    effect_dir_for(layout, updated.name).mkdir(parents=True, exist_ok=True)
    return target.save_effect(updated)


@with_effect_lock
def delete_effect_op(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    name: str,
) -> dict[str, Any]:
    """Delete an effect preset and remove its managed asset tree."""
    validated_name = validate_effect_storage_name(str(name or ""))
    match = _effect_by_name(target, validated_name)
    target.delete_effect(match)
    effect_dir = effect_dir_for(layout, match.name)
    if effect_dir.is_dir():
        shutil.rmtree(effect_dir, ignore_errors=True)
    return {}


def _upload_collection_assets(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    *,
    local_file_access_roots: Sequence[Path],
    name: str,
    paths: Any,
    category: str,
    list_field: str,
    tags_field: str,
    incoming_tags: Any,
    tag_prefix: str,
    allowed_suffixes: frozenset[str] | None,
    field_label: str,
    companion_defaults: Mapping[str, str] | None = None,
) -> Effect:
    validated_name = validate_effect_storage_name(str(name or "").strip())
    if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes, bytearray)):
        raise ValueError("paths must be a list")
    effect = _effect_by_name(target, validated_name)
    effect_dir = effect_dir_for(layout, validated_name)
    dest_dir = effect_category_dir(effect_dir, category)
    dest_dir.mkdir(parents=True, exist_ok=True)

    asset_list = list(getattr(effect, list_field, None) or ())
    defaults = dict(companion_defaults or {})
    companions: dict[str, list[str]] = {}
    for comp_field, default_value in defaults.items():
        comp_values = list(getattr(effect, comp_field, None) or ())
        comp_values.extend(default_value for _ in range(len(asset_list) - len(comp_values)))
        companions[comp_field] = comp_values

    tags = tag_contents(
        str(incoming_tags or getattr(effect, tags_field, "") or ""),
        len(asset_list),
        preserve_blank_lines=True,
    )
    known_digests = managed_asset_digests(effect_dir, layout.project_root, asset_list)

    for raw_path in paths:
        try:
            source = safe_existing_file_path(
                str(raw_path),
                roots=local_file_access_roots,
                field=field_label,
            )
        except (OSError, ValueError, FileNotFoundError):
            continue
        if allowed_suffixes is not None and source.suffix.lower() not in allowed_suffixes:
            continue
        digest = file_digest(source)
        if digest and digest in known_digests:
            continue
        destination = available_destination(dest_dir, source.name)
        shutil.copy2(source, destination)
        if digest:
            known_digests.add(digest)
        destination_text = destination.as_posix()
        if destination_text in asset_list:
            continue
        asset_list.append(destination_text)
        for comp_field, default_value in defaults.items():
            companions[comp_field].append(default_value)
        tags.append("")

    updates: dict[str, Any] = {
        list_field: asset_list,
        tags_field: numbered_tags(tag_prefix, tags),
        **companions,
    }
    return _commit_field_updates(target, effect, updates)


@with_effect_lock
def upload_effect_audio_op(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    *,
    local_file_access_roots: Sequence[Path],
    name: str,
    paths: Any,
    audio_tags: Any = "",
) -> Effect:
    return _upload_collection_assets(
        target,
        layout,
        local_file_access_roots=local_file_access_roots,
        name=name,
        paths=paths,
        category="audio",
        list_field="audio_list",
        tags_field="audio_tags",
        incoming_tags=audio_tags,
        tag_prefix="特效",
        allowed_suffixes=None,
        field_label="effect asset path",
    )


@with_effect_lock
def delete_effect_audio_op(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    *,
    name: str,
    index: int,
) -> Effect:
    validated_name = validate_effect_storage_name(str(name or "").strip())
    effect = _effect_by_name(target, validated_name)
    audio_list = list(effect.audio_list or ())
    if index < 0 or index >= len(audio_list):
        raise IndexError(f"audio index out of range: {index}")

    removed_path = audio_list.pop(index)
    remaining_refs = all_referenced_effect_paths(
        effect,
        layout.project_root,
        exclude_field="audio_list",
        exclude_indexes={index},
    )
    unlink_if_unreferenced(
        effect_dir_for(layout, validated_name),
        layout.project_root,
        removed_path,
        remaining_paths=remaining_refs,
    )
    tag_lines = str(effect.audio_tags or "").splitlines()
    while tag_lines and not tag_lines[-1].strip():
        tag_lines.pop()
    if index < len(tag_lines):
        tag_lines.pop(index)
    return _commit_field_updates(
        target,
        effect,
        {
            "audio_list": audio_list,
            "audio_tags": "".join(
                f"特效 {position + 1}：{_tag_text(line)}\n"
                for position, line in enumerate(tag_lines)
            ),
        },
    )


@with_effect_lock
def delete_all_effect_audio_op(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    *,
    name: str,
) -> Effect:
    validated_name = validate_effect_storage_name(str(name or "").strip())
    effect = _effect_by_name(target, validated_name)
    audio_list = list(effect.audio_list or ())
    remaining_refs = all_referenced_effect_paths(
        effect,
        layout.project_root,
        exclude_field="audio_list",
        exclude_indexes=set(range(len(audio_list))),
    )
    effect_dir = effect_dir_for(layout, validated_name)
    for path in audio_list:
        unlink_if_unreferenced(
            effect_dir,
            layout.project_root,
            str(path),
            remaining_paths=remaining_refs,
        )
    return _commit_field_updates(target, effect, {"audio_list": [], "audio_tags": ""})


@with_effect_lock
def save_effect_audio_tags_op(
    target: EffectPersistenceTarget,
    *,
    name: str,
    audio_tags: str,
) -> Effect:
    validated_name = validate_effect_storage_name(str(name or "").strip())
    effect = _effect_by_name(target, validated_name)
    lines = audio_tags.splitlines()
    missing = [
        str(index + 1)
        for index in range(len(effect.audio_list or ()))
        if index >= len(lines) or not _tag_text(lines[index])
    ]
    if missing:
        print(
            f"[Effect] 警告：特效方案 '{validated_name}' 的第 {', '.join(missing)} 个音频"
            "未输入提示词，将无法通过关键词触发。"
        )
    return _commit_field_updates(target, effect, {"audio_tags": audio_tags})


@with_effect_lock
def upload_effect_images_op(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    *,
    local_file_access_roots: Sequence[Path],
    name: str,
    paths: Any,
    image_tags: Any = "",
) -> Effect:
    return _upload_collection_assets(
        target,
        layout,
        local_file_access_roots=local_file_access_roots,
        name=name,
        paths=paths,
        category="images",
        list_field="image_list",
        tags_field="image_tags",
        incoming_tags=image_tags,
        tag_prefix="图片",
        allowed_suffixes=_IMAGE_EXTENSIONS,
        field_label="effect image path",
        companion_defaults={"image_audio_list": ""},
    )


def _delete_paired_media_asset(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    *,
    name: str,
    index: int,
    list_field: str,
    paired_field: str,
    tags_field: str,
    tag_prefix: str,
    layers_field: str | None = None,
    oob_label: str,
) -> Effect:
    validated_name = validate_effect_storage_name(str(name or "").strip())
    effect = _effect_by_name(target, validated_name)
    primary_list = list(getattr(effect, list_field, None) or ())
    paired_list = list(getattr(effect, paired_field, None) or ())
    if index < 0 or index >= len(primary_list):
        raise IndexError(f"{oob_label} index out of range: {index}")

    updated_primary = list(primary_list)
    removed_visual = updated_primary.pop(index)
    updated_paired = list(paired_list)
    removed_paired = updated_paired.pop(index) if index < len(updated_paired) else ""

    updates: dict[str, Any] = {
        list_field: updated_primary,
        paired_field: updated_paired,
    }
    if layers_field is not None:
        layers_list = list(getattr(effect, layers_field, None) or ())
        if index < len(layers_list):
            layers_list.pop(index)
        updates[layers_field] = layers_list

    next_preview = effect.model_copy(update=updates) if hasattr(effect, "model_copy") else effect
    remaining_refs = all_referenced_effect_paths(next_preview, layout.project_root)
    effect_dir = effect_dir_for(layout, validated_name)
    unlink_if_unreferenced(
        effect_dir,
        layout.project_root,
        str(removed_visual),
        remaining_paths=remaining_refs,
    )
    if removed_paired:
        unlink_if_unreferenced(
            effect_dir,
            layout.project_root,
            str(removed_paired),
            remaining_paths=remaining_refs,
        )

    tag_lines = str(getattr(effect, tags_field, "") or "").splitlines()
    while tag_lines and not tag_lines[-1].strip():
        tag_lines.pop()
    if index < len(tag_lines):
        tag_lines.pop(index)
    updates[tags_field] = "".join(
        f"{tag_prefix} {position + 1}：{_tag_text(line)}\n"
        for position, line in enumerate(tag_lines)
    )
    return _commit_field_updates(target, effect, updates)


@with_effect_lock
def delete_effect_image_op(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    *,
    name: str,
    index: int,
) -> Effect:
    return _delete_paired_media_asset(
        target,
        layout,
        name=name,
        index=index,
        list_field="image_list",
        paired_field="image_audio_list",
        tags_field="image_tags",
        tag_prefix="图片",
        oob_label="image",
    )


@with_effect_lock
def save_effect_image_tags_op(
    target: EffectPersistenceTarget,
    *,
    name: str,
    image_tags: str,
) -> Effect:
    validated_name = validate_effect_storage_name(str(name or "").strip())
    effect = _effect_by_name(target, validated_name)
    return _commit_field_updates(target, effect, {"image_tags": image_tags})


def _upload_paired_audio_op(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    *,
    local_file_access_roots: Sequence[Path],
    name: str,
    index: int,
    raw_path: str,
    primary_field: str,
    paired_field: str,
    category: str,
    label: str,
) -> Effect:
    validated_name = validate_effect_storage_name(str(name or "").strip())
    effect = _effect_by_name(target, validated_name)
    primary_list = list(getattr(effect, primary_field, None) or ())
    if index < 0 or index >= len(primary_list):
        raise IndexError(f"{label} index out of range: {index}")
    source = safe_existing_file_path(
        str(raw_path or ""),
        roots=local_file_access_roots,
        field=f"effect {label} audio path",
    )
    if source.suffix.lower() not in _AUDIO_EXTENSIONS:
        raise ValueError(f"unsupported effect {label} audio format")

    effect_dir = effect_dir_for(layout, validated_name)
    dest_dir = effect_category_dir(effect_dir, category)
    dest_dir.mkdir(parents=True, exist_ok=True)
    destination = available_destination(dest_dir, source.name)
    shutil.copy2(source, destination)

    paired_list = list(getattr(effect, paired_field, None) or ())
    paired_list.extend("" for _ in range(len(primary_list) - len(paired_list)))
    previous_audio = paired_list[index]
    paired_list[index] = destination.as_posix()

    updated = _commit_field_updates(target, effect, {paired_field: paired_list})
    if previous_audio:
        unlink_if_unreferenced(
            effect_dir,
            layout.project_root,
            previous_audio,
            remaining_paths=all_referenced_effect_paths(updated, layout.project_root),
        )
    return updated


@with_effect_lock
def upload_effect_image_audio_op(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    *,
    local_file_access_roots: Sequence[Path],
    name: str,
    index: int,
    raw_path: str,
) -> Effect:
    return _upload_paired_audio_op(
        target,
        layout,
        local_file_access_roots=local_file_access_roots,
        name=name,
        index=index,
        raw_path=raw_path,
        primary_field="image_list",
        paired_field="image_audio_list",
        category="image-audio",
        label="image",
    )


@with_effect_lock
def upload_effect_ambient_op(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    *,
    local_file_access_roots: Sequence[Path],
    name: str,
    paths: Any,
    ambient_tags: Any = "",
) -> Effect:
    return _upload_collection_assets(
        target,
        layout,
        local_file_access_roots=local_file_access_roots,
        name=name,
        paths=paths,
        category="ambient",
        list_field="ambient_list",
        tags_field="ambient_tags",
        incoming_tags=ambient_tags,
        tag_prefix="环境",
        allowed_suffixes=_AMBIENT_MEDIA_EXTENSIONS,
        field_label="effect ambient asset path",
        companion_defaults={"ambient_audio_list": "", "ambient_layers": "back"},
    )


@with_effect_lock
def delete_effect_ambient_op(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    *,
    name: str,
    index: int,
) -> Effect:
    return _delete_paired_media_asset(
        target,
        layout,
        name=name,
        index=index,
        list_field="ambient_list",
        paired_field="ambient_audio_list",
        tags_field="ambient_tags",
        tag_prefix="环境",
        layers_field="ambient_layers",
        oob_label="ambient",
    )


@with_effect_lock
def save_effect_ambient_tags_op(
    target: EffectPersistenceTarget,
    *,
    name: str,
    ambient_tags: str,
) -> Effect:
    validated_name = validate_effect_storage_name(str(name or "").strip())
    effect = _effect_by_name(target, validated_name)
    return _commit_field_updates(target, effect, {"ambient_tags": ambient_tags})


@with_effect_lock
def save_effect_ambient_layers_op(
    target: EffectPersistenceTarget,
    *,
    name: str,
    raw_layers: Any,
) -> Effect:
    validated_name = validate_effect_storage_name(str(name or "").strip())
    effect = _effect_by_name(target, validated_name)
    if not isinstance(raw_layers, Sequence) or isinstance(
        raw_layers, (str, bytes, bytearray)
    ):
        raise ValueError("layers must be a list")
    layers = _normalize_ambient_layers(raw_layers, len(effect.ambient_list or ()))
    return _commit_field_updates(target, effect, {"ambient_layers": layers})


@with_effect_lock
def upload_effect_ambient_audio_op(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    *,
    local_file_access_roots: Sequence[Path],
    name: str,
    index: int,
    raw_path: str,
) -> Effect:
    return _upload_paired_audio_op(
        target,
        layout,
        local_file_access_roots=local_file_access_roots,
        name=name,
        index=index,
        raw_path=raw_path,
        primary_field="ambient_list",
        paired_field="ambient_audio_list",
        category="ambient-audio",
        label="ambient",
    )


@with_effect_lock
def import_effect_packages_op(
    target: EffectPersistenceTarget,
    layout: StorageLayout,
    *,
    local_file_access_roots: Sequence[Path],
    paths: Any,
) -> list[Effect]:
    from core.packaging.effect_package import stage_effect_package_import

    if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes, bytearray)):
        raise ValueError("paths must be a list")
    existing = target.list_all()
    effect_root = layout.media_dir("effects")
    imported: list[Effect] = []
    created_dirs: list[Path] = []
    committed = False
    try:
        for raw_path in paths:
            archive = safe_existing_file_path(
                str(raw_path),
                roots=local_file_access_roots,
                field="effect package path",
            )
            staged = stage_effect_package_import(
                archive,
                existing_effects=[*existing, *imported],
                effect_root=effect_root,
            )
            created_dirs.extend(staged.created_dirs)
            imported.extend(staged.effects)
        target.save_imported(
            imported,
            lambda eff: effect_dir_for(layout, eff.name).mkdir(parents=True, exist_ok=True),
        )
        committed = True
        return imported
    except BaseException:
        if not committed:
            rollback_staged_assets(created_dirs)
        raise


__all__ = [
    "CatalogEffectTarget",
    "ConfigManagerEffectTarget",
    "EFFECT_MUTATION_LOCK",
    "EffectPersistenceTarget",
    "all_referenced_effect_paths",
    "delete_all_effect_audio_op",
    "delete_effect_ambient_op",
    "delete_effect_audio_op",
    "delete_effect_image_op",
    "delete_effect_op",
    "file_digest",
    "import_effect_packages_op",
    "managed_effect_file",
    "move_effect_dir",
    "renamed_asset_paths",
    "save_effect_ambient_layers_op",
    "save_effect_ambient_tags_op",
    "save_effect_audio_tags_op",
    "save_effect_image_tags_op",
    "save_effect_op",
    "unlink_if_unreferenced",
    "upload_effect_ambient_audio_op",
    "upload_effect_ambient_op",
    "upload_effect_audio_op",
    "upload_effect_image_audio_op",
    "upload_effect_images_op",
    "with_effect_lock",
]
