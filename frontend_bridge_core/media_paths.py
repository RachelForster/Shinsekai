from __future__ import annotations

import hmac
import os
import stat
from collections.abc import Iterable, Iterator
from pathlib import Path, PureWindowsPath
from typing import Any

from frontend_bridge_core.security import reject_control_chars


IMAGE_MEDIA_SUFFIXES = frozenset(
    {
        ".apng",
        ".avif",
        ".bmp",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".png",
        ".svg",
        ".webp",
    }
)
AUDIO_MEDIA_SUFFIXES = frozenset(
    {
        ".aac",
        ".aif",
        ".aiff",
        ".flac",
        ".m4a",
        ".mp3",
        ".oga",
        ".ogg",
        ".opus",
        ".wav",
        ".weba",
        ".wma",
    }
)
VIDEO_MEDIA_SUFFIXES = frozenset(
    {
        ".avi",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".ogv",
        ".webm",
        ".wmv",
    }
)
FONT_MEDIA_SUFFIXES = frozenset({".otf", ".ttf", ".woff", ".woff2"})
READABLE_MEDIA_SUFFIXES = (
    IMAGE_MEDIA_SUFFIXES
    | AUDIO_MEDIA_SUFFIXES
    | VIDEO_MEDIA_SUFFIXES
    | FONT_MEDIA_SUFFIXES
)

_WINDOWS_DEVICE_PREFIXES = ("\\\\.\\", "\\\\?\\", "\\??\\")


def _validate_windows_local_drive_path(raw_path: str) -> None:
    value = raw_path.replace("/", "\\")
    if value.startswith(_WINDOWS_DEVICE_PREFIXES):
        raise PermissionError("Windows device paths are not allowed for media")
    if value.startswith("\\\\"):
        raise PermissionError("UNC paths are not allowed for media")

    path = PureWindowsPath(value)
    if not path.drive or not path.root:
        raise PermissionError("external media path must use an absolute local drive path")
    if ":" in value[len(path.drive) :]:
        raise PermissionError("Windows alternate data streams are not allowed for media")


def is_supported_media_path_text(raw_path: str) -> bool:
    value = str(raw_path or "").strip().lower()
    return any(value.endswith(suffix) for suffix in READABLE_MEDIA_SUFFIXES)


def is_absolute_local_media_path_text(raw_path: str) -> bool:
    value = str(raw_path or "").strip()
    if not value:
        return False
    if os.name == "nt":
        normalized = value.replace("/", "\\")
        path = PureWindowsPath(normalized)
        return bool(
            not normalized.startswith("\\\\")
            and not normalized.startswith(_WINDOWS_DEVICE_PREFIXES)
            and path.drive
            and path.root
        )
    return os.path.isabs(value)


def iter_configured_external_media_paths(value: Any) -> Iterator[str]:
    """Yield absolute media paths from server-owned configuration values."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_configured_external_media_paths(item)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from iter_configured_external_media_paths(item)
        return
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if isinstance(value, str) and is_absolute_local_media_path_text(value):
        if is_supported_media_path_text(value):
            yield value.strip()


def resolve_external_media_file(
    raw_path: str | os.PathLike[str],
    *,
    approved_paths: Iterable[str | os.PathLike[str]],
) -> Path:
    raw = reject_control_chars(os.fsdecode(os.fspath(raw_path)), field="media path")
    approved = ""
    for candidate in approved_paths:
        candidate_text = reject_control_chars(
            os.fsdecode(os.fspath(candidate)),
            field="approved media path",
        )
        if hmac.compare_digest(
            raw.encode("utf-8"),
            candidate_text.encode("utf-8"),
        ):
            approved = candidate_text
            break
    if not approved:
        raise PermissionError("external media path has not been approved by the runtime")

    if os.name == "nt":
        _validate_windows_local_drive_path(approved)

    candidate = Path(approved).expanduser()
    if not candidate.is_absolute():
        raise PermissionError("external media path must be absolute")
    return validate_readable_media_file(candidate)


def validate_readable_media_file(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    if resolved.suffix.lower() not in READABLE_MEDIA_SUFFIXES:
        raise PermissionError("file type is not allowed for media")
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise PermissionError("media path must reference a regular file")
    return resolved
