"""Pass-through effect package (``.ef`` / ``.effect``) export and staged import."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import tempfile
from typing import Any
from uuid import uuid4
import zipfile

import yaml

from config.models import Effect
from core.packaging.zip_io import (
    available_destination,
    available_package_filename,
    resolve_underscore_conflict,
    rollback_staged_assets,
    safe_extract_zip,
    write_directory_zip,
)
from sdk.path_utils import safe_child_path, safe_existing_file_path, safe_filename
from i18n import tr

RESERVED_EFFECT_PACKAGE_FIELDS = frozenset({"id"})


@dataclass(slots=True)
class StagedEffectImport:
    """Staged Effect entities and newly created media dirs awaiting DB commit."""

    effects: list[Effect] = field(default_factory=list)
    created_dirs: list[Path] = field(default_factory=list)


def validate_effect_storage_name(name: Any) -> str:
    """Ensure an effect name addresses exactly one managed directory."""
    value = str(name or "").strip()
    if not value:
        raise ValueError("effect name is required")
    if "\x00" in value:
        raise ValueError("effect name contains an invalid character")
    if "/" in value or "\\" in value:
        raise ValueError("effect name must not contain path separators")
    path = Path(value)
    windows_path = PureWindowsPath(value)
    if path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValueError("effect name must not be an absolute path")
    if value in {".", ".."} or any(part in {".", ".."} for part in path.parts):
        raise ValueError("effect name must not contain relative path segments")
    return value


def _configured_path(project_root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    windows_path = PureWindowsPath(raw_path)
    if path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        return path.resolve(strict=False)
    return safe_child_path(project_root, path)


def _export_asset_file(
    effect_root: Path,
    project_root: Path,
    local_file_access_roots: Sequence[Path],
    effect_name: str,
    raw_path: str,
) -> Path:
    effect_dir = safe_child_path(effect_root, validate_effect_storage_name(effect_name))
    candidate = _configured_path(project_root, raw_path)
    if raw_path:
        try:
            return safe_existing_file_path(
                candidate,
                roots=[effect_dir.resolve(strict=False)],
                field="effect asset path",
            )
        except (OSError, ValueError, FileNotFoundError):
            pass
    return safe_existing_file_path(
        candidate,
        roots=local_file_access_roots,
        field="effect asset path",
    )


def _export_asset_paths(
    *,
    effect_root: Path,
    project_root: Path,
    local_file_access_roots: Sequence[Path],
    effect_name: str,
    raw_paths: Sequence[str],
    directory: str,
    allow_empty: bool = False,
) -> tuple[list[tuple[Path, str]], list[str]]:
    packaged: list[tuple[Path, str]] = []
    exported: list[str] = []
    used_names: set[str] = set()
    for raw_path in raw_paths:
        if not raw_path and allow_empty:
            exported.append("")
            continue
        asset_file = _export_asset_file(
            effect_root, project_root, local_file_access_roots, effect_name, str(raw_path)
        )
        package_name = available_package_filename(asset_file.name, used_names)
        used_names.add(package_name.casefold())
        package_path = f"{directory}/{package_name}"
        packaged.append((asset_file, package_path))
        exported.append(package_path)
    return packaged, exported


def _import_asset_paths(
    raw_paths: Any,
    source_dir: Path,
    effect_dir: Path,
) -> list[str]:
    imported: list[str] = []
    for raw_path in raw_paths or ():
        if not raw_path:
            imported.append("")
            continue
        filename = safe_filename(PurePosixPath(str(raw_path).replace("\\", "/")).name)
        source = safe_child_path(source_dir, filename)
        if source.is_file():
            destination = available_destination(effect_dir, filename)
            shutil.copy2(source, destination)
            imported.append(destination.as_posix())
        else:
            imported.append(str(raw_path))
    return imported


def export_effect_package(
    effect: Effect,
    output_path: str | os.PathLike[str],
    *,
    effect_root: Path,
    project_root: Path,
    local_file_access_roots: Sequence[Path] = (),
) -> Path:
    """Export one Effect entity and its referenced audio/images into an effect package."""
    effect_data = effect.model_dump(
        exclude_none=True,
        mode="json",
        exclude=set(RESERVED_EFFECT_PACKAGE_FIELDS),
    )
    packaged_audio, exported_audio = _export_asset_paths(
        effect_root=effect_root,
        project_root=project_root,
        local_file_access_roots=local_file_access_roots,
        effect_name=effect.name,
        raw_paths=effect.audio_list or (),
        directory="audio",
    )
    packaged_images, exported_images = _export_asset_paths(
        effect_root=effect_root,
        project_root=project_root,
        local_file_access_roots=local_file_access_roots,
        effect_name=effect.name,
        raw_paths=effect.image_list or (),
        directory="images",
    )
    packaged_image_audio, exported_image_audio = _export_asset_paths(
        effect_root=effect_root,
        project_root=project_root,
        local_file_access_roots=local_file_access_roots,
        effect_name=effect.name,
        raw_paths=effect.image_audio_list or (),
        directory="image-audio",
        allow_empty=True,
    )
    effect_data["audio_list"] = exported_audio
    effect_data["image_list"] = exported_images
    effect_data["image_audio_list"] = exported_image_audio

    with tempfile.TemporaryDirectory(prefix="shinsekai-effect-export-") as raw_temp:
        temp_dir = Path(raw_temp)
        (temp_dir / "effect.yaml").write_text(
            yaml.safe_dump([effect_data], allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        for asset_file, package_path in (*packaged_audio, *packaged_images, *packaged_image_audio):
            dest = safe_child_path(temp_dir, package_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset_file, dest)
        return write_directory_zip(temp_dir, output_path)


def stage_effect_package_import(
    archive: str | os.PathLike[str],
    *,
    existing_effects: Iterable[Effect],
    effect_root: Path,
) -> StagedEffectImport:
    """Validate an effect package, restore media under ``effect_root``, and build Effect models."""
    archive_path = Path(archive)
    if not archive_path.is_file():
        raise FileNotFoundError(tr("crud.common.archive_not_found", path=archive))

    staged = StagedEffectImport()
    try:
        with tempfile.TemporaryDirectory(prefix="shinsekai-effect-import-") as raw_temp:
            temp_dir = Path(raw_temp)
            with zipfile.ZipFile(archive_path, "r") as package:
                safe_extract_zip(package, temp_dir)
            yaml_path = temp_dir / "effect.yaml"
            yaml_data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if not yaml_data:
                raise ValueError(tr("crud.effect.yaml_empty"))
            entries = yaml_data if isinstance(yaml_data, list) else [yaml_data]
            existing_names_lower = {effect.name.lower() for effect in existing_effects}

            audio_source_dir = temp_dir / "audio"
            image_source_dir = temp_dir / "images"
            image_audio_source_dir = temp_dir / "image-audio"

            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                item = deepcopy(dict(entry))
                for reserved in RESERVED_EFFECT_PACKAGE_FIELDS:
                    item.pop(reserved, None)
                item["id"] = uuid4().hex

                original_name = validate_effect_storage_name(item.get("name", ""))
                name = resolve_underscore_conflict(original_name, existing_names_lower)
                existing_names_lower.add(name.lower())
                item["name"] = name

                effect_dir = safe_child_path(effect_root, validate_effect_storage_name(name))
                existed = effect_dir.exists()
                effect_dir.mkdir(parents=True, exist_ok=True)
                if not existed:
                    staged.created_dirs.append(effect_dir)

                item["audio_list"] = _import_asset_paths(
                    item.get("audio_list"), audio_source_dir, effect_dir
                )
                item["image_list"] = _import_asset_paths(
                    item.get("image_list"), image_source_dir, effect_dir
                )
                item["image_audio_list"] = _import_asset_paths(
                    item.get("image_audio_list"), image_audio_source_dir, effect_dir
                )
                staged.effects.append(Effect.model_validate(item))
        return staged
    except BaseException:
        rollback_staged_assets(staged.created_dirs)
        raise


__all__ = [
    "RESERVED_EFFECT_PACKAGE_FIELDS",
    "StagedEffectImport",
    "export_effect_package",
    "stage_effect_package_import",
    "validate_effect_storage_name",
]
