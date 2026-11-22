"""Safe ZIP I/O, path relocation, and conflict resolution shared across package exporters."""

from __future__ import annotations

from collections.abc import Iterable
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile

from sdk.path_utils import safe_child_path

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def safe_package_relpath(path: str | os.PathLike[str] | None, field_name: str) -> Path:
    """Interpret package paths written on Windows or POSIX as safe relative paths."""
    raw = str(path or "").replace("\\", "/").strip()
    while raw.startswith("./"):
        raw = raw[2:]
    if not raw:
        raise ValueError(f"{field_name} must not be empty")
    if "\x00" in raw or raw.startswith("/") or _WINDOWS_DRIVE_RE.match(raw):
        raise ValueError(f"{field_name} must be a relative package path: {path!r}")
    if any(part in ("", ".", "..") for part in raw.split("/")):
        raise ValueError(f"{field_name} contains an unsafe path component: {path!r}")
    rel = PurePosixPath(raw)
    return Path(*rel.parts)


def safe_package_name(value: str | os.PathLike[str] | None, field_name: str) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw:
        return ""
    if (
        "\x00" in raw
        or "/" in raw
        or raw in (".", "..")
        or _WINDOWS_DRIVE_RE.match(raw)
    ):
        raise ValueError(f"{field_name} must be a plain package name: {value!r}")
    return raw


def safe_package_basename(path: str | os.PathLike[str] | None, field_name: str) -> str:
    return safe_package_relpath(path, field_name).name


def safe_package_basename_or_legacy_absolute(
    path: str | os.PathLike[str] | None,
    field_name: str,
) -> str:
    """Return a safe package filename, accepting old host-absolute YAML paths."""
    raw = str(path or "").replace("\\", "/").strip()
    if not raw:
        raise ValueError(f"{field_name} must not be empty")
    if "\x00" in raw:
        raise ValueError(f"{field_name} contains an unsafe path component: {path!r}")

    has_windows_drive = _WINDOWS_DRIVE_RE.match(raw)
    is_legacy_absolute = raw.startswith("/") or (
        has_windows_drive is not None and raw[2:3] == "/"
    )
    if not is_legacy_absolute:
        return safe_package_basename(raw, field_name)

    tail = raw[3:] if has_windows_drive else raw
    parts = tail.lstrip("/").split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"{field_name} contains an unsafe path component: {path!r}")
    return safe_package_name(parts[-1], field_name)


def safe_extract_zip(zf: zipfile.ZipFile, target_dir: Path) -> None:
    """Extract zip members after validating every path against Zip Slip traversal."""
    for info in zf.infolist():
        member = str(info.filename or "").replace("\\", "/").rstrip("/")
        if member:
            safe_package_relpath(member, "zip member")
    zf.extractall(target_dir)


def write_directory_zip(source_dir: Path, output_path: str | os.PathLike[str]) -> Path:
    """Compress all files under ``source_dir`` into ``output_path`` atomically."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=out.parent,
        prefix=f".{out.name}.",
        suffix=".zip.tmp",
        delete=False,
    ) as handle:
        tmp_zip = Path(handle.name)
    try:
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(source_dir.rglob("*")):
                if file_path.is_file():
                    zf.write(file_path, file_path.relative_to(source_dir))
        os.replace(tmp_zip, out)
        return out
    finally:
        tmp_zip.unlink(missing_ok=True)


def resolve_name_conflict(name: str, existing_names: set[str]) -> str:
    """Resolve character/background display-name collision with ``（N）`` suffixes."""
    if name not in existing_names:
        return name
    counter = 1
    candidate = f"{name}（{counter}）"
    while candidate in existing_names:
        counter += 1
        candidate = f"{name}（{counter}）"
    return candidate


def resolve_sprite_prefix_conflict(sprite_prefix: str, existing_prefixes: set[str]) -> str:
    """Resolve directory-prefix collision with numeric suffixes."""
    if sprite_prefix not in existing_prefixes:
        return sprite_prefix
    counter = 1
    candidate = f"{sprite_prefix}{counter}"
    while candidate in existing_prefixes:
        counter += 1
        candidate = f"{sprite_prefix}{counter}"
    return candidate


def resolve_underscore_conflict(name: str, existing_names_lower: set[str]) -> str:
    """Resolve case-insensitive collision with ``_N`` suffixes (used by effects)."""
    candidate = name
    counter = 1
    while candidate.lower() in existing_names_lower:
        candidate = f"{name}_{counter}"
        counter += 1
    return candidate


def available_destination(directory: Path, filename: str) -> Path:
    """Return a non-colliding file path inside ``directory``."""
    base_name = safe_package_name(filename, "filename")
    if not base_name:
        raise ValueError("filename must not be empty")
    destination = safe_child_path(directory, base_name)
    counter = 1
    stem = destination.stem
    suffix = destination.suffix
    while destination.exists():
        destination = directory / f"{stem}_{counter}{suffix}"
        counter += 1
    return destination


def available_package_filename(filename: str, used_names_lower: set[str]) -> str:
    """Allocate a case-insensitively unique basename inside a package folder."""
    candidate = safe_package_name(filename, "filename")
    if not candidate:
        raise ValueError("filename must not be empty")
    stem = Path(candidate).stem
    suffix = Path(candidate).suffix
    counter = 1
    while candidate.casefold() in used_names_lower:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def format_restored_path(target: Path, cwd_base: Path | None) -> str:
    """Format restored asset path relative to ``cwd_base`` when possible, else POSIX."""
    if cwd_base is not None:
        try:
            return str(target.relative_to(cwd_base))
        except ValueError:
            pass
    return target.as_posix()


def rollback_staged_assets(created_dirs: Iterable[Path]) -> None:
    """Remove directories created during staging if downstream persistence fails."""
    for directory in reversed(list(created_dirs)):
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)


__all__ = [
    "available_destination",
    "available_package_filename",
    "format_restored_path",
    "resolve_name_conflict",
    "resolve_sprite_prefix_conflict",
    "resolve_underscore_conflict",
    "rollback_staged_assets",
    "safe_extract_zip",
    "safe_package_basename",
    "safe_package_basename_or_legacy_absolute",
    "safe_package_name",
    "safe_package_relpath",
    "write_directory_zip",
]
