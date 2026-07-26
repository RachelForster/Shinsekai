from __future__ import annotations

import os
import stat
from pathlib import Path, PureWindowsPath

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


def resolve_external_media_file(raw_path: str | os.PathLike[str]) -> Path:
    raw = reject_control_chars(os.fspath(raw_path), field="media path")
    if os.name == "nt":
        _validate_windows_local_drive_path(raw)

    candidate = Path(raw).expanduser()
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
