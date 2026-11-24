"""Cross-platform archive creation, SHA-256 checksums, and metadata emission."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
from typing import Sequence
import zipfile

from scripts.portable.targets import PlatformTarget

SUPPORTED_ARCHIVE_FORMATS = ("auto", "zip", "tar.gz", "7z")
ARCHIVE_EXTENSIONS = (".zip", ".tar.gz", ".7z")
SIDECAR_SUFFIXES = ("", ".sha256", ".meta.json")


def cleanup_stale_bundle_artifacts(output_dir: Path) -> list[Path]:
    """Remove stale archives and sidecar files sharing `<output_dir.name>` in `output_dir.parent`."""
    parent = output_dir.parent
    if not parent.is_dir():
        return []
    removed: list[Path] = []
    for ext in ARCHIVE_EXTENSIONS:
        for sidecar in SIDECAR_SUFFIXES:
            candidate = parent / f"{output_dir.name}{ext}{sidecar}"
            if candidate.is_file() or candidate.is_symlink():
                candidate.unlink()
                removed.append(candidate)
    return removed


def resolve_archive_format(
    requested: str,
    *,
    source_root: Path,
    target: PlatformTarget,
) -> str:
    """Resolve 'auto' or an explicit archive format name into a concrete format."""
    fmt = str(requested or "auto").strip().lower()
    if fmt == "auto":
        if target.os_family == "windows" and (source_root / "build_exe" / "7za.exe").is_file():
            return "7z"
        return target.default_archive_format
    if fmt not in ("zip", "tar.gz", "7z"):
        raise ValueError(
            f"Unsupported archive format '{requested}'. Expected one of: {', '.join(SUPPORTED_ARCHIVE_FORMATS)}"
        )
    return fmt


def _find_7z_executable(source_root: Path) -> Path:
    bundled = source_root / "build_exe" / "7za.exe"
    if bundled.is_file():
        return bundled
    for cmd in ("7z", "7zz", "7za"):
        found = shutil.which(cmd)
        if found:
            return Path(found)
    raise FileNotFoundError(
        "7z archive format requested, but neither build_exe/7za.exe nor system 7z/7zz/7za was found."
    )


def _write_zip_archive(output_dir: Path, archive_path: Path) -> Path:
    base_parent = output_dir.parent
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=5,
        allowZip64=True,
    ) as zf:
        entries = sorted(output_dir.rglob("*"), key=lambda path: path.as_posix())
        for entry in entries:
            arcname = entry.relative_to(base_parent).as_posix()
            st = entry.lstat()
            if stat.S_ISLNK(st.st_mode):
                target_link = os.readlink(entry)
                info = zipfile.ZipInfo(arcname)
                info.create_system = 3
                info.external_attr = (st.st_mode & 0xFFFF) << 16
                zf.writestr(info, target_link)
                continue
            if entry.is_dir():
                info = zipfile.ZipInfo(f"{arcname}/")
                info.create_system = 3
                info.external_attr = ((st.st_mode & 0xFFFF) << 16) | 0x10
                zf.writestr(info, b"")
                continue
            info = zipfile.ZipInfo.from_file(entry, arcname=arcname)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3 if os.name != "nt" else 0
            info.external_attr = (st.st_mode & 0xFFFF) << 16
            with entry.open("rb") as src, zf.open(info, "w") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
    return archive_path


def _write_tar_gz_archive(output_dir: Path, archive_path: Path) -> Path:
    with tarfile.open(archive_path, "w:gz", compresslevel=5) as tf:
        tf.add(output_dir, arcname=output_dir.name, recursive=True)
    return archive_path


def compress_bundle(
    source_root: Path,
    output_dir: Path,
    *,
    target: PlatformTarget,
    archive_format: str = "auto",
) -> Path:
    """Compress the assembled portable directory into a distributable archive."""
    resolved_fmt = resolve_archive_format(archive_format, source_root=source_root, target=target)
    if resolved_fmt == "7z":
        seven_zip = _find_7z_executable(source_root)
        archive_path = output_dir.parent / f"{output_dir.name}.7z"
        if archive_path.exists():
            archive_path.unlink()
        subprocess.run(
            [str(seven_zip), "a", "-t7z", "-mx=5", str(archive_path), output_dir.name],
            cwd=output_dir.parent,
            check=True,
        )
        return archive_path

    if resolved_fmt == "tar.gz":
        archive_path = output_dir.parent / f"{output_dir.name}.tar.gz"
        if archive_path.exists():
            archive_path.unlink()
        return _write_tar_gz_archive(output_dir, archive_path)

    archive_path = output_dir.parent / f"{output_dir.name}.zip"
    if archive_path.exists():
        archive_path.unlink()
    return _write_zip_archive(output_dir, archive_path)


def compute_sha256(file_path: Path) -> str:
    """Compute lowercase hexadecimal SHA-256 digest of a file."""
    hasher = hashlib.sha256()
    with file_path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_sha256_file(archive_path: Path, *, digest: str | None = None) -> tuple[Path, str]:
    """Write a standard `<archive>.sha256` sidecar file and return `(path, digest)`."""
    resolved_digest = digest or compute_sha256(archive_path)
    sha256_path = archive_path.with_name(f"{archive_path.name}.sha256")
    sha256_path.write_text(f"{resolved_digest}  {archive_path.name}\n", encoding="utf-8")
    return sha256_path, resolved_digest


def write_bundle_metadata(
    archive_path: Path,
    *,
    version: str,
    target: PlatformTarget,
    sha256: str,
    included_models: Sequence[str],
    archive_format: str,
    llama_cpp_tag: str,
) -> Path:
    """Write `<archive>.meta.json` describing the built portable archive."""
    meta_path = archive_path.with_name(f"{archive_path.name}.meta.json")
    payload = {
        "version": version,
        "platform": target.name,
        "os_family": target.os_family,
        "arch": target.arch,
        "archive_name": archive_path.name,
        "archive_format": archive_format,
        "size_bytes": archive_path.stat().st_size,
        "sha256": sha256,
        "included_models": list(included_models),
        "llama_cpp_tag": llama_cpp_tag,
    }
    meta_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return meta_path
