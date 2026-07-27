"""Path validation shared by host services and interface adapters."""

from __future__ import annotations

import os
import re
from pathlib import Path


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def reject_control_chars(value: str, *, field: str = "value") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    if _CONTROL_CHARS_RE.search(text):
        raise ValueError(f"{field} contains control characters")
    return text


def safe_existing_path(
    raw_path: str | os.PathLike[str],
    *,
    field: str = "path",
) -> Path:
    raw = reject_control_chars(os.fspath(raw_path), field=field)
    return Path(raw).expanduser().resolve(strict=True)


def safe_existing_file_path(
    raw_path: str | os.PathLike[str],
    *,
    field: str = "path",
) -> Path:
    path = safe_existing_path(raw_path, field=field)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def safe_existing_dir_path(
    raw_path: str | os.PathLike[str],
    *,
    field: str = "path",
) -> Path:
    path = safe_existing_path(raw_path, field=field)
    if not path.is_dir():
        raise NotADirectoryError(path)
    return path
