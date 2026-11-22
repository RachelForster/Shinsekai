"""Shared path validation and storage directory resolution for effects."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Any

from core.storage.layout import StorageLayout
from sdk.path_utils import safe_child_path

EFFECT_ASSET_SUBDIRS: tuple[str, ...] = (
    "audio",
    "images",
    "image-audio",
    "ambient",
    "ambient-audio",
)


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


def configured_effect_path(project_root: Path, raw_path: str) -> Path:
    """Resolve a persisted effect asset path relative to ``project_root`` or absolute."""
    path = Path(raw_path)
    windows_path = PureWindowsPath(raw_path)
    if path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        return path.resolve(strict=False)
    return safe_child_path(project_root, path)


def effect_dir_for(layout: StorageLayout, name: str) -> Path:
    """Return the managed storage directory for one effect preset."""
    return layout.media_dir("effects", validate_effect_storage_name(name))


def effect_category_dir(effect_dir: Path, category: str) -> Path:
    """Return the validated category subdirectory inside an effect storage folder."""
    if category not in EFFECT_ASSET_SUBDIRS:
        raise ValueError(f"unsupported effect asset category: {category}")
    return safe_child_path(effect_dir, category)


__all__ = [
    "EFFECT_ASSET_SUBDIRS",
    "configured_effect_path",
    "effect_category_dir",
    "effect_dir_for",
    "validate_effect_storage_name",
]
