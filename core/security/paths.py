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


def _comparison_path(path: Path) -> str:
    value = os.path.normpath(str(path))
    return os.path.normcase(value) if os.name == "nt" else value


def _ensure_path_within_base(base: Path, resolved: Path, *, message: str) -> Path:
    try:
        common = os.path.commonpath(
            [_comparison_path(base), _comparison_path(resolved)]
        )
    except ValueError as exc:
        raise PermissionError(f"{message} or uses a different drive") from exc
    if common != _comparison_path(base):
        raise PermissionError(message)
    return resolved


def safe_project_path(
    raw_path: str | os.PathLike[str],
    *,
    root: Path | None = None,
) -> Path:
    base = (root or Path.cwd()).expanduser().resolve(strict=False)
    raw = reject_control_chars(os.fspath(raw_path), field="path")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.expanduser().resolve(strict=False)
    return _ensure_path_within_base(
        base,
        resolved,
        message="path is outside project root",
    )


def safe_child_path(base: Path, raw_path: str | os.PathLike[str]) -> Path:
    root = base.expanduser().resolve(strict=False)
    raw = reject_control_chars(os.fspath(raw_path), field="path")
    resolved = (root / raw.lstrip("/\\")).resolve(strict=False)
    return _ensure_path_within_base(
        root,
        resolved,
        message="path is outside base path",
    )


def safe_filename(raw_name: str, *, default_suffix: str = "") -> str:
    raw = reject_control_chars(raw_name, field="filename")
    if "/" in raw or "\\" in raw:
        raise ValueError("filename must not contain path separators")
    name = Path(raw).name
    if not name or name in {".", ".."} or name != raw:
        raise ValueError("filename is invalid")
    if default_suffix and not name.endswith(default_suffix):
        name = f"{name}{default_suffix}"
    return name


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
