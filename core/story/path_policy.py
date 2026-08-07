"""Cross-platform lexical path rules for story-owned resources."""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath


def is_story_relative_path(value: str) -> bool:
    """Return whether a path is relative and cannot traverse above a story root."""

    normalized = value.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(value)
    return not (
        posix_path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or ".." in posix_path.parts
    )
