"""Dependency-free path validation shared across host layers.

All paths influenced by API, plugin, or configuration input should cross this
module before they are used for filesystem I/O.  Compatibility modules may
re-export these helpers, but must not carry their own path-containment logic.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def reject_control_chars(value: str, *, field: str = "value") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    if _CONTROL_CHARS_RE.search(text):
        raise ValueError(f"{field} contains control characters")
    return text


def strip_windows_verbatim_prefix(value: str) -> str:
    r"""Drop Windows extended-length path prefixes (``\\?\`` / ``//?/``)."""

    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[len("\\\\?\\UNC\\") :]
    if value.startswith("\\\\?\\"):
        return value[len("\\\\?\\") :]
    if value.startswith("//?/UNC/"):
        return "//" + value[len("//?/UNC/") :]
    if value.startswith("//?/"):
        return value[len("//?/") :]
    return value


def resolve_regular_path(
    value: str | os.PathLike[str],
    *,
    strict: bool = False,
) -> Path:
    r"""Resolve a path while retaining verbatim spelling when long-path I/O needs it."""

    resolved = Path(os.fspath(value)).expanduser().resolve(strict=strict)
    if os.name == "nt":
        resolved_text = str(resolved)
        regular_text = strip_windows_verbatim_prefix(resolved_text)
        if regular_text != resolved_text and len(regular_text) < 248:
            regular = Path(regular_text)
            try:
                if resolved.exists() and regular.exists() and os.path.samefile(resolved, regular):
                    return regular.resolve(strict=strict)
            except OSError:
                pass
    return resolved


def _comparison_path(path: str | os.PathLike[str]) -> str:
    value = os.path.normpath(strip_windows_verbatim_prefix(os.fspath(path)))
    return os.path.normcase(value) if os.name == "nt" else value


def _path_prefix(base: str) -> str:
    separator = "\\" if os.name == "nt" else "/"
    value = _comparison_path(base)
    return value if value.endswith(("/", "\\")) else f"{value}{separator}"


def _resolve_path_text(value: str | os.PathLike[str]) -> str:
    """Normalize a path as text so containment is checked before ``Path`` I/O."""

    expanded = os.path.expanduser(os.fspath(value))
    return os.path.realpath(os.path.abspath(expanded))


def safe_project_path(
    raw_path: str | os.PathLike[str],
    root: Path | None = None,
) -> Path:
    """Resolve ``raw_path`` and require it to remain inside ``root``."""

    base = _resolve_path_text(root or os.getcwd())
    raw = reject_control_chars(os.fspath(raw_path), field="path")
    expanded = os.path.expanduser(raw)
    candidate = expanded if os.path.isabs(expanded) else os.path.join(base, expanded)
    resolved = os.path.realpath(os.path.abspath(candidate))
    base_value = _comparison_path(base)
    resolved_value = _comparison_path(resolved)
    base_drive = os.path.splitdrive(base_value)[0]
    resolved_drive = os.path.splitdrive(resolved_value)[0]
    if base_drive and resolved_drive and base_drive != resolved_drive:
        raise PermissionError("path is outside project root or uses a different drive")
    if resolved_value != base_value and not resolved_value.startswith(_path_prefix(base)):
        raise PermissionError("path is outside project root")
    return Path(resolved)


def safe_child_path(base: Path, raw_path: str | os.PathLike[str]) -> Path:
    """Resolve a request-style child path beneath ``base``."""

    root = _resolve_path_text(base)
    raw = reject_control_chars(os.fspath(raw_path), field="path")
    if os.path.splitdrive(raw)[0]:
        raise PermissionError("path is outside base path")
    candidate = os.path.join(root, raw.lstrip("/\\"))
    resolved = os.path.realpath(os.path.abspath(candidate))
    root_value = _comparison_path(root)
    resolved_value = _comparison_path(resolved)
    if resolved_value != root_value and not resolved_value.startswith(_path_prefix(root)):
        raise PermissionError("path is outside base path")
    return Path(resolved)


def safe_filename(raw_name: str, *, default_suffix: str = "") -> str:
    raw = reject_control_chars(raw_name, field="filename")
    if "/" in raw or "\\" in raw:
        raise ValueError("filename must not contain path separators")
    name = raw
    if name in {".", ".."}:
        raise ValueError("filename is invalid")
    if default_suffix and not name.endswith(default_suffix):
        name = f"{name}{default_suffix}"
    return name


def safe_existing_path(
    raw_path: str | os.PathLike[str],
    *,
    roots: Iterable[str | os.PathLike[str]],
    field: str = "path",
) -> Path:
    """Resolve an existing path only when it is inside an explicit trusted root."""

    raw = reject_control_chars(os.fspath(raw_path), field=field)
    trusted_roots = tuple(roots)
    if not trusted_roots:
        raise ValueError("at least one trusted path root is required")

    expanded = os.path.expanduser(raw)
    first_root = _resolve_path_text(trusted_roots[0])
    candidate = expanded if os.path.isabs(expanded) else os.path.join(first_root, expanded)
    resolved = os.path.realpath(os.path.abspath(candidate))
    resolved_value = _comparison_path(resolved)
    allowed = False
    for root in trusted_roots:
        trusted_root = _resolve_path_text(root)
        trusted_value = _comparison_path(trusted_root)
        if resolved_value == trusted_value or resolved_value.startswith(_path_prefix(trusted_root)):
            allowed = True
            break
    if not allowed:
        raise PermissionError(f"{field} is outside the allowed roots")

    path = Path(resolved)
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def safe_existing_file_path(
    raw_path: str | os.PathLike[str],
    *,
    roots: Iterable[str | os.PathLike[str]],
    field: str = "path",
) -> Path:
    path = safe_existing_path(raw_path, roots=roots, field=field)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def safe_existing_dir_path(
    raw_path: str | os.PathLike[str],
    *,
    roots: Iterable[str | os.PathLike[str]],
    field: str = "path",
) -> Path:
    path = safe_existing_path(raw_path, roots=roots, field=field)
    if not path.is_dir():
        raise NotADirectoryError(path)
    return path


__all__ = [
    "reject_control_chars",
    "resolve_regular_path",
    "safe_child_path",
    "safe_existing_dir_path",
    "safe_existing_file_path",
    "safe_existing_path",
    "safe_filename",
    "safe_project_path",
    "strip_windows_verbatim_prefix",
]
