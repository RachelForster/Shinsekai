"""Dependency-free path validation shared across host layers.

All paths influenced by API, plugin, or configuration input should cross this
module before they are used for filesystem I/O.  Compatibility modules may
re-export these helpers, but must not carry their own path-containment logic.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
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


def _has_windows_verbatim_prefix(value: str) -> bool:
    return value.startswith(("\\\\?\\", "//?/"))


def _windows_verbatim_path(value: str) -> str:
    regular = strip_windows_verbatim_prefix(value)
    if regular.startswith("\\\\"):
        return "\\\\?\\UNC\\" + regular[2:]
    return "\\\\?\\" + regular


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


def normalize_path_identity(
    value: str | os.PathLike[str],
    *,
    field: str = "path",
) -> Path:
    """Normalize path spelling without touching the filesystem.

    Use this for comparisons only. Filesystem access must use one of the
    containment-enforcing ``safe_*`` helpers below.
    """

    raw = reject_control_chars(os.fspath(value), field=field)
    expanded = os.path.expanduser(raw)
    return Path(os.path.abspath(os.path.normpath(expanded)))


def is_portable_relative_path(value: str | os.PathLike[str]) -> bool:
    """Return whether a path is relative and non-traversing on POSIX and Windows."""

    try:
        raw = reject_control_chars(os.fspath(value), field="path")
    except ValueError:
        return False
    posix_path = PurePosixPath(raw.replace("\\", "/"))
    windows_path = PureWindowsPath(raw)
    return not (
        posix_path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or ".." in posix_path.parts
    )


def safe_project_path(
    raw_path: str | os.PathLike[str],
    root: Path | None = None,
) -> Path:
    """Resolve ``raw_path`` and require it to remain inside ``root``."""

    base_input = os.path.expanduser(os.fspath(root or os.getcwd()))
    base_verbatim = os.name == "nt" and _has_windows_verbatim_prefix(base_input)
    if os.name == "nt":
        base_input = strip_windows_verbatim_prefix(base_input)
    base = os.path.realpath(os.path.abspath(base_input))
    raw = reject_control_chars(os.fspath(raw_path), field="path")
    raw_verbatim = os.name == "nt" and _has_windows_verbatim_prefix(raw)
    comparison_raw = strip_windows_verbatim_prefix(raw) if os.name == "nt" else raw
    expanded = os.path.expanduser(comparison_raw)
    raw_is_absolute = os.path.isabs(expanded)
    candidate = expanded if os.path.isabs(expanded) else os.path.join(base, expanded)
    # Keep the normalized value itself behind a direct ``startswith`` guard.
    # Besides being easy to audit, this is the containment pattern understood
    # by path-sensitive static analysis.
    resolved = os.path.join(os.path.realpath(os.path.abspath(candidate)), "")
    base_drive = os.path.normcase(os.path.splitdrive(base)[0])
    resolved_drive = os.path.normcase(os.path.splitdrive(resolved)[0])
    if base_drive and resolved_drive and base_drive != resolved_drive:
        raise PermissionError("path is outside project root or uses a different drive")
    if not resolved.startswith(os.path.join(base, "")):
        raise PermissionError("path is outside project root")
    if os.name == "nt" and (raw_verbatim or (base_verbatim and not raw_is_absolute)):
        return Path(_windows_verbatim_path(resolved))
    return Path(resolved)


def safe_child_path(base: Path, raw_path: str | os.PathLike[str]) -> Path:
    """Resolve a request-style child path beneath ``base``."""

    base_input = os.path.expanduser(os.fspath(base))
    base_verbatim = os.name == "nt" and _has_windows_verbatim_prefix(base_input)
    if os.name == "nt":
        base_input = strip_windows_verbatim_prefix(base_input)
    root = os.path.realpath(os.path.abspath(base_input))
    raw = reject_control_chars(os.fspath(raw_path), field="path")
    raw_verbatim = os.name == "nt" and _has_windows_verbatim_prefix(raw)
    comparison_raw = strip_windows_verbatim_prefix(raw) if os.name == "nt" else raw
    if os.path.splitdrive(comparison_raw)[0]:
        raise PermissionError("path is outside base path")
    candidate = os.path.join(root, comparison_raw.lstrip("/\\"))
    resolved = os.path.join(os.path.realpath(os.path.abspath(candidate)), "")
    if not resolved.startswith(os.path.join(root, "")):
        raise PermissionError("path is outside base path")
    if os.name == "nt" and (raw_verbatim or base_verbatim):
        return Path(_windows_verbatim_path(resolved))
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

    raw_verbatim = os.name == "nt" and _has_windows_verbatim_prefix(raw)
    comparison_raw = strip_windows_verbatim_prefix(raw) if os.name == "nt" else raw
    expanded = os.path.expanduser(comparison_raw)
    raw_is_absolute = os.path.isabs(expanded)
    first_root_input = os.path.expanduser(os.fspath(trusted_roots[0]))
    first_root_verbatim = os.name == "nt" and _has_windows_verbatim_prefix(first_root_input)
    if os.name == "nt":
        first_root_input = strip_windows_verbatim_prefix(first_root_input)
    first_root = os.path.realpath(os.path.abspath(first_root_input))
    candidate = expanded if os.path.isabs(expanded) else os.path.join(first_root, expanded)
    resolved = os.path.join(os.path.realpath(os.path.abspath(candidate)), "")
    for root in trusted_roots:
        trusted_input = os.path.expanduser(os.fspath(root))
        if os.name == "nt":
            trusted_input = strip_windows_verbatim_prefix(trusted_input)
        trusted_root = os.path.realpath(os.path.abspath(trusted_input))
        if resolved.startswith(os.path.join(trusted_root, "")):
            if os.name == "nt" and (
                raw_verbatim or (first_root_verbatim and not raw_is_absolute)
            ):
                return Path(_windows_verbatim_path(resolved))
            return Path(resolved)
    raise PermissionError(f"{field} is outside the allowed roots")


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
    "is_portable_relative_path",
    "normalize_path_identity",
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
