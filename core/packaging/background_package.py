"""Pass-through background package (``.bg``) export and staged import."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4
import zipfile

import yaml

from config.models import Background
from core.packaging.zip_io import (
    resolve_name_conflict,
    resolve_sprite_prefix_conflict,
    rollback_staged_assets,
    safe_extract_zip,
    safe_package_basename_or_legacy_absolute,
    safe_package_name,
    write_directory_zip,
)
from i18n import tr

RESERVED_BACKGROUND_PACKAGE_FIELDS = frozenset({"id"})


@dataclass(slots=True)
class StagedBackgroundImport:
    """Staged Background entities and newly created media dirs awaiting DB commit."""

    backgrounds: list[Background] = field(default_factory=list)
    created_dirs: list[Path] = field(default_factory=list)


def _sanitize_background_package_paths(bg_data: dict) -> None:
    sprites = bg_data.get("sprites") or []
    if isinstance(sprites, list):
        for sprite_entry in sprites:
            if isinstance(sprite_entry, dict) and sprite_entry.get("path"):
                sprite_entry["path"] = safe_package_basename_or_legacy_absolute(
                    sprite_entry["path"], "background sprite path"
                )
    bgm_list = bg_data.get("bgm_list")
    if isinstance(bgm_list, list):
        bg_data["bgm_list"] = [
            safe_package_basename_or_legacy_absolute(path, "background bgm path")
            for path in bgm_list
        ]


def export_background_package(
    backgrounds: Sequence[Background],
    output_path: str | os.PathLike[str],
    *,
    background_upload_dir: Path,
    bgm_upload_dir: Path,
) -> Path:
    """Export backgrounds and bundled media into a ``.bg`` archive."""
    with tempfile.TemporaryDirectory(prefix="shinsekai-bg-export-") as raw_temp:
        temp_dir = Path(raw_temp)
        background_data_list = []

        for config in backgrounds:
            bg_data = config.model_dump(
                exclude_none=True,
                mode="json",
                exclude=set(RESERVED_BACKGROUND_PACKAGE_FIELDS),
            )
            prefix = config.sprite_prefix
            if prefix:
                sprite_source_dir = background_upload_dir / prefix
                if sprite_source_dir.is_dir():
                    shutil.copytree(
                        sprite_source_dir,
                        temp_dir / "sprites" / prefix,
                        dirs_exist_ok=True,
                    )
                bgm_source_dir = bgm_upload_dir / prefix
                if bgm_source_dir.is_dir():
                    shutil.copytree(
                        bgm_source_dir,
                        temp_dir / "bgm" / prefix,
                        dirs_exist_ok=True,
                    )
            _sanitize_background_package_paths(bg_data)
            background_data_list.append(bg_data)

        (temp_dir / "background.yaml").write_text(
            yaml.safe_dump(background_data_list, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return write_directory_zip(temp_dir, output_path)


def stage_background_package_import(
    input_path: str | os.PathLike[str],
    *,
    existing_configs: Iterable[Background],
    background_upload_dir: Path,
    bgm_upload_dir: Path,
) -> StagedBackgroundImport:
    """Validate a ``.bg`` archive, restore assets into destination dirs, and build Background models."""
    archive_path = Path(input_path)
    if not archive_path.exists():
        raise FileNotFoundError(tr("crud.common.archive_not_found", path=input_path))

    staged = StagedBackgroundImport()
    try:
        with tempfile.TemporaryDirectory(prefix="shinsekai-bg-import-") as raw_temp:
            temp_dir = Path(raw_temp)
            with zipfile.ZipFile(archive_path, "r") as zf:
                safe_extract_zip(zf, temp_dir)

            yaml_data = yaml.safe_load((temp_dir / "background.yaml").read_text(encoding="utf-8"))
            if not yaml_data:
                raise ValueError(tr("crud.bg.yaml_empty"))
            if not isinstance(yaml_data, list):
                raise ValueError(tr("crud.bg.yaml_invalid"))

            existing_list = list(existing_configs)
            imported_names = {config.name for config in existing_list}
            imported_prefixes = {config.sprite_prefix for config in existing_list}

            for raw_bg in yaml_data:
                bg_data = deepcopy(dict(raw_bg))
                for reserved in RESERVED_BACKGROUND_PACKAGE_FIELDS:
                    bg_data.pop(reserved, None)
                bg_data["id"] = uuid4().hex

                original_name = str(bg_data.get("name") or "")
                original_prefix = safe_package_name(
                    bg_data.get("sprite_prefix", ""), "background sprite_prefix"
                )
                new_name = resolve_name_conflict(original_name, imported_names)
                bg_data["name"] = new_name
                imported_names.add(new_name)

                new_prefix = resolve_sprite_prefix_conflict(original_prefix, imported_prefixes)
                bg_data["sprite_prefix"] = new_prefix
                imported_prefixes.add(new_prefix)

                if new_prefix:
                    source_sprite_dir = temp_dir / "sprites" / original_prefix
                    dest_sprite_dir = background_upload_dir / new_prefix
                    if source_sprite_dir.is_dir():
                        existed = dest_sprite_dir.exists()
                        shutil.copytree(source_sprite_dir, dest_sprite_dir, dirs_exist_ok=True)
                        if not existed:
                            staged.created_dirs.append(dest_sprite_dir)

                    source_bgm_dir = temp_dir / "bgm" / original_prefix
                    dest_bgm_dir = bgm_upload_dir / new_prefix
                    if source_bgm_dir.is_dir():
                        existed = dest_bgm_dir.exists()
                        shutil.copytree(source_bgm_dir, dest_bgm_dir, dirs_exist_ok=True)
                        if not existed:
                            staged.created_dirs.append(dest_bgm_dir)

                if isinstance(bg_data.get("sprites"), list):
                    for sprite_entry in bg_data["sprites"]:
                        if isinstance(sprite_entry, dict) and "path" in sprite_entry:
                            filename = safe_package_basename_or_legacy_absolute(
                                sprite_entry["path"], "background sprite path"
                            )
                            sprite_entry["path"] = (
                                background_upload_dir / new_prefix / filename
                            ).as_posix()

                if isinstance(bg_data.get("bgm_list"), list):
                    bg_data["bgm_list"] = [
                        (
                            bgm_upload_dir
                            / new_prefix
                            / safe_package_basename_or_legacy_absolute(path, "background bgm path")
                        ).as_posix()
                        for path in bg_data["bgm_list"]
                    ]

                staged.backgrounds.append(Background.model_validate(bg_data))
        return staged
    except BaseException:
        rollback_staged_assets(staged.created_dirs)
        raise


__all__ = [
    "RESERVED_BACKGROUND_PACKAGE_FIELDS",
    "StagedBackgroundImport",
    "export_background_package",
    "stage_background_package_import",
]
