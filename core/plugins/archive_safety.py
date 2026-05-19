"""Safety checks for source ZIP archives used by plugin/app updates."""

from __future__ import annotations

import os
import re
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

MAX_ZIP_MEMBER_SIZE = 256 * 1024 * 1024
MAX_ZIP_TOTAL_SIZE = 1024 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100.0

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:$")


class UnsafeArchiveError(ValueError):
    """Raised when an archive member could escape or alter extraction semantics."""


def _is_zip_symlink_or_special(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    if mode == 0:
        return False
    file_type = stat.S_IFMT(mode)
    if file_type == 0:
        return False
    return not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))


def _safe_member_parts(name: str) -> tuple[str, ...]:
    raw = name.strip()
    if not raw:
        raise UnsafeArchiveError("empty ZIP member name")
    if "\x00" in raw or "\\" in raw:
        raise UnsafeArchiveError(f"unsafe ZIP member path: {name!r}")
    path = PurePosixPath(raw)
    parts = path.parts
    if not parts or path.is_absolute():
        raise UnsafeArchiveError(f"unsafe ZIP member path: {name!r}")
    for part in parts:
        if part in ("", ".", "..") or ":" in part or _WINDOWS_DRIVE_RE.match(part):
            raise UnsafeArchiveError(f"unsafe ZIP member path: {name!r}")
    return parts


def validate_zip_single_top_folder(zip_path: Path) -> str:
    """Validate archive members and return the only top-level folder name."""
    total = 0
    top_names: set[str] = set()
    has_file = False
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            parts = _safe_member_parts(info.filename)
            top_names.add(parts[0])
            if len(parts) == 1 and not info.is_dir():
                raise UnsafeArchiveError("ZIP archive must contain a top-level folder")
            if _is_zip_symlink_or_special(info):
                raise UnsafeArchiveError(f"ZIP member is not a regular file: {info.filename!r}")
            if info.is_dir():
                continue
            has_file = True
            if info.file_size > MAX_ZIP_MEMBER_SIZE:
                raise UnsafeArchiveError(f"ZIP member too large: {info.filename!r}")
            total += info.file_size
            if total > MAX_ZIP_TOTAL_SIZE:
                raise UnsafeArchiveError("ZIP archive uncompressed size is too large")
            if info.compress_size == 0 and info.file_size > 0:
                raise UnsafeArchiveError(f"ZIP member has invalid compressed size: {info.filename!r}")
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > MAX_ZIP_COMPRESSION_RATIO:
                    raise UnsafeArchiveError(f"ZIP member compression ratio is too high: {info.filename!r}")
    if not has_file:
        raise UnsafeArchiveError("empty archive")
    if len(top_names) != 1:
        raise UnsafeArchiveError("ZIP archive must contain exactly one top-level folder")
    return next(iter(top_names))


def _ensure_within(root: Path, child: Path) -> None:
    root_resolved = root.resolve()
    child_resolved = child.resolve(strict=False)
    try:
        child_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafeArchiveError(f"ZIP member escapes extraction root: {child}") from exc


def safe_extract_zip_single_top(zip_path: Path, dest_root: Path) -> Path:
    """
    Extract a validated ZIP under ``dest_root`` and return the extracted top folder.

    The archive must contain exactly one top-level folder. Members with absolute
    paths, ``..``, Windows drive paths, symlink/special modes, or zip-bomb-like
    sizes are rejected before any file is written.
    """
    dest_root.mkdir(parents=True, exist_ok=True)
    top = validate_zip_single_top_folder(zip_path)
    top_path = dest_root / top
    _ensure_within(dest_root, top_path)
    if top_path.exists():
        raise FileExistsError(f"extract target already exists: {top_path}")

    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            parts = _safe_member_parts(info.filename)
            target = dest_root.joinpath(*parts)
            _ensure_within(dest_root, target)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                try:
                    os.chmod(target, mode)
                except OSError:
                    pass
    return top_path
