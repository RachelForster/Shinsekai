"""Stable, portable archive validation and link-free extraction primitives."""

from __future__ import annotations

import os
import shutil
import stat
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sdk.file_transactions import (
    capture_directory_identity,
    file_snapshot_is_stable,
    inspect_portable_directory_tree_with_metadata,
    open_binary_read_without_links,
    open_binary_write_exclusive_without_links,
    portable_name_key,
    require_directory_identity,
)
from sdk.path_contract import (
    _metadata_is_link_or_reparse_point,
    path_is_within,
    path_is_link_or_reparse_point,
    require_symlink_free_absolute_path,
    safe_path_component,
)


class UnsafeArchiveError(ValueError):
    """Raised before extraction when an archive cannot map to portable paths."""


@dataclass(frozen=True)
class ZipExtraction:
    top_level: str | None
    file_count: int


@dataclass(frozen=True)
class _Entry:
    info: zipfile.ZipInfo
    relative: Path
    is_directory: bool


@dataclass(frozen=True)
class _TarEntry:
    member: tarfile.TarInfo
    relative: Path
    is_directory: bool


@dataclass(frozen=True)
class _ZipSource:
    path: Path
    archive_name: str
    identity: os.stat_result
    parent: Path
    parent_identity: os.stat_result


def _portable_member_parts(raw_name: str) -> tuple[tuple[str, ...], bool]:
    normalized = str(raw_name or "").replace("\\", "/")
    if normalized.startswith("/"):
        raise UnsafeArchiveError(f"unsafe archive path: {raw_name!r}")
    is_directory = normalized.endswith("/")
    if is_directory and normalized.endswith("//"):
        raise UnsafeArchiveError(f"unsafe archive path: {raw_name!r}")
    member = normalized[:-1] if is_directory else normalized
    if not member:
        return (), is_directory
    if member != member.strip():
        raise UnsafeArchiveError(f"unsafe archive path: {raw_name!r}")
    parts = tuple(member.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise UnsafeArchiveError(f"unsafe archive path: {raw_name!r}")
    if parts[0].startswith("~"):
        raise UnsafeArchiveError(f"unsafe archive home-relative path: {raw_name!r}")
    for part in parts:
        try:
            safe_path_component(part, field="archive path component")
        except ValueError as exc:
            raise UnsafeArchiveError(f"non-portable archive path: {raw_name!r}") from exc
    return parts, is_directory


def validate_archive_member_names(names: list[str] | tuple[str, ...]) -> None:
    """Validate portable member names before delegating to another extractor.

    Some formats (notably 7z) require an external extraction backend.  This
    preflight still enforces the traversal, case-collision, duplicate, and
    file/directory invariants used by the manual ZIP/TAR paths.
    """

    entry_types: dict[tuple[str, ...], str] = {}
    prefix_spellings: dict[tuple[str, ...], tuple[str, ...]] = {}
    file_count = 0
    for raw_name in names:
        parts, is_directory = _portable_member_parts(raw_name)
        if not parts:
            continue
        folded = tuple(portable_name_key(part) for part in parts)
        for index in range(1, len(folded) + 1):
            folded_prefix = folded[:index]
            spelling = parts[:index]
            previous_spelling = prefix_spellings.setdefault(folded_prefix, spelling)
            if previous_spelling != spelling:
                raise UnsafeArchiveError(
                    f"archive paths differ only by case: {raw_name!r}"
                )
        if folded in entry_types:
            raise UnsafeArchiveError(f"duplicate portable archive path: {raw_name!r}")
        for index in range(1, len(folded)):
            if entry_types.get(folded[:index]) == "file":
                raise UnsafeArchiveError(f"archive path is nested below a file: {raw_name!r}")
        if not is_directory and any(
            len(existing) > len(folded) and existing[: len(folded)] == folded
            for existing in entry_types
        ):
            raise UnsafeArchiveError(f"archive file conflicts with a directory: {raw_name!r}")
        entry_types[folded] = "directory" if is_directory else "file"
        if not is_directory:
            file_count += 1
    if file_count == 0:
        raise UnsafeArchiveError("archive contains no regular files")


def write_zip_files_without_links(
    archive: zipfile.ZipFile,
    members: list[tuple[Path, str]] | tuple[tuple[Path, str], ...],
) -> int:
    """Stream exact regular files into a ZIP after validating the member set.

    The complete archive namespace is checked before the first new member is
    written.  Every source is then opened through the link-free file contract,
    closing the validation/read race that ``ZipFile.write`` otherwise leaves.
    """

    normalized: list[tuple[Path, str]] = []
    for source, raw_name in members:
        parts, is_directory = _portable_member_parts(raw_name)
        if not parts or is_directory:
            raise UnsafeArchiveError(f"archive member must be a regular file: {raw_name!r}")
        source_path = require_symlink_free_absolute_path(
            source,
            field="archive source file",
        )
        normalized.append((source_path, "/".join(parts)))

    validate_archive_member_names(tuple([*archive.namelist(), *(name for _, name in normalized)]))
    pinned: list[_ZipSource] = []
    for source, archive_name in normalized:
        source_identity = source.lstat()
        if (
            _metadata_is_link_or_reparse_point(source_identity)
            or not stat.S_ISREG(source_identity.st_mode)
        ):
            raise PermissionError(f"archive source must be a regular non-link file: {source}")
        parent, parent_identity = capture_directory_identity(
            source.parent,
            field="archive source parent",
        )
        pinned.append(
            _ZipSource(
                path=source,
                archive_name=archive_name,
                identity=source_identity,
                parent=parent,
                parent_identity=parent_identity,
            )
        )
    return _write_pinned_zip_sources(archive, pinned)


def write_zip_file_snapshots_without_links(
    archive: zipfile.ZipFile,
    members: (
        list[tuple[Path, str, os.stat_result, os.stat_result]]
        | tuple[tuple[Path, str, os.stat_result, os.stat_result], ...]
    ),
) -> int:
    """Write previously observed file identities without reopening peers.

    Directory walkers use this variant to carry the exact leaf and parent
    identities from enumeration into archival.  A same-named file or parent
    that appears later is therefore never substituted into the ZIP.
    """

    pinned: list[_ZipSource] = []
    for source, raw_name, source_identity, parent_identity in members:
        parts, is_directory = _portable_member_parts(raw_name)
        if not parts or is_directory:
            raise UnsafeArchiveError(
                f"archive member must be a regular file: {raw_name!r}"
            )
        source_path = require_symlink_free_absolute_path(
            source,
            field="archive source file",
        )
        parent, current_parent_identity = capture_directory_identity(
            source_path.parent,
            field="archive source parent",
        )
        try:
            current_source_identity = source_path.lstat()
        except FileNotFoundError:
            raise PermissionError(
                f"archive source disappeared before read: {source_path}"
            ) from None
        if (
            not os.path.samestat(parent_identity, current_parent_identity)
            or _metadata_is_link_or_reparse_point(current_source_identity)
            or not stat.S_ISREG(current_source_identity.st_mode)
            or not os.path.samestat(source_identity, current_source_identity)
        ):
            raise PermissionError(
                f"archive source identity changed before read: {source_path}"
            )
        pinned.append(
            _ZipSource(
                path=source_path,
                archive_name="/".join(parts),
                identity=source_identity,
                parent=parent,
                parent_identity=parent_identity,
            )
        )
    validate_archive_member_names(
        tuple(
            [
                *archive.namelist(),
                *(source.archive_name for source in pinned),
            ]
        )
    )
    return _write_pinned_zip_sources(archive, pinned)


def _write_pinned_zip_sources(
    archive: zipfile.ZipFile,
    sources: list[_ZipSource],
    *,
    expected_root: tuple[Path, os.stat_result] | None = None,
) -> int:
    for source in sources:
        if expected_root is not None:
            require_directory_identity(
                expected_root[0],
                expected_root[1],
                field="archive source root",
            )
        with tempfile.SpooledTemporaryFile(
            max_size=8 * 1024 * 1024,
            mode="w+b",
        ) as staged:
            with open_binary_read_without_links(
                source.path,
                expected_identity=source.identity,
                expected_parent_identity=source.parent_identity,
            ) as input_file:
                metadata = os.fstat(input_file.fileno())
                shutil.copyfileobj(
                    input_file,
                    staged,
                    length=1024 * 1024,
                )
                final_metadata = os.fstat(input_file.fileno())
            if not file_snapshot_is_stable(metadata, final_metadata):
                raise PermissionError(
                    "archive source changed while it was being read: "
                    f"{source.path}"
                )
            staged.seek(0)
            try:
                date_time = time.localtime(metadata.st_mtime)[:6]
            except (OSError, OverflowError, ValueError):
                date_time = (1980, 1, 1, 0, 0, 0)
            if date_time[0] < 1980:
                date_time = (1980, 1, 1, 0, 0, 0)
            elif date_time[0] > 2107:
                date_time = (2107, 12, 31, 23, 59, 58)
            info = zipfile.ZipInfo(source.archive_name, date_time=date_time)
            info.external_attr = (metadata.st_mode & 0xFFFF) << 16
            info.compress_type = archive.compression
            with archive.open(info, "w", force_zip64=True) as output:
                shutil.copyfileobj(staged, output, length=1024 * 1024)
        require_directory_identity(
            source.parent,
            source.parent_identity,
            field="archive source parent",
        )
        try:
            current_identity = source.path.lstat()
        except FileNotFoundError:
            raise PermissionError(
                f"archive source disappeared during read: {source.path}"
            ) from None
        if (
            _metadata_is_link_or_reparse_point(current_identity)
            or not os.path.samestat(source.identity, current_identity)
        ):
            raise PermissionError(
                f"archive source identity changed during read: {source.path}"
            )
        if expected_root is not None:
            require_directory_identity(
                expected_root[0],
                expected_root[1],
                field="archive source root",
            )
    return len(sources)


def write_directory_to_zip_without_links(
    archive: zipfile.ZipFile,
    source_root: str | Path,
) -> int:
    """Archive a complete portable directory tree without following aliases."""

    root = require_symlink_free_absolute_path(
        source_root,
        field="archive source directory",
    )
    root_identity, directories, files = inspect_portable_directory_tree_with_metadata(
        root
    )
    directory_identities = dict(directories)
    directory_identities[Path()] = root_identity
    pinned = [
        _ZipSource(
            path=root / relative,
            archive_name=relative.as_posix(),
            identity=identity,
            parent=root / relative.parent,
            parent_identity=directory_identities[relative.parent],
        )
        for relative, identity in files
    ]
    validate_archive_member_names(
        tuple([*archive.namelist(), *(source.archive_name for source in pinned)])
    )
    return _write_pinned_zip_sources(
        archive,
        pinned,
        expected_root=(root, root_identity),
    )


def _validated_entries(
    zf: zipfile.ZipFile,
    *,
    require_single_root: bool,
    strip_single_root: bool,
) -> tuple[list[_Entry], str | None]:
    parsed: list[tuple[zipfile.ZipInfo, tuple[str, ...], bool]] = []
    roots: set[str] = set()
    for info in zf.infolist():
        parts, directory_by_name = _portable_member_parts(info.filename)
        if not parts:
            continue
        unix_mode = info.external_attr >> 16
        file_type = stat.S_IFMT(unix_mode)
        if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise UnsafeArchiveError(f"archive contains a link or special file: {info.filename!r}")
        if directory_by_name and file_type == stat.S_IFREG:
            raise UnsafeArchiveError(
                f"archive regular file has a directory-shaped name: {info.filename!r}"
            )
        is_directory = directory_by_name or file_type == stat.S_IFDIR
        roots.add(parts[0])
        parsed.append((info, parts, is_directory))

    files = [entry for entry in parsed if not entry[2]]
    if not files:
        raise UnsafeArchiveError("archive contains no regular files")
    folded_roots = {portable_name_key(root) for root in roots}
    if len(roots) != len(folded_roots):
        raise UnsafeArchiveError("archive top-level paths differ only by case")
    if (require_single_root or strip_single_root) and len(folded_roots) != 1:
        raise UnsafeArchiveError("archive must contain exactly one top-level directory")

    top_level = parsed[0][1][0] if len(folded_roots) == 1 else None
    if (require_single_root or strip_single_root) and any(len(parts) < 2 for _, parts, _ in files):
        raise UnsafeArchiveError("archive files must be nested below one top-level directory")

    entries: list[_Entry] = []
    entry_types: dict[tuple[str, ...], str] = {}
    prefix_spellings: dict[tuple[str, ...], tuple[str, ...]] = {}
    for info, original_parts, is_directory in parsed:
        parts = original_parts[1:] if strip_single_root else original_parts
        if not parts:
            continue
        folded = tuple(portable_name_key(part) for part in parts)
        for index in range(1, len(folded) + 1):
            folded_prefix = folded[:index]
            spelling = parts[:index]
            previous_spelling = prefix_spellings.setdefault(folded_prefix, spelling)
            if previous_spelling != spelling:
                raise UnsafeArchiveError(
                    f"archive paths differ only by case: {info.filename!r}"
                )
        if folded in entry_types:
            raise UnsafeArchiveError(f"duplicate portable archive path: {info.filename!r}")
        for index in range(1, len(folded)):
            if entry_types.get(folded[:index]) == "file":
                raise UnsafeArchiveError(f"archive path is nested below a file: {info.filename!r}")
        if not is_directory and any(
            len(existing) > len(folded) and existing[: len(folded)] == folded
            for existing in entry_types
        ):
            raise UnsafeArchiveError(f"archive file conflicts with a directory: {info.filename!r}")
        entry_types[folded] = "directory" if is_directory else "file"
        entries.append(_Entry(info=info, relative=Path(*parts), is_directory=is_directory))
    return entries, top_level


def extract_zip_safely(
    zf: zipfile.ZipFile,
    target_dir: str | Path,
    *,
    require_single_root: bool = False,
    strip_single_root: bool = False,
) -> ZipExtraction:
    """Validate every member first, then extract regular files without links."""

    entries, top_level = _validated_entries(
        zf,
        require_single_root=require_single_root,
        strip_single_root=strip_single_root,
    )
    target_dir = require_symlink_free_absolute_path(
        target_dir,
        field="archive extraction target",
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    target_dir = require_symlink_free_absolute_path(
        target_dir,
        field="archive extraction target",
    )
    target_dir, root_identity = capture_directory_identity(
        target_dir,
        field="archive extraction target",
    )
    root = target_dir.resolve(strict=True)
    _preflight_destinations(
        target_dir,
        root,
        entries,
        expected_root_identity=root_identity,
    )
    file_count = 0
    for entry in entries:
        _require_extraction_root_identity(target_dir, root_identity)
        destination = target_dir / entry.relative
        if path_is_link_or_reparse_point(destination):
            raise UnsafeArchiveError(f"archive target is a symbolic link: {entry.relative.as_posix()!r}")
        resolved = destination.resolve(strict=False)
        if not path_is_within(resolved, root):
            raise UnsafeArchiveError(f"archive member escapes extraction root: {entry.info.filename!r}")
        if entry.is_directory:
            destination.mkdir(parents=True, exist_ok=True)
            require_symlink_free_absolute_path(
                destination,
                field="archive directory destination",
            )
            _require_extraction_root_identity(target_dir, root_identity)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        require_symlink_free_absolute_path(
            destination,
            field="archive file destination",
            include_leaf=False,
        )
        _require_extraction_root_identity(target_dir, root_identity)
        destination_parent, destination_parent_identity = capture_directory_identity(
            destination.parent,
            field="archive file destination parent",
        )
        with (
            zf.open(entry.info, "r") as source,
            open_binary_write_exclusive_without_links(
                destination,
                expected_parent_identity=destination_parent_identity,
            ) as output,
        ):
            output_identity = os.fstat(output.fileno())
            shutil.copyfileobj(source, output)
        _require_extraction_root_identity(target_dir, root_identity)
        require_directory_identity(
            destination_parent,
            destination_parent_identity,
            field="archive file destination parent",
        )
        _require_extracted_file_identity(
            destination,
            output_identity,
            entry.relative,
        )
        file_count += 1
    _require_extraction_root_identity(target_dir, root_identity)
    return ZipExtraction(top_level=top_level, file_count=file_count)


def _require_extraction_root_identity(
    target_dir: Path,
    expected_identity: os.stat_result,
) -> None:
    try:
        require_directory_identity(
            target_dir,
            expected_identity,
            field="archive extraction target",
        )
    except (OSError, ValueError) as exc:
        raise UnsafeArchiveError(
            "archive extraction target changed identity during extraction"
        ) from exc


def _require_extracted_file_identity(
    destination: Path,
    expected_identity: os.stat_result,
    relative: Path,
) -> None:
    try:
        current_identity = destination.lstat()
    except OSError as exc:
        raise UnsafeArchiveError(
            f"archive output disappeared: {relative.as_posix()!r}"
        ) from exc
    if (
        _metadata_is_link_or_reparse_point(current_identity)
        or not stat.S_ISREG(current_identity.st_mode)
        or not os.path.samestat(expected_identity, current_identity)
    ):
        raise UnsafeArchiveError(
            f"archive output changed identity: {relative.as_posix()!r}"
        )


def _preflight_destinations(
    target_dir: Path,
    root: Path,
    entries: list[_Entry] | list[_TarEntry],
    *,
    expected_root_identity: os.stat_result,
) -> None:
    """Reject link and existing-path conflicts before the first file is written."""

    for entry in entries:
        _require_extraction_root_identity(target_dir, expected_root_identity)
        destination = target_dir / entry.relative
        cursor = target_dir
        for index, part in enumerate(entry.relative.parts):
            cursor = cursor / part
            try:
                metadata = cursor.lstat()
            except FileNotFoundError:
                metadata = None
            except OSError as exc:
                raise UnsafeArchiveError(
                    f"archive target cannot be inspected: {entry.relative.as_posix()!r}"
                ) from exc
            if metadata is not None and _metadata_is_link_or_reparse_point(metadata):
                raise UnsafeArchiveError(
                    "archive target contains a symbolic link or reparse point: "
                    f"{entry.relative.as_posix()!r}"
                )
            if (
                index < len(entry.relative.parts) - 1
                and metadata is not None
                and not stat.S_ISDIR(metadata.st_mode)
            ):
                raise UnsafeArchiveError(
                    "archive target parent conflicts with an existing non-directory: "
                    f"{entry.relative.as_posix()!r}"
                )
        if not path_is_within(destination.resolve(strict=False), root):
            raise UnsafeArchiveError(
                f"archive member escapes extraction root: {entry.relative.as_posix()!r}"
            )
        if entry.is_directory:
            if destination.exists() and not destination.is_dir():
                raise UnsafeArchiveError(
                    f"archive directory conflicts with an existing file: {entry.relative.as_posix()!r}"
                )
        elif destination.exists():
                raise UnsafeArchiveError(
                    f"archive file already exists: {entry.relative.as_posix()!r}"
                )
    _require_extraction_root_identity(target_dir, expected_root_identity)


def extract_tar_safely(tf: tarfile.TarFile, target_dir: str | Path) -> ZipExtraction:
    """Validate a TAR completely and extract only ordinary files/directories."""

    target_dir = require_symlink_free_absolute_path(
        target_dir,
        field="archive extraction target",
    )
    parsed: list[_TarEntry] = []
    roots: set[str] = set()
    entry_types: dict[tuple[str, ...], str] = {}
    prefix_spellings: dict[tuple[str, ...], tuple[str, ...]] = {}
    for member in tf.getmembers():
        parts, directory_by_name = _portable_member_parts(member.name)
        if not parts:
            continue
        if member.isfile() and directory_by_name:
            raise UnsafeArchiveError(
                f"archive regular file has a directory-shaped name: {member.name!r}"
            )
        is_directory = member.isdir()
        if not is_directory and not member.isfile():
            raise UnsafeArchiveError(f"archive contains a link or special file: {member.name!r}")
        folded = tuple(portable_name_key(part) for part in parts)
        for index in range(1, len(folded) + 1):
            folded_prefix = folded[:index]
            spelling = parts[:index]
            previous_spelling = prefix_spellings.setdefault(folded_prefix, spelling)
            if previous_spelling != spelling:
                raise UnsafeArchiveError(f"archive paths differ only by case: {member.name!r}")
        if folded in entry_types:
            raise UnsafeArchiveError(f"duplicate portable archive path: {member.name!r}")
        for index in range(1, len(folded)):
            if entry_types.get(folded[:index]) == "file":
                raise UnsafeArchiveError(f"archive path is nested below a file: {member.name!r}")
        if not is_directory and any(
            len(existing) > len(folded) and existing[: len(folded)] == folded
            for existing in entry_types
        ):
            raise UnsafeArchiveError(f"archive file conflicts with a directory: {member.name!r}")
        entry_types[folded] = "directory" if is_directory else "file"
        roots.add(parts[0])
        parsed.append(_TarEntry(member=member, relative=Path(*parts), is_directory=is_directory))

    files = [entry for entry in parsed if not entry.is_directory]
    if not files:
        raise UnsafeArchiveError("archive contains no regular files")
    folded_roots = {portable_name_key(root) for root in roots}
    if len(roots) != len(folded_roots):
        raise UnsafeArchiveError("archive top-level paths differ only by case")
    top_level = parsed[0].relative.parts[0] if len(folded_roots) == 1 else None

    target_dir.mkdir(parents=True, exist_ok=True)
    target_dir = require_symlink_free_absolute_path(
        target_dir,
        field="archive extraction target",
    )
    target_dir, root_identity = capture_directory_identity(
        target_dir,
        field="archive extraction target",
    )
    root = target_dir.resolve(strict=True)
    _preflight_destinations(
        target_dir,
        root,
        parsed,
        expected_root_identity=root_identity,
    )
    for entry in parsed:
        _require_extraction_root_identity(target_dir, root_identity)
        destination = target_dir / entry.relative
        if path_is_link_or_reparse_point(destination) or not path_is_within(
            destination.resolve(strict=False),
            root,
        ):
            raise UnsafeArchiveError(f"archive member escapes extraction root: {entry.member.name!r}")
        if entry.is_directory:
            destination.mkdir(parents=True, exist_ok=True)
            require_symlink_free_absolute_path(
                destination,
                field="archive directory destination",
            )
            _require_extraction_root_identity(target_dir, root_identity)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        require_symlink_free_absolute_path(
            destination,
            field="archive file destination",
            include_leaf=False,
        )
        _require_extraction_root_identity(target_dir, root_identity)
        destination_parent, destination_parent_identity = capture_directory_identity(
            destination.parent,
            field="archive file destination parent",
        )
        source = tf.extractfile(entry.member)
        if source is None:
            raise UnsafeArchiveError(f"archive file cannot be read: {entry.member.name!r}")
        with source, open_binary_write_exclusive_without_links(
            destination,
            expected_parent_identity=destination_parent_identity,
        ) as output:
            output_identity = os.fstat(output.fileno())
            shutil.copyfileobj(source, output)
        _require_extraction_root_identity(target_dir, root_identity)
        require_directory_identity(
            destination_parent,
            destination_parent_identity,
            field="archive file destination parent",
        )
        _require_extracted_file_identity(
            destination,
            output_identity,
            entry.relative,
        )
    _require_extraction_root_identity(target_dir, root_identity)
    return ZipExtraction(top_level=top_level, file_count=len(files))


__all__ = [
    "UnsafeArchiveError",
    "ZipExtraction",
    "extract_tar_safely",
    "extract_zip_safely",
    "validate_archive_member_names",
    "write_directory_to_zip_without_links",
    "write_zip_file_snapshots_without_links",
    "write_zip_files_without_links",
]
