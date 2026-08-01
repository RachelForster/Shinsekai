"""Stable, host-neutral filesystem transaction primitives for extensions.

The public functions in this module depend only on the standard library and
other SDK path contracts. They deliberately expose no Shinsekai project state;
callers must provide the exact roots and identities they are authorized to
mutate.
"""

from __future__ import annotations

import ctypes
import errno
import os
import shutil
import stat
import sys
import tempfile
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import BinaryIO, Iterator, TextIO

from .path_contract import (
    _metadata_is_link_or_reparse_point,
    managed_child_path,
    path_is_link_or_reparse_point,
    portable_path_component_prefix,
    require_symlink_free_absolute_path,
    safe_path_component,
    safe_path_component_with_suffix,
)


_EXCLUSIVE_FILE_PUBLICATION_LOCK = threading.Lock()
_DIRECTORY_PUBLICATION_LOCK = threading.RLock()
_UNSPECIFIED_IDENTITY = object()
_TEMPFILE_RANDOM_TOKEN_RESERVE = 16


def private_sibling_path(
    path: str | os.PathLike[str],
    suffix: str,
    *,
    field: str = "private sibling path",
) -> Path:
    """Return a portable private sibling while preserving an exact suffix."""

    target = Path(path)
    name = safe_path_component_with_suffix(
        f".{target.name}",
        suffix,
        field=field,
    )
    return target.with_name(name)


def _serialized_path_mutation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _DIRECTORY_PUBLICATION_LOCK:
            return function(*args, **kwargs)

    return wrapped


def _exact_path(
    value: str | os.PathLike[str],
    *,
    field: str,
    allow_filesystem_root: bool = False,
) -> Path:
    return require_symlink_free_absolute_path(
        value,
        field=field,
        allow_filesystem_root=allow_filesystem_root,
    )


def portable_name_key(value: str) -> str:
    """Return the collision key used by common case-insensitive filesystems."""

    return unicodedata.normalize("NFC", str(value)).casefold()


def create_private_temporary_directory(
    *,
    prefix: str,
    directory: str | os.PathLike[str] | None = None,
) -> tuple[Path, os.stat_result]:
    """Create a private temporary directory and return its pinned identity.

    ``tempfile.TemporaryDirectory`` later removes whatever occupies its name.
    Long-running encoders, extractors, and network tasks must instead remember
    the directory created at entry so cleanup cannot delete a replacement that
    appeared after a rename or a peer race.
    """

    if (
        not prefix
        or prefix != prefix.strip()
        or "\x00" in prefix
        or "/" in prefix
        or "\\" in prefix
    ):
        raise ValueError("temporary directory prefix must be one exact path component")
    prefix = portable_path_component_prefix(
        prefix,
        reserved_suffix_bytes=_TEMPFILE_RANDOM_TOKEN_RESERVE,
        field="temporary directory prefix",
    )

    parent: Path | None = None
    if directory is not None:
        parent = _exact_path(directory, field="temporary directory parent")
        if path_is_link_or_reparse_point(parent) or not parent.is_dir():
            raise NotADirectoryError(parent)

    raw_path = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    raw_identity = raw_path.lstat()
    path = raw_path.resolve(strict=True)
    path = _exact_path(path, field="private temporary directory")
    identity = path.lstat()
    if (
        _metadata_is_link_or_reparse_point(identity)
        or not stat.S_ISDIR(identity.st_mode)
        or not os.path.samestat(raw_identity, identity)
    ):
        raise PermissionError("private temporary directory changed identity during creation")
    return path, identity


@contextmanager
def private_temporary_directory(
    *,
    prefix: str,
    directory: str | os.PathLike[str] | None = None,
) -> Iterator[Path]:
    """Yield an owned temporary directory and clean only that exact identity."""

    path, identity = create_private_temporary_directory(
        prefix=prefix,
        directory=directory,
    )
    try:
        yield path
    finally:
        try:
            remove_directory_without_links(path, expected_identity=identity)
        except (OSError, ValueError):
            # The directory may have been atomically published or replaced.
            # In either case the expected identity prevents deleting a peer.
            pass


def _native_rename_without_overwrite(
    source: Path,
    destination: Path,
    *,
    expected_source_identity: os.stat_result,
    expected_source_parent_identity: os.stat_result,
    expected_destination_parent_identity: os.stat_result,
) -> None:
    """Invoke the host's atomic no-replace rename primitive.

    POSIX calls are directory-descriptor relative. Full-path ``renameat2``
    with ``AT_FDCWD`` would re-resolve a parent that changed after validation
    and could move a peer's same-named object from the replacement directory.
    """

    if os.name == "nt":
        # Windows MoveFile semantics, which back ``os.rename``, fail when the
        # destination already exists.
        if (
            not os.path.samestat(
                expected_source_parent_identity,
                source.parent.lstat(),
            )
            or not os.path.samestat(
                expected_destination_parent_identity,
                destination.parent.lstat(),
            )
            or not os.path.samestat(expected_source_identity, source.lstat())
        ):
            raise PermissionError("rename path identity changed before publication")
        if os.path.lexists(destination):
            raise FileExistsError(destination)
        os.rename(source, destination)
        return

    libc = ctypes.CDLL(None, use_errno=True)
    directory_flags = os.O_RDONLY
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    source_parent_descriptor = os.open(source.parent, directory_flags)
    destination_parent_descriptor = -1
    try:
        destination_parent_descriptor = os.open(
            destination.parent,
            directory_flags,
        )
        if not os.path.samestat(
            expected_source_parent_identity,
            os.fstat(source_parent_descriptor),
        ):
            raise PermissionError("rename source parent identity changed")
        if not os.path.samestat(
            expected_destination_parent_identity,
            os.fstat(destination_parent_descriptor),
        ):
            raise PermissionError("rename destination parent identity changed")
        current_source_identity = os.stat(
            source.name,
            dir_fd=source_parent_descriptor,
            follow_symlinks=False,
        )
        if not os.path.samestat(
            expected_source_identity,
            current_source_identity,
        ):
            raise PermissionError("rename source identity changed")
        try:
            os.stat(
                destination.name,
                dir_fd=destination_parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(destination)

        source_bytes = os.fsencode(source.name)
        destination_bytes = os.fsencode(destination.name)
        if sys.platform.startswith("linux"):
            renameat2 = getattr(libc, "renameat2", None)
            if renameat2 is None:
                raise OSError(
                    errno.ENOTSUP,
                    "atomic no-replace rename is unavailable on this Linux runtime",
                    destination,
                )
            renameat2.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            renameat2.restype = ctypes.c_int
            result = renameat2(
                source_parent_descriptor,
                source_bytes,
                destination_parent_descriptor,
                destination_bytes,
                1,  # RENAME_NOREPLACE
            )
        elif sys.platform == "darwin":
            renameatx_np = getattr(libc, "renameatx_np", None)
            if renameatx_np is None:
                raise OSError(
                    errno.ENOTSUP,
                    "atomic descriptor-relative no-replace rename is unavailable "
                    "on this macOS runtime",
                    destination,
                )
            renameatx_np.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            renameatx_np.restype = ctypes.c_int
            result = renameatx_np(
                source_parent_descriptor,
                source_bytes,
                destination_parent_descriptor,
                destination_bytes,
                0x00000004,  # RENAME_EXCL
            )
        else:
            raise OSError(
                errno.ENOTSUP,
                "atomic no-replace rename is unavailable on this platform",
                destination,
            )

        if result != 0:
            error_number = ctypes.get_errno()
            raise OSError(
                error_number,
                os.strerror(error_number),
                destination,
            )
        published_identity = os.stat(
            destination.name,
            dir_fd=destination_parent_descriptor,
            follow_symlinks=False,
        )
        if not os.path.samestat(expected_source_identity, published_identity):
            raise PermissionError(
                "rename destination does not contain the source identity"
            )
    finally:
        if destination_parent_descriptor >= 0:
            os.close(destination_parent_descriptor)
        os.close(source_parent_descriptor)


@_serialized_path_mutation
def rename_path_without_overwrite(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    expected_identity: os.stat_result | None = None,
    expected_source_parent_identity: os.stat_result | None = None,
    expected_destination_parent_identity: os.stat_result | None = None,
) -> Path:
    """Atomically move one exact path while preserving every occupied target.

    A preceding ``exists`` check cannot make POSIX ``rename`` safe: another
    process can create a file or an empty directory between the check and the
    rename, and POSIX then replaces it.  Use the host no-replace primitive and
    verify that the published identity is the exact source captured before the
    operation.
    """

    source_path = require_symlink_free_absolute_path(
        source,
        field="rename source",
        include_leaf=False,
    )
    target = require_symlink_free_absolute_path(
        destination,
        field="rename destination",
        include_leaf=False,
    )
    if source_path == target:
        raise ValueError("rename source and destination must differ")
    source_parent = require_symlink_free_absolute_path(
        source_path.parent,
        field="rename source parent",
    )
    target_parent = require_symlink_free_absolute_path(
        target.parent,
        field="rename destination parent",
    )
    if not source_parent.is_dir():
        raise NotADirectoryError(source_parent)
    if not target_parent.is_dir():
        raise NotADirectoryError(target_parent)
    source_parent_metadata = source_parent.lstat()
    target_parent_metadata = target_parent.lstat()
    if (
        expected_source_parent_identity is not None
        and not os.path.samestat(
            expected_source_parent_identity,
            source_parent_metadata,
        )
    ):
        raise PermissionError(
            f"rename source parent identity changed: {source_parent}"
        )
    if (
        expected_destination_parent_identity is not None
        and not os.path.samestat(
            expected_destination_parent_identity,
            target_parent_metadata,
        )
    ):
        raise PermissionError(
            f"rename destination parent identity changed: {target_parent}"
        )

    try:
        source_metadata = source_path.lstat()
    except FileNotFoundError:
        raise FileNotFoundError(source_path) from None
    if (
        expected_identity is not None
        and not os.path.samestat(expected_identity, source_metadata)
    ):
        raise PermissionError(f"rename source identity changed: {source_path}")
    if os.path.lexists(target):
        raise FileExistsError(target)
    ensure_portable_name_available(
        target_parent,
        target.name,
        expected_directory_identity=target_parent_metadata,
    )

    _native_rename_without_overwrite(
        source_path,
        target,
        expected_source_identity=source_metadata,
        expected_source_parent_identity=source_parent_metadata,
        expected_destination_parent_identity=target_parent_metadata,
    )
    if (
        not os.path.samestat(source_parent_metadata, source_parent.lstat())
        or not os.path.samestat(target_parent_metadata, target_parent.lstat())
    ):
        raise PermissionError("rename parent identity changed during publication")
    try:
        published_metadata = target.lstat()
    except FileNotFoundError:
        raise PermissionError(f"renamed path disappeared: {target}") from None
    if not os.path.samestat(source_metadata, published_metadata):
        raise PermissionError(
            f"rename destination does not contain the source identity: {target}"
        )
    return target


@contextmanager
def open_binary_read_without_links(
    path: str | os.PathLike[str],
    *,
    expected_identity: os.stat_result | None = None,
    expected_parent_identity: os.stat_result | None = None,
) -> Iterator[BinaryIO]:
    """Open one exact regular file without following path aliases.

    Validation is repeated after opening and the opened descriptor is compared
    with the current leaf metadata.  This keeps callers from validating one
    project file and then reading a replacement symlink, junction, or different
    file through the same spelling.
    """

    source = _exact_path(path, field="source file")
    parent, parent_identity = _directory_identity(
        source.parent,
        field="source file parent",
    )
    if source.parent != parent:
        raise PermissionError("source file parent changed identity")
    if (
        expected_parent_identity is not None
        and not os.path.samestat(expected_parent_identity, parent_identity)
    ):
        raise PermissionError(f"source file parent identity changed: {parent}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    parent_descriptor = -1
    try:
        if os.open in os.supports_dir_fd:
            directory_flags = os.O_RDONLY
            directory_flags |= getattr(os, "O_DIRECTORY", 0)
            directory_flags |= getattr(os, "O_NOFOLLOW", 0)
            directory_flags |= getattr(os, "O_CLOEXEC", 0)
            parent_descriptor = os.open(parent, directory_flags)
            if not os.path.samestat(
                parent_identity,
                os.fstat(parent_descriptor),
            ):
                raise PermissionError(
                    f"source file parent identity changed: {parent}"
                )
            descriptor = os.open(
                source.name,
                flags,
                dir_fd=parent_descriptor,
            )
        else:
            _require_directory_identity(
                parent,
                parent_identity,
                field="source file parent",
            )
            descriptor = os.open(source, flags)
    except FileNotFoundError:
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
            parent_descriptor = -1
        raise FileNotFoundError(source) from None
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
            descriptor = -1
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
            parent_descriptor = -1
        raise
    try:
        opened_metadata = os.fstat(descriptor)
        source = _exact_path(source, field="source file")
        current_metadata = source.lstat()
        if (
            not stat.S_ISREG(opened_metadata.st_mode)
            or _metadata_is_link_or_reparse_point(current_metadata)
            or not os.path.samestat(opened_metadata, current_metadata)
            or (
                expected_identity is not None
                and not file_snapshot_is_stable(
                    expected_identity,
                    opened_metadata,
                )
            )
        ):
            raise PermissionError(f"source file identity changed: {source}")
        _require_directory_identity(
            parent,
            parent_identity,
            field="source file parent",
        )
        handle = os.fdopen(descriptor, "rb")
        descriptor = -1
        with handle:
            yield handle
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def read_text_without_links(
    path: str | os.PathLike[str],
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
    expected_identity: os.stat_result | None = None,
    expected_parent_identity: os.stat_result | None = None,
) -> str:
    """Read one stable text-file snapshot through the link-free contract."""

    payload, _metadata = read_bytes_snapshot_without_links(
        path,
        expected_identity=expected_identity,
        expected_parent_identity=expected_parent_identity,
    )
    return payload.decode(encoding, errors=errors)


def read_bytes_without_links(
    path: str | os.PathLike[str],
    *,
    expected_identity: os.stat_result | None = None,
    expected_parent_identity: os.stat_result | None = None,
) -> bytes:
    """Read one stable byte snapshot through the exact link-free contract."""

    payload, _metadata = read_bytes_snapshot_without_links(
        path,
        expected_identity=expected_identity,
        expected_parent_identity=expected_parent_identity,
    )
    return payload


def file_snapshot_is_stable(
    before: os.stat_result,
    after: os.stat_result,
) -> bool:
    """Return whether a descriptor still exposes the same immutable snapshot."""

    return (
        os.path.samestat(before, after)
        and before.st_mode == after.st_mode
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and before.st_ctime_ns == after.st_ctime_ns
    )


def read_bytes_snapshot_without_links(
    path: str | os.PathLike[str],
    *,
    expected_identity: os.stat_result | None = None,
    expected_parent_identity: os.stat_result | None = None,
) -> tuple[bytes, os.stat_result]:
    """Read bytes and metadata from one stable, identity-bound file snapshot.

    Holding a descriptor prevents a pathname replacement from retargeting the
    read, but it does not prevent another writer from mutating the same inode
    in place.  Configuration, template, manifest, and metadata readers need
    both guarantees, so reject a snapshot whose size or write/change time
    moves while it is being consumed.
    """

    source_path = _exact_path(path, field="source file")
    with open_binary_read_without_links(
        source_path,
        expected_identity=expected_identity,
        expected_parent_identity=expected_parent_identity,
    ) as source:
        before = os.fstat(source.fileno())
        payload = source.read()
        after = os.fstat(source.fileno())
    if not file_snapshot_is_stable(before, after):
        raise PermissionError(
            f"source file changed while it was being read: {source_path}"
        )
    return payload, before


def read_text_snapshot_without_links(
    path: str | os.PathLike[str],
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
    expected_identity: os.stat_result | None = None,
    expected_parent_identity: os.stat_result | None = None,
) -> tuple[str, os.stat_result]:
    """Read text and metadata from one stable, identity-bound file snapshot."""

    payload, metadata = read_bytes_snapshot_without_links(
        path,
        expected_identity=expected_identity,
        expected_parent_identity=expected_parent_identity,
    )
    return payload.decode(encoding, errors=errors), metadata


def ensure_portable_name_available(
    directory: Path,
    requested_name: str,
    *,
    expected_directory_identity: os.stat_result | None = None,
) -> None:
    """Reject a different existing spelling that aliases on common filesystems."""

    parent = _exact_path(directory, field="managed directory")
    try:
        parent, parent_identity, entries = (
            snapshot_directory_entries_without_links(
                parent,
                field="managed directory",
            )
        )
    except NotADirectoryError:
        if not parent.exists():
            return
        raise
    if (
        expected_directory_identity is not None
        and not os.path.samestat(
            expected_directory_identity,
            parent_identity,
        )
    ):
        raise PermissionError(f"managed directory identity changed: {parent}")
    requested_key = portable_name_key(requested_name)
    for child, _metadata in entries:
        if portable_name_key(child.name) == requested_key and child.name != requested_name:
            raise FileExistsError(
                f"portable filename collision: {requested_name!r} conflicts with {child.name!r}"
            )
    _require_directory_identity(
        parent,
        parent_identity,
        field="managed directory",
    )


def _existing_regular_file_identity(target: Path) -> os.stat_result | None:
    """Capture one destination identity, distinguishing absence from replacement."""

    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return None
    if _metadata_is_link_or_reparse_point(metadata):
        raise PermissionError(f"refusing to replace symbolic link: {target}")
    if not stat.S_ISREG(metadata.st_mode):
        raise IsADirectoryError(target)
    return metadata


def _directory_identity(
    path: str | os.PathLike[str],
    *,
    field: str,
    allow_filesystem_root: bool = False,
) -> tuple[Path, os.stat_result]:
    directory = _exact_path(
        path,
        field=field,
        allow_filesystem_root=allow_filesystem_root,
    )
    try:
        metadata = directory.lstat()
    except FileNotFoundError:
        raise NotADirectoryError(directory) from None
    if (
        _metadata_is_link_or_reparse_point(metadata)
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise NotADirectoryError(directory)
    return directory, metadata


def _require_directory_identity(
    path: str | os.PathLike[str],
    expected_identity: os.stat_result,
    *,
    field: str,
    allow_filesystem_root: bool = False,
) -> Path:
    directory, current_identity = _directory_identity(
        path,
        field=field,
        allow_filesystem_root=allow_filesystem_root,
    )
    if not os.path.samestat(expected_identity, current_identity):
        raise PermissionError(f"{field} identity changed: {directory}")
    return directory


def capture_directory_identity(
    path: str | os.PathLike[str],
    *,
    field: str = "directory",
) -> tuple[Path, os.stat_result]:
    """Return one link-free directory together with its filesystem identity.

    Path-only APIs used by external tools cannot retain a directory descriptor.
    Their callers can capture the directory once, perform the long operation,
    then pass the identity into the publication primitive and revalidate it
    before accepting any output.
    """

    return _directory_identity(path, field=field)


def snapshot_directory_entries_without_links(
    path: str | os.PathLike[str],
    *,
    field: str = "directory",
    allow_filesystem_root: bool = False,
) -> tuple[Path, os.stat_result, list[tuple[Path, os.stat_result]]]:
    """Return one directory's entries from a single identity-checked scan.

    Entry metadata is collected without following links.  The public
    directory name is checked before and after ``scandir`` so callers never
    combine names from an old directory with files reached through a
    replacement directory bearing the same pathname.
    """

    directory, directory_identity = _directory_identity(
        path,
        field=field,
        allow_filesystem_root=allow_filesystem_root,
    )
    descriptor = -1
    try:
        if (
            os.scandir in os.supports_fd
            and os.stat in os.supports_dir_fd
        ):
            directory_flags = os.O_RDONLY
            directory_flags |= getattr(os, "O_DIRECTORY", 0)
            directory_flags |= getattr(os, "O_NOFOLLOW", 0)
            directory_flags |= getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(directory, directory_flags)
            opened_identity = os.fstat(descriptor)
            if not os.path.samestat(
                directory_identity,
                opened_identity,
            ):
                raise PermissionError(
                    f"{field} identity changed: {directory}"
                )
            try:
                with os.scandir(descriptor) as scanner:
                    entries = [
                        (
                            directory / entry.name,
                            os.stat(
                                entry.name,
                                dir_fd=descriptor,
                                follow_symlinks=False,
                            ),
                        )
                        for entry in scanner
                    ]
            except FileNotFoundError as exc:
                raise PermissionError(
                    f"{field} identity changed or contents changed during scan: "
                    f"{directory}"
                ) from exc
            final_opened_identity = os.fstat(descriptor)
            if not file_snapshot_is_stable(
                opened_identity,
                final_opened_identity,
            ):
                raise PermissionError(
                    f"{field} identity changed or contents changed during scan: "
                    f"{directory}"
                )
        else:
            try:
                with os.scandir(directory) as scanner:
                    entries = [
                        (
                            directory / entry.name,
                            entry.stat(follow_symlinks=False),
                        )
                        for entry in scanner
                    ]
            except FileNotFoundError as exc:
                raise PermissionError(
                    f"{field} identity changed or contents changed during scan: "
                    f"{directory}"
                ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    _directory, final_identity = _directory_identity(
        directory,
        field=field,
        allow_filesystem_root=allow_filesystem_root,
    )
    if not file_snapshot_is_stable(
        directory_identity,
        final_identity,
    ):
        raise PermissionError(f"{field} identity changed: {directory}")
    return directory, directory_identity, entries


def require_directory_identity(
    path: str | os.PathLike[str],
    expected_identity: os.stat_result,
    *,
    field: str = "directory",
    allow_filesystem_root: bool = False,
) -> Path:
    """Require that a public path still names the captured directory."""

    return _require_directory_identity(
        path,
        expected_identity,
        field=field,
        allow_filesystem_root=allow_filesystem_root,
    )


def atomic_write_text(
    path: str | os.PathLike[str],
    text: str,
    *,
    encoding: str = "utf-8",
    expected_parent_identity: os.stat_result | None = None,
) -> None:
    """Publish a complete text file while preserving the previous file on failure."""

    target = _exact_path(path, field="atomic write target")
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _exact_path(target, field="atomic write target")
    parent, parent_identity = _directory_identity(
        target.parent,
        field="atomic write parent",
    )
    if (
        expected_parent_identity is not None
        and not os.path.samestat(expected_parent_identity, parent_identity)
    ):
        raise PermissionError(f"atomic write parent identity changed: {parent}")
    target_identity = _existing_regular_file_identity(target)

    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding=encoding,
        dir=parent,
        prefix=portable_path_component_prefix(
            f".{target.name}.",
            reserved_suffix_bytes=_TEMPFILE_RANDOM_TOKEN_RESERVE + len(".tmp"),
            field="atomic write temporary prefix",
        ),
        suffix=".tmp",
        delete=False,
    )
    staging = Path(handle.name)
    staging_identity = os.fstat(handle.fileno())
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        target = _exact_path(target, field="atomic write target")
        _require_directory_identity(
            parent,
            parent_identity,
            field="atomic write parent",
        )
        if path_is_link_or_reparse_point(target):
            raise PermissionError(f"refusing to replace symbolic link: {target}")
        replace_file_transactionally(
            staging,
            target,
            expected_staging_identity=staging_identity,
            expected_destination_identity=target_identity,
            expected_parent_identity=parent_identity,
        )
        _require_directory_identity(
            parent,
            parent_identity,
            field="atomic write parent",
        )
    finally:
        remove_file_without_links(
            staging,
            missing_ok=True,
            expected_identity=staging_identity,
        )


@contextmanager
def atomic_binary_writer(
    path: str | os.PathLike[str],
    *,
    expected_parent_identity: os.stat_result | None = None,
) -> Iterator[BinaryIO]:
    """Yield a private binary staging file and atomically publish it on success."""

    target = _exact_path(path, field="atomic write target")
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _exact_path(target, field="atomic write target")
    parent, parent_identity = _directory_identity(
        target.parent,
        field="atomic write parent",
    )
    if (
        expected_parent_identity is not None
        and not os.path.samestat(expected_parent_identity, parent_identity)
    ):
        raise PermissionError(f"atomic write parent identity changed: {parent}")
    target_identity = _existing_regular_file_identity(target)

    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=parent,
        prefix=portable_path_component_prefix(
            f".{target.name}.",
            reserved_suffix_bytes=_TEMPFILE_RANDOM_TOKEN_RESERVE + len(".tmp"),
            field="atomic write temporary prefix",
        ),
        suffix=".tmp",
        delete=False,
    )
    staging = Path(handle.name)
    staging_identity = os.fstat(handle.fileno())
    try:
        with handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        target = _exact_path(target, field="atomic write target")
        _require_directory_identity(
            parent,
            parent_identity,
            field="atomic write parent",
        )
        if path_is_link_or_reparse_point(target):
            raise PermissionError(f"refusing to replace symbolic link: {target}")
        replace_file_transactionally(
            staging,
            target,
            expected_staging_identity=staging_identity,
            expected_destination_identity=target_identity,
            expected_parent_identity=parent_identity,
        )
        _require_directory_identity(
            parent,
            parent_identity,
            field="atomic write parent",
        )
    finally:
        remove_file_without_links(
            staging,
            missing_ok=True,
            expected_identity=staging_identity,
        )


def atomic_write_bytes(path: str | os.PathLike[str], content: bytes) -> None:
    """Publish a complete binary file while preserving the prior file on failure."""

    with atomic_binary_writer(path) as handle:
        handle.write(content)


@_serialized_path_mutation
def replace_file_transactionally(
    staging: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    expected_staging_identity: os.stat_result | None = None,
    expected_destination_identity: os.stat_result | None | object = (
        _UNSPECIFIED_IDENTITY
    ),
    expected_parent_identity: os.stat_result | None = None,
) -> Path:
    """Atomically publish one complete sibling file.

    External encoders and archive writers often require a filesystem path
    instead of an already-open handle.  They can write to a private sibling
    and hand it here only after validation; the old destination remains intact
    until publication.  Both paths are pinned by filesystem identity, and the
    destination is moved aside with no-replace semantics before the staging
    identity is published.  A peer-created destination is therefore preserved
    instead of being silently overwritten by POSIX ``replace`` semantics.
    """

    staging_path = _exact_path(staging, field="staging file")
    target = _exact_path(destination, field="destination file")
    if staging_path == target:
        raise ValueError("staging and destination files must differ")
    if staging_path.parent != target.parent:
        raise ValueError("staging and destination files must share a parent")
    parent, parent_identity = _directory_identity(
        staging_path.parent,
        field="file publication parent",
    )
    if (
        expected_parent_identity is not None
        and not os.path.samestat(expected_parent_identity, parent_identity)
    ):
        raise PermissionError(f"file publication parent identity changed: {parent}")
    if path_is_link_or_reparse_point(staging_path):
        raise PermissionError(f"staging file must not be a symbolic link: {staging_path}")
    try:
        staging_metadata = staging_path.lstat()
    except FileNotFoundError:
        raise FileNotFoundError(staging_path) from None
    if not stat.S_ISREG(staging_metadata.st_mode):
        raise PermissionError(f"staging file must be a regular file: {staging_path}")
    if (
        expected_staging_identity is not None
        and not os.path.samestat(expected_staging_identity, staging_metadata)
    ):
        raise PermissionError(f"staging file identity changed: {staging_path}")

    target_metadata = _existing_regular_file_identity(target)
    if expected_destination_identity is not _UNSPECIFIED_IDENTITY:
        if expected_destination_identity is None:
            if target_metadata is not None:
                raise FileExistsError(
                    f"destination file appeared before publication: {target}"
                )
        elif (
            target_metadata is None
            or not os.path.samestat(expected_destination_identity, target_metadata)
        ):
            raise PermissionError(f"destination file identity changed: {target}")
    ensure_portable_name_available(target.parent, target.name)

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(staging_path, flags)
    try:
        opened_metadata = os.fstat(descriptor)
        current_metadata = staging_path.lstat()
        if (
            not stat.S_ISREG(opened_metadata.st_mode)
            or path_is_link_or_reparse_point(staging_path)
            or not os.path.samestat(opened_metadata, current_metadata)
        ):
            raise PermissionError(f"staging file identity changed: {staging_path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

    staging_path = _exact_path(staging_path, field="staging file")
    target = _exact_path(target, field="destination file")
    _require_directory_identity(
        parent,
        parent_identity,
        field="file publication parent",
    )
    if staging_path.parent != target.parent:
        raise ValueError("publication paths changed parent")
    if path_is_link_or_reparse_point(staging_path) or not staging_path.is_file():
        raise PermissionError(f"staging file changed before publication: {staging_path}")
    current_staging_metadata = staging_path.lstat()
    if not os.path.samestat(opened_metadata, current_staging_metadata):
        raise PermissionError(f"staging file identity changed: {staging_path}")

    current_target_metadata = _existing_regular_file_identity(target)
    if target_metadata is None:
        if current_target_metadata is not None:
            raise FileExistsError(
                f"destination file appeared during publication: {target}"
            )
    elif (
        current_target_metadata is None
        or not os.path.samestat(target_metadata, current_target_metadata)
    ):
        raise PermissionError(f"destination file identity changed: {target}")

    backup: Path | None = None
    if target_metadata is not None:
        raw_backup = private_sibling_path(
            target,
            f".backup-{uuid.uuid4().hex}",
            field="file publication backup",
        )
        rename_path_without_overwrite(
            target,
            raw_backup,
            expected_identity=target_metadata,
        )
        _require_directory_identity(
            parent,
            parent_identity,
            field="file publication parent",
        )
        try:
            backup = _exact_path(raw_backup, field="file publication backup")
            backup_metadata = backup.lstat()
            if (
                _metadata_is_link_or_reparse_point(backup_metadata)
                or not stat.S_ISREG(backup_metadata.st_mode)
                or not os.path.samestat(target_metadata, backup_metadata)
            ):
                raise PermissionError(
                    f"destination file identity changed: {target}"
                )
        except BaseException:
            if not os.path.lexists(target) and os.path.lexists(raw_backup):
                try:
                    rename_path_without_overwrite(
                        raw_backup,
                        target,
                        expected_identity=target_metadata,
                    )
                except OSError:
                    pass
            raise

    try:
        _require_directory_identity(
            parent,
            parent_identity,
            field="file publication parent",
        )
        rename_path_without_overwrite(
            staging_path,
            target,
            expected_identity=staging_metadata,
        )
        _require_directory_identity(
            parent,
            parent_identity,
            field="file publication parent",
        )
        published_metadata = target.lstat()
        if not os.path.samestat(staging_metadata, published_metadata):
            raise PermissionError(
                f"staging file identity changed during publication: {staging_path}"
            )
    except BaseException:
        if backup is not None and not os.path.lexists(target):
            rename_path_without_overwrite(
                backup,
                target,
                expected_identity=target_metadata,
            )
            backup = None
        raise

    if backup is not None:
        remove_file_without_links(
            backup,
            expected_identity=target_metadata,
        )
    _require_directory_identity(
        parent,
        parent_identity,
        field="file publication parent",
    )
    return target


def copy_file_transactionally(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    expected_source_identity: os.stat_result | None = None,
    expected_source_parent_identity: os.stat_result | None = None,
    expected_destination_parent_identity: os.stat_result | None = None,
) -> Path:
    """Copy one regular file and atomically publish the complete result.

    The source is held through one validated descriptor, while the destination
    is written to a private sibling first.  This prevents application updates
    and other overwrite flows from exposing a partially copied file or
    following a path component that was replaced by a link.
    """

    source_path = _exact_path(source, field="source file")
    target = _exact_path(destination, field="destination file")
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _exact_path(target, field="destination file")
    parent, parent_identity = _directory_identity(
        target.parent,
        field="copy destination parent",
    )
    if (
        expected_destination_parent_identity is not None
        and not os.path.samestat(
            expected_destination_parent_identity,
            parent_identity,
        )
    ):
        raise PermissionError(
            f"copy destination parent identity changed: {parent}"
        )
    target_identity = _existing_regular_file_identity(target)

    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=parent,
        prefix=portable_path_component_prefix(
            f".{target.name}.",
            reserved_suffix_bytes=_TEMPFILE_RANDOM_TOKEN_RESERVE + len(".copy"),
            field="copy temporary prefix",
        ),
        suffix=".copy",
        delete=False,
    )
    staging = Path(handle.name)
    staging_identity = os.fstat(handle.fileno())
    try:
        with open_binary_read_without_links(
            source_path,
            expected_identity=expected_source_identity,
            expected_parent_identity=expected_source_parent_identity,
        ) as input_file:
            source_metadata = os.fstat(input_file.fileno())
            with handle:
                shutil.copyfileobj(input_file, handle)
                if hasattr(os, "fchmod"):
                    os.fchmod(
                        handle.fileno(),
                        stat.S_IMODE(source_metadata.st_mode),
                    )
                if os.utime in os.supports_fd:
                    try:
                        os.utime(
                            handle.fileno(),
                            ns=(
                                source_metadata.st_atime_ns,
                                source_metadata.st_mtime_ns,
                            ),
                        )
                    except (NotImplementedError, OSError):
                        pass
                handle.flush()
                os.fsync(handle.fileno())
            final_source_metadata = os.fstat(input_file.fileno())
            if not file_snapshot_is_stable(
                source_metadata,
                final_source_metadata,
            ):
                raise PermissionError(
                    f"source file changed while it was being copied: {source_path}"
                )
        return replace_file_transactionally(
            staging,
            target,
            expected_staging_identity=staging_identity,
            expected_destination_identity=target_identity,
            expected_parent_identity=parent_identity,
        )
    finally:
        if not handle.closed:
            handle.close()
        remove_file_without_links(
            staging,
            missing_ok=True,
            expected_identity=staging_identity,
            expected_parent_identity=parent_identity,
        )


def remove_file_without_links(
    path: str | os.PathLike[str],
    *,
    missing_ok: bool = False,
    expected_identity: os.stat_result | None = None,
    expected_parent_identity: os.stat_result | None = None,
) -> None:
    """Remove one exact regular file without deleting a replacement identity.

    The file is opened without following its leaf, compared with the current
    path, then renamed to a private sibling.  The renamed object must still be
    the same file before it is unlinked.  If another process replaced the path
    during the operation, that replacement is restored or preserved instead of
    being silently deleted.
    """

    target = _exact_path(path, field="file removal target")
    parent, parent_identity = _directory_identity(
        target.parent,
        field="file removal parent",
    )
    if target.parent != parent:
        raise PermissionError("file removal parent changed identity")
    if (
        expected_parent_identity is not None
        and not os.path.samestat(expected_parent_identity, parent_identity)
    ):
        raise PermissionError(f"file removal parent identity changed: {parent}")

    with _DIRECTORY_PUBLICATION_LOCK:
        _require_directory_identity(
            parent,
            parent_identity,
            field="file removal parent",
        )
        if (
            expected_parent_identity is not None
            and not os.path.samestat(expected_parent_identity, parent_identity)
        ):
            raise PermissionError(f"file removal parent identity changed: {parent}")
        target = _exact_path(target, field="file removal target")
        try:
            current_metadata = target.lstat()
        except FileNotFoundError:
            if missing_ok:
                return
            raise FileNotFoundError(target) from None
        if (
            _metadata_is_link_or_reparse_point(current_metadata)
            or not stat.S_ISREG(current_metadata.st_mode)
        ):
            raise PermissionError(
                f"file removal target must be a regular non-link file: {target}"
            )
        if (
            expected_identity is not None
            and not os.path.samestat(expected_identity, current_metadata)
        ):
            raise PermissionError(f"file removal target identity changed: {target}")

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags)
        try:
            opened_metadata = os.fstat(descriptor)
            current_metadata = target.lstat()
            if (
                not stat.S_ISREG(opened_metadata.st_mode)
                or _metadata_is_link_or_reparse_point(current_metadata)
                or not os.path.samestat(opened_metadata, current_metadata)
                or (
                    expected_identity is not None
                    and not os.path.samestat(expected_identity, opened_metadata)
                )
            ):
                raise PermissionError(f"file removal target identity changed: {target}")
        finally:
            os.close(descriptor)

        trash = private_sibling_path(
            target,
            f".delete-{uuid.uuid4().hex}",
            field="file removal staging path",
        )
        trash = _exact_path(trash, field="file removal staging path")
        if os.path.lexists(trash):
            raise FileExistsError(trash)

        rename_path_without_overwrite(
            target,
            trash,
            expected_identity=opened_metadata,
        )
        try:
            exact_trash = _exact_path(trash, field="file removal staging path")
            trash_metadata = exact_trash.lstat()
            if (
                _metadata_is_link_or_reparse_point(trash_metadata)
                or not stat.S_ISREG(trash_metadata.st_mode)
                or not os.path.samestat(opened_metadata, trash_metadata)
            ):
                raise PermissionError(
                    f"file removal target changed before deletion: {target}"
                )
            exact_trash.unlink()
        except BaseException:
            if os.path.lexists(trash) and not os.path.lexists(target):
                try:
                    rename_path_without_overwrite(
                        trash,
                        target,
                        expected_identity=opened_metadata,
                    )
                except OSError:
                    pass
            raise


def remove_link_without_following(
    path: str | os.PathLike[str],
    *,
    expected_identity: os.stat_result | None = None,
) -> None:
    """Remove one exact symlink/junction without following or deleting a replacement."""

    target = require_symlink_free_absolute_path(
        path,
        field="link removal target",
        include_leaf=False,
    )
    parent = _exact_path(target.parent, field="link removal parent")
    if target.parent != parent:
        raise PermissionError("link removal parent changed identity")

    with _DIRECTORY_PUBLICATION_LOCK:
        target = require_symlink_free_absolute_path(
            target,
            field="link removal target",
            include_leaf=False,
        )
        try:
            target_metadata = target.lstat()
        except FileNotFoundError:
            raise FileNotFoundError(target) from None
        if not _metadata_is_link_or_reparse_point(target_metadata):
            raise PermissionError(f"link removal target is not a link: {target}")
        if (
            expected_identity is not None
            and not os.path.samestat(expected_identity, target_metadata)
        ):
            raise PermissionError(f"link removal target identity changed: {target}")

        trash = private_sibling_path(
            target,
            f".delete-{uuid.uuid4().hex}",
            field="link removal staging path",
        )
        trash = require_symlink_free_absolute_path(
            trash,
            field="link removal staging path",
            include_leaf=False,
        )
        if os.path.lexists(trash):
            raise FileExistsError(trash)

        rename_path_without_overwrite(
            target,
            trash,
            expected_identity=target_metadata,
        )
        try:
            trash = require_symlink_free_absolute_path(
                trash,
                field="link removal staging path",
                include_leaf=False,
            )
            trash_metadata = trash.lstat()
            if (
                not _metadata_is_link_or_reparse_point(trash_metadata)
                or not os.path.samestat(target_metadata, trash_metadata)
            ):
                raise PermissionError(
                    f"link removal target changed before deletion: {target}"
                )
            if stat.S_ISDIR(trash_metadata.st_mode):
                trash.rmdir()
            else:
                trash.unlink()
        except BaseException:
            if os.path.lexists(trash) and not os.path.lexists(target):
                try:
                    rename_path_without_overwrite(
                        trash,
                        target,
                        expected_identity=target_metadata,
                    )
                except OSError:
                    pass
            raise


def remove_empty_directory_without_links(
    path: str | os.PathLike[str],
    *,
    expected_identity: os.stat_result | None = None,
) -> None:
    """Remove one exact empty directory without deleting a replacement identity."""

    target = _exact_path(path, field="empty directory removal target")
    parent = _exact_path(target.parent, field="empty directory removal parent")
    if target.parent != parent:
        raise PermissionError("empty directory removal parent changed identity")

    with _DIRECTORY_PUBLICATION_LOCK:
        target = _exact_path(target, field="empty directory removal target")
        try:
            target_metadata = target.lstat()
        except FileNotFoundError:
            raise FileNotFoundError(target) from None
        if (
            _metadata_is_link_or_reparse_point(target_metadata)
            or not stat.S_ISDIR(target_metadata.st_mode)
        ):
            raise NotADirectoryError(target)
        if (
            expected_identity is not None
            and not os.path.samestat(expected_identity, target_metadata)
        ):
            raise PermissionError(
                f"empty directory removal target identity changed: {target}"
            )

        trash = private_sibling_path(
            target,
            f".delete-{uuid.uuid4().hex}",
            field="empty directory removal staging path",
        )
        trash = _exact_path(trash, field="empty directory removal staging path")
        if os.path.lexists(trash):
            raise FileExistsError(trash)

        rename_path_without_overwrite(
            target,
            trash,
            expected_identity=target_metadata,
        )
        try:
            trash = _exact_path(trash, field="empty directory removal staging path")
            trash_metadata = trash.lstat()
            if (
                _metadata_is_link_or_reparse_point(trash_metadata)
                or not stat.S_ISDIR(trash_metadata.st_mode)
                or not os.path.samestat(target_metadata, trash_metadata)
            ):
                raise PermissionError(
                    f"empty directory removal target changed before deletion: {target}"
                )
            trash.rmdir()
        except BaseException:
            if os.path.lexists(trash) and not os.path.lexists(target):
                try:
                    rename_path_without_overwrite(
                        trash,
                        target,
                        expected_identity=target_metadata,
                    )
                except OSError:
                    pass
            raise


def open_text_append_without_links(
    path: str | os.PathLike[str],
    *,
    encoding: str = "utf-8",
    buffering: int = 1,
    expected_parent_identity: os.stat_result | None = None,
) -> TextIO:
    """Open an append target relative to one identity-bound parent directory.

    Validating a link-free pathname and then calling ``open(path)`` still
    leaves a parent-replacement window.  Prefer descriptor-relative creation
    where the host supports it, compare the opened leaf with the public name,
    and recheck the parent before returning a writable handle.
    """

    target = _exact_path(path, field="append target")
    if expected_parent_identity is None:
        target.parent.mkdir(parents=True, exist_ok=True)
    parent, parent_identity = _directory_identity(
        target.parent,
        field="append target parent",
    )
    if target.parent != parent:
        raise PermissionError("append target parent changed identity")
    if (
        expected_parent_identity is not None
        and not os.path.samestat(expected_parent_identity, parent_identity)
    ):
        raise PermissionError(f"append target parent identity changed: {parent}")

    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    parent_descriptor = -1
    created = False
    try:
        if os.open in os.supports_dir_fd:
            directory_flags = os.O_RDONLY
            directory_flags |= getattr(os, "O_DIRECTORY", 0)
            directory_flags |= getattr(os, "O_NOFOLLOW", 0)
            directory_flags |= getattr(os, "O_CLOEXEC", 0)
            parent_descriptor = os.open(parent, directory_flags)
            if not os.path.samestat(
                parent_identity,
                os.fstat(parent_descriptor),
            ):
                raise PermissionError(
                    f"append target parent identity changed: {parent}"
                )
            try:
                os.stat(
                    target.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                created = True
            descriptor = os.open(
                target.name,
                flags,
                0o600,
                dir_fd=parent_descriptor,
            )
        else:
            _require_directory_identity(
                parent,
                parent_identity,
                field="append target parent",
            )
            created = not os.path.lexists(target)
            descriptor = os.open(target, flags, 0o600)

        opened_metadata = os.fstat(descriptor)
        target = _exact_path(target, field="append target")
        current_metadata = target.lstat()
        if (
            not stat.S_ISREG(opened_metadata.st_mode)
            or _metadata_is_link_or_reparse_point(current_metadata)
            or not os.path.samestat(opened_metadata, current_metadata)
        ):
            raise PermissionError(f"append target must be a regular non-link file: {target}")
        _require_directory_identity(
            parent,
            parent_identity,
            field="append target parent",
        )
        handle = os.fdopen(
            descriptor,
            "a",
            encoding=encoding,
            buffering=buffering,
        )
        descriptor = -1
        return handle
    except BaseException:
        if created and descriptor >= 0:
            try:
                opened_identity = os.fstat(descriptor)
                if parent_descriptor >= 0:
                    current_identity = os.stat(
                        target.name,
                        dir_fd=parent_descriptor,
                        follow_symlinks=False,
                    )
                    if os.path.samestat(opened_identity, current_identity):
                        os.unlink(target.name, dir_fd=parent_descriptor)
                else:
                    current_identity = target.lstat()
                    if os.path.samestat(opened_identity, current_identity):
                        target.unlink()
            except OSError:
                pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def open_binary_write_exclusive_without_links(
    path: str | os.PathLike[str],
    *,
    expected_parent_identity: os.stat_result | None = None,
) -> BinaryIO:
    """Create one exact regular file exclusively and verify its opened identity.

    On hosts with descriptor-relative filesystem calls, creation is bound to
    the already-validated parent directory.  This prevents a same-named
    replacement directory from receiving the new file between validation and
    ``open``.  The optional expected identity extends that binding across a
    caller's longer transaction.
    """

    target = _exact_path(path, field="exclusive write target")
    parent, parent_identity = _directory_identity(
        target.parent,
        field="exclusive write parent",
    )
    if target.parent != parent:
        raise PermissionError("exclusive write parent changed identity")
    if (
        expected_parent_identity is not None
        and not os.path.samestat(expected_parent_identity, parent_identity)
    ):
        raise PermissionError(f"exclusive write parent identity changed: {parent}")

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    parent_descriptor = -1
    try:
        if os.open in os.supports_dir_fd:
            directory_flags = os.O_RDONLY
            directory_flags |= getattr(os, "O_DIRECTORY", 0)
            directory_flags |= getattr(os, "O_NOFOLLOW", 0)
            directory_flags |= getattr(os, "O_CLOEXEC", 0)
            parent_descriptor = os.open(parent, directory_flags)
            if not os.path.samestat(
                parent_identity,
                os.fstat(parent_descriptor),
            ):
                raise PermissionError(
                    f"exclusive write parent identity changed: {parent}"
                )
            descriptor = os.open(
                target.name,
                flags,
                0o600,
                dir_fd=parent_descriptor,
            )
        else:
            _require_directory_identity(
                parent,
                parent_identity,
                field="exclusive write parent",
            )
            descriptor = os.open(target, flags, 0o600)

        opened_metadata = os.fstat(descriptor)
        target = _exact_path(target, field="exclusive write target")
        current_metadata = target.lstat()
        if (
            not stat.S_ISREG(opened_metadata.st_mode)
            or _metadata_is_link_or_reparse_point(current_metadata)
            or not os.path.samestat(opened_metadata, current_metadata)
        ):
            raise PermissionError(
                f"exclusive write target identity changed: {target}"
            )
        _require_directory_identity(
            parent,
            parent_identity,
            field="exclusive write parent",
        )
        handle = os.fdopen(descriptor, "wb")
        descriptor = -1
        return handle
    except BaseException:
        if descriptor >= 0 and parent_descriptor >= 0:
            try:
                created_identity = os.fstat(descriptor)
                current_identity = os.stat(
                    target.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                if os.path.samestat(created_identity, current_identity):
                    os.unlink(target.name, dir_fd=parent_descriptor)
            except OSError:
                pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def _open_portable_destination(
    directory: str | os.PathLike[str],
    requested_name: str,
    *,
    field: str,
) -> tuple[Path, BinaryIO, Path, os.stat_result]:
    """Reserve a unique portable filename and return its exclusive handle."""

    raw_name = safe_path_component(requested_name, field=field)
    destination_dir = _exact_path(directory, field=f"{field} directory")
    if path_is_link_or_reparse_point(destination_dir):
        raise PermissionError(f"{field} directory must not be a symbolic link")
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_dir, destination_dir_identity = _directory_identity(
        destination_dir,
        field=f"{field} directory",
    )

    source_name = Path(raw_name)
    suffix = source_name.suffix
    stem = source_name.name[: -len(suffix)] if suffix else source_name.name

    # Exclusive creation protects exact-name publication across processes.  The
    # process lock also closes the directory-listing race for case/Unicode aliases
    # on case-sensitive filesystems, where two distinct spellings could otherwise
    # both be created before either caller observes the other one.
    with _EXCLUSIVE_FILE_PUBLICATION_LOCK:
        (
            _destination_dir,
            listed_directory_identity,
            entries,
        ) = snapshot_directory_entries_without_links(
            destination_dir,
            field=f"{field} directory",
        )
        if not os.path.samestat(
            destination_dir_identity,
            listed_directory_identity,
        ):
            raise PermissionError(
                f"{field} directory identity changed: {destination_dir}"
            )
        existing_keys = {
            portable_name_key(child.name)
            for child, _metadata in entries
        }
        counter = 0
        while True:
            candidate_name = (
                raw_name
                if counter == 0
                else safe_path_component_with_suffix(
                    stem,
                    f"_{counter}{suffix}",
                    field=field,
                )
            )
            if portable_name_key(candidate_name) in existing_keys:
                counter += 1
                continue
            destination = managed_child_path(destination_dir, candidate_name, field=field)
            try:
                return (
                    destination,
                    open_binary_write_exclusive_without_links(
                        destination,
                        expected_parent_identity=destination_dir_identity,
                    ),
                    destination_dir,
                    destination_dir_identity,
                )
            except FileExistsError:
                existing_keys.add(portable_name_key(candidate_name))
                counter += 1


def write_bytes_exclusive(
    directory: str | os.PathLike[str],
    requested_name: str,
    content: bytes,
    *,
    field: str = "filename",
) -> Path:
    """Publish bytes under a unique portable filename without overwriting."""

    destination, output, destination_dir, destination_dir_identity = (
        _open_portable_destination(
            directory,
            requested_name,
            field=field,
        )
    )
    destination_identity = os.fstat(output.fileno())
    try:
        with output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        _require_directory_identity(
            destination_dir,
            destination_dir_identity,
            field=f"{field} directory",
        )
        current_identity = destination.lstat()
        if not os.path.samestat(destination_identity, current_identity):
            raise PermissionError(
                f"published file identity changed: {destination}"
            )
    except BaseException:
        remove_file_without_links(
            destination,
            missing_ok=True,
            expected_identity=destination_identity,
        )
        raise
    return destination


def copy_file_exclusive(
    source: str | os.PathLike[str],
    directory: str | os.PathLike[str],
    requested_name: str,
    *,
    field: str = "filename",
    expected_source_identity: os.stat_result | None = None,
) -> Path:
    """Copy one file and return its exclusively published path."""

    destination, _identity = copy_file_exclusive_with_identity(
        source,
        directory,
        requested_name,
        field=field,
        expected_source_identity=expected_source_identity,
    )
    return destination


def copy_file_exclusive_with_identity(
    source: str | os.PathLike[str],
    directory: str | os.PathLike[str],
    requested_name: str,
    *,
    field: str = "filename",
    expected_source_identity: os.stat_result | None = None,
) -> tuple[Path, os.stat_result]:
    """Copy one file under a unique portable name without overwriting anything.

    The destination is opened with exclusive creation.  This makes an upload
    safe even when another request creates the same name between validation and
    the copy itself.  Returning the descriptor-captured identity lets a later
    rollback remove only this exact file, never a replacement at the same name.
    """

    source_path = _exact_path(source, field="source file")
    if path_is_link_or_reparse_point(source_path):
        raise PermissionError(f"source file must not be a symbolic link: {source_path}")

    destination, output, destination_dir, destination_dir_identity = (
        _open_portable_destination(
            directory,
            requested_name,
            field=field,
        )
    )
    destination_identity = os.fstat(output.fileno())
    try:
        with output:
            with open_binary_read_without_links(
                source_path,
                expected_identity=expected_source_identity,
            ) as input_file:
                source_metadata = os.fstat(input_file.fileno())
                shutil.copyfileobj(input_file, output)
                final_source_metadata = os.fstat(input_file.fileno())
                if not file_snapshot_is_stable(
                    source_metadata,
                    final_source_metadata,
                ):
                    raise PermissionError(
                        f"source file changed while it was being copied: {source_path}"
                    )
                output.flush()
                os.fsync(output.fileno())
        _require_directory_identity(
            destination_dir,
            destination_dir_identity,
            field=f"{field} directory",
        )
        current_identity = destination.lstat()
        if not os.path.samestat(destination_identity, current_identity):
            raise PermissionError(
                f"published file identity changed: {destination}"
            )
    except BaseException:
        remove_file_without_links(
            destination,
            missing_ok=True,
            expected_identity=destination_identity,
        )
        raise
    return destination, destination_identity


def _inspect_portable_directory_tree_with_metadata(
    source_root: Path,
) -> tuple[
    os.stat_result,
    list[tuple[Path, os.stat_result]],
    list[tuple[Path, os.stat_result]],
]:
    """Return a portable tree inventory pinned to every observed identity."""

    source_root = _exact_path(source_root, field="source tree root")
    root_metadata = source_root.lstat()
    if (
        _metadata_is_link_or_reparse_point(root_metadata)
        or not stat.S_ISDIR(root_metadata.st_mode)
    ):
        raise PermissionError(
            f"source directory must be a real directory: {source_root}"
        )

    directories: list[tuple[Path, os.stat_result]] = []
    files: list[tuple[Path, os.stat_result]] = []

    def inspect(
        relative: Path,
        expected_directory_identity: os.stat_result,
    ) -> None:
        directory = _exact_path(
            source_root / relative,
            field="source tree directory",
        )
        (
            directory,
            directory_metadata,
            scanned_entries,
        ) = snapshot_directory_entries_without_links(
            directory,
            field="source tree directory",
        )
        if not os.path.samestat(
            expected_directory_identity,
            directory_metadata,
        ):
            raise PermissionError(
                f"source tree directory identity changed: {directory}"
            )
        entries = sorted(
            scanned_entries,
            key=lambda entry: (
                portable_name_key(entry[0].name),
                entry[0].name,
            ),
        )
        spellings: dict[str, str] = {}
        for entry_path, metadata in entries:
            name = safe_path_component(
                entry_path.name,
                field="directory entry name",
            )
            key = portable_name_key(name)
            previous = spellings.setdefault(key, name)
            if previous != name:
                raise FileExistsError(
                    f"portable filename collision: {name!r} conflicts with {previous!r}"
                )
            child_relative = relative / name
            if _metadata_is_link_or_reparse_point(metadata):
                raise PermissionError(
                    "source tree contains a symbolic link or reparse point: "
                    f"{entry_path}"
                )
            if stat.S_ISDIR(metadata.st_mode):
                directories.append((child_relative, metadata))
                inspect(child_relative, metadata)
            elif stat.S_ISREG(metadata.st_mode):
                files.append((child_relative, metadata))
            else:
                raise PermissionError(
                    f"source tree contains a special file: {entry_path}"
                )

    inspect(Path(), root_metadata)
    final_root_metadata = source_root.lstat()
    if not os.path.samestat(root_metadata, final_root_metadata):
        raise PermissionError(
            f"source tree root identity changed: {source_root}"
        )
    return root_metadata, directories, files


def inspect_portable_directory_tree(source_root: Path) -> tuple[list[Path], list[Path]]:
    """Return a link-free portable tree inventory relative to ``source_root``."""

    _root_metadata, directories, files = (
        _inspect_portable_directory_tree_with_metadata(source_root)
    )
    return (
        [relative for relative, _metadata in directories],
        [relative for relative, _metadata in files],
    )


def inspect_portable_directory_tree_with_metadata(
    source_root: Path,
) -> tuple[
    os.stat_result,
    list[tuple[Path, os.stat_result]],
    list[tuple[Path, os.stat_result]],
]:
    """Return a portable tree inventory with every observed identity pinned."""

    return _inspect_portable_directory_tree_with_metadata(source_root)


def _metadata_snapshot(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _tree_inventory_snapshot(
    root_metadata: os.stat_result,
    directories: list[tuple[Path, os.stat_result]],
    files: list[tuple[Path, os.stat_result]],
) -> tuple[
    tuple[int, int, int, int, int, int],
    tuple[tuple[str, tuple[int, int, int, int, int, int]], ...],
    tuple[tuple[str, tuple[int, int, int, int, int, int]], ...],
]:
    return (
        _metadata_snapshot(root_metadata),
        tuple(
            (relative.as_posix(), _metadata_snapshot(metadata))
            for relative, metadata in directories
        ),
        tuple(
            (relative.as_posix(), _metadata_snapshot(metadata))
            for relative, metadata in files
        ),
    )


def _assert_directory_chain_identities(
    root: Path,
    relative: Path,
    identities: dict[Path, os.stat_result],
    *,
    field: str,
) -> None:
    cursor = Path()
    for component in relative.parts:
        cursor /= component
        expected = identities[cursor]
        current_path = _exact_path(root / cursor, field=field)
        current = current_path.lstat()
        if (
            _metadata_is_link_or_reparse_point(current)
            or not stat.S_ISDIR(current.st_mode)
            or not os.path.samestat(expected, current)
        ):
            raise PermissionError(
                f"{field} identity changed: {current_path}"
            )


def copy_directory_without_links(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    expected_source_identity: os.stat_result | None = None,
) -> Path:
    """Copy a portable directory tree without following symbolic links.

    Exporting a project directory with ``shutil.copytree`` follows links by
    default.  A stale or malicious asset link could therefore pull unrelated
    host files into a shareable package.  Preflight the complete tree first,
    reject non-portable/colliding names and special files, then copy regular
    files using ``O_NOFOLLOW`` where the host provides it.
    """

    source_root = _exact_path(source, field="source directory")
    target_root = _exact_path(destination, field="destination directory")
    if os.path.lexists(target_root):
        raise FileExistsError(target_root)
    source_identity, directories, files = (
        _inspect_portable_directory_tree_with_metadata(source_root)
    )
    if (
        expected_source_identity is not None
        and not os.path.samestat(expected_source_identity, source_identity)
    ):
        raise PermissionError(
            f"source directory identity changed: {source_root}"
        )
    source_snapshot = _tree_inventory_snapshot(
        source_identity,
        directories,
        files,
    )
    source_directory_identities = {
        Path(): source_identity,
        **dict(directories),
    }
    target_root.parent.mkdir(parents=True, exist_ok=True)
    target_root = _exact_path(target_root, field="destination directory")
    target_root.mkdir()
    target_root = _exact_path(target_root, field="destination directory")
    target_identity = target_root.lstat()
    target_directory_identities = {Path(): target_identity}
    target_file_snapshots: dict[
        Path,
        tuple[int, int, int, int, int, int],
    ] = {}
    try:
        for relative, source_directory_identity in directories:
            _assert_directory_chain_identities(
                source_root,
                relative,
                source_directory_identities,
                field="source tree directory",
            )
            _assert_directory_chain_identities(
                target_root,
                relative.parent,
                target_directory_identities,
                field="destination tree directory",
            )
            target_directory = target_root / relative
            target_directory.mkdir()
            target_directory_identity = target_directory.lstat()
            if (
                _metadata_is_link_or_reparse_point(target_directory_identity)
                or not stat.S_ISDIR(target_directory_identity.st_mode)
            ):
                raise PermissionError(
                    f"destination tree directory changed: {target_directory}"
                )
            target_directory_identities[relative] = target_directory_identity
            current_source_identity = (source_root / relative).lstat()
            if not os.path.samestat(
                source_directory_identity,
                current_source_identity,
            ):
                raise PermissionError(
                    f"source tree directory identity changed: {source_root / relative}"
                )
        for relative, source_file_identity in files:
            _assert_directory_chain_identities(
                source_root,
                relative.parent,
                source_directory_identities,
                field="source tree directory",
            )
            _assert_directory_chain_identities(
                target_root,
                relative.parent,
                target_directory_identities,
                field="destination tree directory",
            )
            source_file = _exact_path(
                source_root / relative,
                field="source tree file",
            )
            with open_binary_read_without_links(source_file) as input_file:
                opened_source_identity = os.fstat(input_file.fileno())
                if not os.path.samestat(
                    source_file_identity,
                    opened_source_identity,
                ):
                    raise PermissionError(
                        f"source tree file identity changed: {source_file}"
                    )
                with open_binary_write_exclusive_without_links(
                    target_root / relative
                ) as output_file:
                    opened_target_identity = os.fstat(output_file.fileno())
                    shutil.copyfileobj(input_file, output_file)
                copied_target = target_root / relative
                copied_target_identity = copied_target.lstat()
                if not os.path.samestat(
                    opened_target_identity,
                    copied_target_identity,
                ):
                    raise PermissionError(
                        f"destination tree file identity changed: {copied_target}"
                    )
                target_file_snapshots[relative] = _metadata_snapshot(
                    copied_target_identity
                )
                final_source_metadata = os.fstat(input_file.fileno())
                if _metadata_snapshot(
                    source_file_identity
                ) != _metadata_snapshot(final_source_metadata):
                    raise PermissionError(
                        f"source tree file changed while copying: {source_file}"
                    )

        final_source_inventory = _inspect_portable_directory_tree_with_metadata(
            source_root
        )
        if source_snapshot != _tree_inventory_snapshot(*final_source_inventory):
            raise PermissionError(
                f"source directory changed while copying: {source_root}"
            )
        (
            final_target_identity,
            final_target_directories,
            final_target_files,
        ) = _inspect_portable_directory_tree_with_metadata(target_root)
        if not os.path.samestat(target_identity, final_target_identity):
            raise PermissionError(
                f"destination directory identity changed: {target_root}"
            )
        if {
            relative for relative, _metadata in final_target_directories
        } != set(target_directory_identities).difference({Path()}):
            raise PermissionError(
                f"destination directory tree changed while copying: {target_root}"
            )
        for relative, metadata in final_target_directories:
            if not os.path.samestat(
                target_directory_identities[relative],
                metadata,
            ):
                raise PermissionError(
                    f"destination tree directory identity changed: {target_root / relative}"
                )
        if {
            relative for relative, _metadata in final_target_files
        } != set(target_file_snapshots):
            raise PermissionError(
                f"destination file tree changed while copying: {target_root}"
            )
        for relative, metadata in final_target_files:
            if target_file_snapshots[relative] != _metadata_snapshot(metadata):
                raise PermissionError(
                    f"destination tree file changed while copying: {target_root / relative}"
                )
    except BaseException:
        try:
            remove_directory_without_links(
                target_root,
                expected_identity=target_identity,
            )
        except (OSError, ValueError):
            pass
        raise
    return target_root


def remove_directory_without_links(
    path: str | os.PathLike[str],
    *,
    expected_identity: os.stat_result | None = None,
) -> None:
    """Remove one exact directory without following a renamed path alias.

    Managed callers commonly validate a directory, persist related state, and
    only then delete its tree. Revalidate the complete component chain at the
    destructive boundary and first move the directory to a private sibling.
    That prevents a concurrent replacement at the original name from becoming
    the object passed to ``shutil.rmtree``.
    """

    target = _exact_path(path, field="directory removal target")
    parent = _exact_path(target.parent, field="directory removal parent")
    if target.parent != parent:
        raise PermissionError("directory removal parent changed identity")

    with _DIRECTORY_PUBLICATION_LOCK:
        target = _exact_path(target, field="directory removal target")
        try:
            target_metadata = target.lstat()
        except FileNotFoundError:
            raise NotADirectoryError(target) from None
        if (
            _metadata_is_link_or_reparse_point(target_metadata)
            or not stat.S_ISDIR(target_metadata.st_mode)
        ):
            raise NotADirectoryError(target)
        if (
            expected_identity is not None
            and not os.path.samestat(expected_identity, target_metadata)
        ):
            raise PermissionError(
                f"directory removal target identity changed: {target}"
            )
        trash = private_sibling_path(
            target,
            f".delete-{uuid.uuid4().hex}",
            field="directory removal staging path",
        )
        trash = _exact_path(trash, field="directory removal staging path")
        if os.path.lexists(trash):
            raise FileExistsError(trash)

        rename_path_without_overwrite(
            target,
            trash,
            expected_identity=target_metadata,
        )
        try:
            trash = _exact_path(trash, field="directory removal staging path")
            trash_metadata = trash.lstat()
            if (
                _metadata_is_link_or_reparse_point(trash_metadata)
                or not stat.S_ISDIR(trash_metadata.st_mode)
                or not os.path.samestat(target_metadata, trash_metadata)
            ):
                raise PermissionError(
                    f"directory removal target changed before deletion: {target}"
                )
            shutil.rmtree(trash)
        except BaseException:
            if not os.path.lexists(target) and os.path.lexists(trash):
                try:
                    restored = _exact_path(
                        trash,
                        field="directory removal rollback path",
                    )
                    if (
                        not path_is_link_or_reparse_point(restored)
                        and restored.is_dir()
                    ):
                        rename_path_without_overwrite(
                            restored,
                            target,
                            expected_identity=target_metadata,
                        )
                except (OSError, PermissionError, ValueError):
                    pass
            raise


@_serialized_path_mutation
def clear_directory_without_links(
    path: str | os.PathLike[str],
    *,
    expected_identity: os.stat_result | None = None,
) -> None:
    """Remove owned children while preserving the directory's exact identity.

    Extraction fallbacks sometimes need an empty output directory but must not
    delete and recreate the root: doing so invalidates the identity held by the
    outer cancellation/rollback path. Each child is removed through the same
    no-link, identity-checked primitives used by public destructive operations.
    """

    root = _exact_path(path, field="directory clearing target")
    root_metadata = root.lstat()
    if (
        _metadata_is_link_or_reparse_point(root_metadata)
        or not stat.S_ISDIR(root_metadata.st_mode)
    ):
        raise NotADirectoryError(root)
    if (
        expected_identity is not None
        and not os.path.samestat(expected_identity, root_metadata)
    ):
        raise PermissionError(f"directory clearing target identity changed: {root}")

    _root, listed_root_metadata, entries = (
        snapshot_directory_entries_without_links(
            root,
            field="directory clearing target",
        )
    )
    if not os.path.samestat(root_metadata, listed_root_metadata):
        raise PermissionError(
            f"directory clearing target identity changed: {root}"
        )
    for child, child_metadata in entries:
        current_root = root.lstat()
        if not os.path.samestat(root_metadata, current_root):
            raise PermissionError(f"directory clearing target identity changed: {root}")
        if _metadata_is_link_or_reparse_point(child_metadata):
            remove_link_without_following(
                child,
                expected_identity=child_metadata,
            )
        elif stat.S_ISDIR(child_metadata.st_mode):
            remove_directory_without_links(
                child,
                expected_identity=child_metadata,
            )
        elif stat.S_ISREG(child_metadata.st_mode):
            remove_file_without_links(
                child,
                expected_identity=child_metadata,
            )
        else:
            raise PermissionError(
                f"directory contains a non-regular entry that cannot be cleared: {child}"
            )

    final_metadata = root.lstat()
    if not os.path.samestat(root_metadata, final_metadata):
        raise PermissionError(f"directory clearing target identity changed: {root}")
    _root, final_snapshot_identity, remaining_entries = (
        snapshot_directory_entries_without_links(
            root,
            field="directory clearing target",
        )
    )
    if (
        not os.path.samestat(root_metadata, final_snapshot_identity)
        or remaining_entries
    ):
        raise OSError(f"directory changed while being cleared: {root}")


@_serialized_path_mutation
def replace_directory_transactionally(
    staging: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    overwrite: bool = True,
    expected_staging_identity: os.stat_result | None = None,
    expected_destination_identity: os.stat_result | None | object = (
        _UNSPECIFIED_IDENTITY
    ),
    expected_parent_identity: os.stat_result | None = None,
) -> Path:
    """Atomically publish a complete sibling directory and restore on failure.

    The caller must first materialize ``staging`` beside ``destination``.  This
    makes the final rename atomic even when the original download or extraction
    lived on another volume.
    """

    staging_root = _exact_path(staging, field="staging directory")
    target_root = _exact_path(destination, field="destination directory")
    if staging_root == target_root:
        raise ValueError("staging and destination directories must differ")
    if staging_root.parent != target_root.parent:
        raise ValueError("staging and destination directories must share a parent")
    parent, parent_identity = _directory_identity(
        staging_root.parent,
        field="directory publication parent",
    )
    if (
        expected_parent_identity is not None
        and not os.path.samestat(expected_parent_identity, parent_identity)
    ):
        raise PermissionError(
            f"directory publication parent identity changed: {parent}"
        )
    if path_is_link_or_reparse_point(staging_root) or not staging_root.is_dir():
        raise NotADirectoryError(staging_root)
    staging_identity = staging_root.lstat()
    if (
        expected_staging_identity is not None
        and not os.path.samestat(expected_staging_identity, staging_identity)
    ):
        raise PermissionError(
            f"staging directory identity changed: {staging_root}"
        )
    inspect_portable_directory_tree(staging_root)

    _require_directory_identity(
        parent,
        parent_identity,
        field="directory publication parent",
    )

    with _DIRECTORY_PUBLICATION_LOCK:
        staging_root = _exact_path(staging_root, field="staging directory")
        target_root = _exact_path(target_root, field="destination directory")
        _require_directory_identity(
            parent,
            parent_identity,
            field="directory publication parent",
        )
        if staging_root.parent != target_root.parent:
            raise ValueError("publication paths changed parent")
        if path_is_link_or_reparse_point(staging_root) or not staging_root.is_dir():
            raise NotADirectoryError(staging_root)
        if not os.path.samestat(staging_identity, staging_root.lstat()):
            raise PermissionError(
                f"staging directory identity changed: {staging_root}"
            )
        ensure_portable_name_available(parent, target_root.name)

        target_exists = os.path.lexists(target_root)
        target_identity: os.stat_result | None = None
        if target_exists:
            target_identity = target_root.lstat()
            if (
                _metadata_is_link_or_reparse_point(target_identity)
                or not stat.S_ISDIR(target_identity.st_mode)
            ):
                raise NotADirectoryError(target_root)
        if expected_destination_identity is not _UNSPECIFIED_IDENTITY:
            if expected_destination_identity is None:
                if target_identity is not None:
                    raise FileExistsError(
                        f"destination directory appeared before publication: {target_root}"
                    )
            elif (
                target_identity is None
                or not os.path.samestat(
                    expected_destination_identity,
                    target_identity,
                )
            ):
                raise PermissionError(
                    f"destination directory identity changed: {target_root}"
                )
        if target_exists and not overwrite:
            raise FileExistsError(target_root)

        backup: Path | None = None
        if target_exists:
            raw_backup = private_sibling_path(
                target_root,
                f".backup-{uuid.uuid4().hex}",
                field="directory publication backup",
            )
            rename_path_without_overwrite(
                target_root,
                raw_backup,
                expected_identity=target_identity,
            )
            _require_directory_identity(
                parent,
                parent_identity,
                field="directory publication parent",
            )
            try:
                backup = _exact_path(
                    raw_backup,
                    field="directory publication backup",
                )
                backup_metadata = backup.lstat()
                if (
                    _metadata_is_link_or_reparse_point(backup_metadata)
                    or not stat.S_ISDIR(backup_metadata.st_mode)
                    or target_identity is None
                    or not os.path.samestat(target_identity, backup_metadata)
                ):
                    raise PermissionError(
                        f"destination directory identity changed: {target_root}"
                    )
            except BaseException:
                if not os.path.lexists(target_root) and os.path.lexists(raw_backup):
                    try:
                        rename_path_without_overwrite(
                            raw_backup,
                            target_root,
                            expected_identity=target_identity,
                        )
                    except OSError:
                        pass
                raise

        try:
            _require_directory_identity(
                parent,
                parent_identity,
                field="directory publication parent",
            )
            rename_path_without_overwrite(
                staging_root,
                target_root,
                expected_identity=staging_identity,
            )
            _require_directory_identity(
                parent,
                parent_identity,
                field="directory publication parent",
            )
            published_metadata = target_root.lstat()
            if not os.path.samestat(staging_identity, published_metadata):
                raise PermissionError(
                    f"staging directory identity changed during publication: {staging_root}"
                )
        except BaseException:
            if backup is not None and not os.path.lexists(target_root):
                rename_path_without_overwrite(
                    backup,
                    target_root,
                    expected_identity=target_identity,
                )
                backup = None
            raise

        if backup is not None:
            backup = _exact_path(backup, field="directory publication backup")
            if (
                not backup.is_dir()
                or target_identity is None
                or not os.path.samestat(target_identity, backup.lstat())
            ):
                raise NotADirectoryError(backup)
            remove_directory_without_links(
                backup,
                expected_identity=target_identity,
            )
        _require_directory_identity(
            parent,
            parent_identity,
            field="directory publication parent",
        )
        return target_root


__all__ = [
    "atomic_binary_writer",
    "atomic_write_bytes",
    "atomic_write_text",
    "capture_directory_identity",
    "clear_directory_without_links",
    "copy_directory_without_links",
    "copy_file_exclusive",
    "copy_file_exclusive_with_identity",
    "copy_file_transactionally",
    "create_private_temporary_directory",
    "ensure_portable_name_available",
    "file_snapshot_is_stable",
    "inspect_portable_directory_tree",
    "inspect_portable_directory_tree_with_metadata",
    "open_binary_read_without_links",
    "open_binary_write_exclusive_without_links",
    "open_text_append_without_links",
    "portable_name_key",
    "private_sibling_path",
    "private_temporary_directory",
    "read_bytes_snapshot_without_links",
    "read_bytes_without_links",
    "read_text_snapshot_without_links",
    "read_text_without_links",
    "remove_directory_without_links",
    "remove_empty_directory_without_links",
    "remove_file_without_links",
    "remove_link_without_following",
    "rename_path_without_overwrite",
    "replace_directory_transactionally",
    "replace_file_transactionally",
    "require_directory_identity",
    "snapshot_directory_entries_without_links",
    "write_bytes_exclusive",
]
