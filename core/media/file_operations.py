"""Host filesystem operations exposed through higher-level adapters.

Paths preserve exact lexical identity, reject linked traversal, and use
transactional writes for destructive operations.
"""

from __future__ import annotations

import errno
import io
import os
import zipfile
import tarfile
import mimetypes
import subprocess
import platform
import stat
import threading
import uuid
from pathlib import Path
from typing import Any

from sdk.archive_paths import extract_tar_safely, extract_zip_safely
from sdk.file_transactions import (
    atomic_write_text,
    capture_directory_identity,
    copy_directory_without_links,
    copy_file_transactionally,
    create_private_temporary_directory,
    file_snapshot_is_stable,
    inspect_portable_directory_tree,
    open_binary_read_without_links,
    open_text_append_without_links,
    private_sibling_path,
    remove_directory_without_links,
    remove_empty_directory_without_links,
    remove_file_without_links,
    remove_link_without_following,
    rename_path_without_overwrite,
    replace_directory_transactionally,
    require_directory_identity,
    snapshot_directory_entries_without_links,
)
from sdk.path_contract import (
    _metadata_is_link_or_reparse_point,
    path_is_link_or_reparse_point,
    require_symlink_free_absolute_path,
    resolve_project_path,
    user_home_directory,
    validate_exact_path_text,
)
from sdk.process_launch import open_with_default_application

_FILE_SEARCH_LIMIT = 50
_FILE_EXTRACTION_LOCK = threading.RLock()


def _resolve(path_str: str) -> Path:
    """Resolve an exact user-filesystem path, with relative values under home."""

    return resolve_project_path(path_str, root=user_home_directory())


def _resolve_lexical(path_str: str) -> Path:
    """Keep the leaf identity while rejecting linked parent directories."""

    raw = validate_exact_path_text(path_str, field="filesystem path")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = user_home_directory().joinpath(*raw.replace("\\", "/").split("/"))
    return require_symlink_free_absolute_path(
        candidate,
        field="filesystem path",
        include_leaf=False,
    )


def _reject_write_target_link(path: Path) -> None:
    if path_is_link_or_reparse_point(path):
        raise PermissionError(f"Write target must not be a symbolic link: {path}")


def _copy_file_atomically(
    source: Path,
    destination: Path,
    *,
    expected_source_identity: os.stat_result | None = None,
) -> None:
    """Replace one regular destination without following its final link."""

    _reject_write_target_link(destination)
    copy_file_transactionally(
        source,
        destination,
        expected_source_identity=expected_source_identity,
    )


def _remove_private_move_path(
    path: Path,
    *,
    expected_identity: os.stat_result,
) -> None:
    """Remove only a UUID-named staging/holding path owned by this move."""

    if not os.path.lexists(path):
        return
    metadata = path.lstat()
    if not os.path.samestat(expected_identity, metadata):
        raise PermissionError(
            f"private move path identity changed: {path}"
        )
    if _metadata_is_link_or_reparse_point(metadata):
        remove_link_without_following(
            path,
            expected_identity=expected_identity,
        )
    elif stat.S_ISDIR(metadata.st_mode):
        remove_directory_without_links(
            path,
            expected_identity=expected_identity,
        )
    elif stat.S_ISREG(metadata.st_mode):
        remove_file_without_links(
            path,
            expected_identity=expected_identity,
        )
    else:
        raise PermissionError(f"private move path has an unsupported type: {path}")


def _restore_cross_volume_source(
    holding: Path,
    source: Path,
    *,
    expected_holding_identity: os.stat_result,
) -> None:
    """Restore a source-side holding name without overwriting a peer path."""

    if not os.path.lexists(holding):
        return
    if os.path.lexists(source):
        raise RuntimeError(
            "cross-volume move failed and the original source name was reused; "
            f"the preserved source is at {holding}"
        )
    rename_path_without_overwrite(
        holding,
        source,
        expected_identity=expected_holding_identity,
    )


def _move_across_filesystems(
    source: Path,
    destination: Path,
    *,
    expected_source_identity: os.stat_result,
) -> None:
    """Move through private sibling paths without exposing a partial target.

    A raw ``shutil.move`` changes from rename to an in-place copy on ``EXDEV``.
    That makes a half-copied destination visible if the copy is interrupted.
    Isolate the source under a source-volume holding name, build a complete
    destination-volume sibling, publish it, and only then remove the holding
    copy.  Failure before publication restores the original source identity.
    """

    if not destination.parent.is_dir():
        raise NotADirectoryError(destination.parent)

    holding = private_sibling_path(
        source,
        f".move-source-{uuid.uuid4().hex}",
        field="move source holding path",
    )
    staging = private_sibling_path(
        destination,
        f".move-target-{uuid.uuid4().hex}",
        field="move destination staging path",
    )
    published = False
    source_metadata = source.lstat()
    if not os.path.samestat(
        expected_source_identity,
        source_metadata,
    ):
        raise PermissionError(
            f"Move source identity changed: {source}"
        )
    source_is_link = _metadata_is_link_or_reparse_point(source_metadata)
    source_link_targets_directory = source.is_dir() if source_is_link else False
    staging_identity: os.stat_result | None = None
    build_root: Path | None = None
    build_root_identity: os.stat_result | None = None
    holding_identity: os.stat_result | None = None

    rename_path_without_overwrite(
        source,
        holding,
        expected_identity=source_metadata,
    )
    try:
        holding_identity = holding.lstat()
        if not os.path.samestat(source_metadata, holding_identity):
            raise PermissionError(
                f"Move source identity changed while it was isolated: {holding}"
            )
        build_root, build_root_identity = create_private_temporary_directory(
            directory=destination.parent,
            prefix=f".{destination.name}.move-build-",
        )
        payload = build_root / "payload"
        if source_is_link:
            link_target = os.readlink(holding)
            if not os.path.samestat(
                holding_identity,
                holding.lstat(),
            ):
                raise PermissionError(
                    f"Move source identity changed: {holding}"
                )
            os.symlink(
                link_target,
                payload,
                target_is_directory=source_link_targets_directory,
            )
            payload_identity = payload.lstat()
        elif stat.S_ISREG(source_metadata.st_mode):
            _copy_file_atomically(
                holding,
                payload,
                expected_source_identity=holding_identity,
            )
            payload_identity = payload.lstat()
        elif stat.S_ISDIR(source_metadata.st_mode):
            copy_directory_without_links(
                holding,
                payload,
                expected_source_identity=holding_identity,
            )
            payload_identity = payload.lstat()
        else:
            raise PermissionError(
                f"Move source must be a regular file, directory, or symbolic link: {source}"
            )

        rename_path_without_overwrite(
            payload,
            staging,
            expected_identity=payload_identity,
        )
        staging_identity = payload_identity
        remove_directory_without_links(
            build_root,
            expected_identity=build_root_identity,
        )
        build_root = None
        build_root_identity = None

        if os.path.lexists(destination):
            raise FileExistsError(f"Destination already exists: {destination}")
        if staging_identity is None:
            raise PermissionError(
                f"Move staging identity was not established: {staging}"
            )
        if (
            _metadata_is_link_or_reparse_point(staging_identity)
            or stat.S_ISREG(staging_identity.st_mode)
        ):
            rename_path_without_overwrite(
                staging,
                destination,
                expected_identity=staging_identity,
            )
        else:
            replace_directory_transactionally(
                staging,
                destination,
                overwrite=False,
                expected_staging_identity=staging_identity,
                expected_destination_identity=None,
            )
        published = True
    except BaseException:
        if not published:
            if staging_identity is not None:
                try:
                    _remove_private_move_path(
                        staging,
                        expected_identity=staging_identity,
                    )
                except (OSError, ValueError):
                    pass
            if (
                build_root is not None
                and build_root_identity is not None
            ):
                try:
                    remove_directory_without_links(
                        build_root,
                        expected_identity=build_root_identity,
                    )
                except (OSError, ValueError):
                    pass
            if holding_identity is None:
                current_holding_identity = holding.lstat()
                if not os.path.samestat(
                    source_metadata,
                    current_holding_identity,
                ):
                    raise PermissionError(
                        f"Move source identity changed while it was isolated: {holding}"
                    )
                holding_identity = current_holding_identity
            _restore_cross_volume_source(
                holding,
                source,
                expected_holding_identity=holding_identity,
            )
        raise

    # At this point the destination is complete.  A cleanup failure leaves the
    # UUID holding path intact instead of risking loss of the only full copy.
    if holding_identity is None:
        raise PermissionError(
            f"Move holding identity was not established: {holding}"
        )
    _remove_private_move_path(
        holding,
        expected_identity=holding_identity,
    )


def _safe(name: str, base: Path) -> Path | None:
    """Resolve and check existence; return None if not found."""
    p = resolve_project_path(name, root=base)
    if not p.exists():
        return None
    return p


def _safe_search_pattern(value: str, *, field: str) -> str:
    """Return a glob pattern that cannot escape its selected search root."""

    raw = str(value or "")
    if (
        not raw
        or raw != raw.strip()
        or any(
            ord(character) < 32
            or ord(character) == 127
            or 0xD800 <= ord(character) <= 0xDFFF
            for character in raw
        )
    ):
        raise ValueError(
            f"{field} is empty or contains surrounding whitespace or control characters"
        )
    portable = raw.replace("\\", "/")
    first = portable.split("/", 1)[0]
    if (
        portable.startswith("/")
        or (len(first) >= 2 and first[0].isalpha() and first[1] == ":")
        or first.startswith("~")
    ):
        raise ValueError(f"{field} must be relative to the selected directory")
    parts = portable.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PermissionError(f"{field} escapes the selected directory")
    return "/".join(parts)


def _walk_regular_file_snapshots(
    base: Path,
    base_identity: os.stat_result,
    pattern: str,
):
    """Yield one link-free recursive file inventory with pinned parent identities."""

    def walk(
        relative_directory: Path,
        expected_directory_identity: os.stat_result,
    ):
        directory = base / relative_directory
        try:
            (
                directory,
                directory_identity,
                entries,
            ) = snapshot_directory_entries_without_links(
                directory,
                field="file search directory",
            )
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            return
        if not os.path.samestat(
            expected_directory_identity,
            directory_identity,
        ):
            return
        for child, metadata in sorted(
            entries,
            key=lambda item: (
                item[0].name.casefold(),
                item[0].name,
            ),
        ):
            relative = relative_directory / child.name
            if _metadata_is_link_or_reparse_point(metadata):
                continue
            if stat.S_ISDIR(metadata.st_mode):
                yield from walk(relative, metadata)
            elif (
                stat.S_ISREG(metadata.st_mode)
                and relative.match(pattern)
            ):
                yield child, metadata, directory_identity

    yield from walk(Path(), base_identity)


# ── Read-only tools ──────────────────────────────────────────────────


def search_files(pattern: str, directory: str = "~") -> dict[str, Any]:
    base = (
        user_home_directory()
        if directory == "~"
        else _resolve_lexical(directory)
    )
    try:
        base, base_identity = capture_directory_identity(
            base,
            field="file search directory",
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return {"error": f"Directory not found: {base}", "matches": []}
    pattern = _safe_search_pattern(pattern, field="file search pattern")
    matches = []
    for candidate, metadata, parent_identity in _walk_regular_file_snapshots(
        base,
        base_identity,
        pattern,
    ):
        try:
            candidate = require_symlink_free_absolute_path(
                candidate,
                field="file search result",
            )
        except (FileNotFoundError, PermissionError, ValueError):
            continue
        try:
            current_metadata = candidate.lstat()
            require_directory_identity(
                candidate.parent,
                parent_identity,
                field="file search result parent",
            )
            require_directory_identity(
                base,
                base_identity,
                field="file search directory",
            )
        except (FileNotFoundError, PermissionError, ValueError):
            continue
        if not os.path.samestat(metadata, current_metadata):
            continue
        matches.append({
            "name": candidate.name,
            "path": str(candidate),
            "size": metadata.st_size,
            "size_human": _human_size(metadata.st_size),
        })
        if len(matches) >= _FILE_SEARCH_LIMIT:
            break
    require_directory_identity(
        base,
        base_identity,
        field="file search directory",
    )
    return {"pattern": pattern, "directory": str(base), "count": len(matches), "matches": matches}


def list_directory(path: str = "~") -> dict[str, Any]:
    p = (
        user_home_directory()
        if path == "~"
        else _resolve_lexical(path)
    )
    try:
        p, directory_identity, entries = (
            snapshot_directory_entries_without_links(
                p,
                field="listed directory",
            )
        )
    except (FileNotFoundError, NotADirectoryError):
        return {"error": f"Directory not found: {p}"}
    except PermissionError:
        return {"error": f"Permission denied: {p}", "items": []}
    items = []
    try:
        for entry, metadata in sorted(
            entries,
            key=lambda item: (
                not stat.S_ISDIR(item[1].st_mode),
                item[0].name.lower(),
            ),
        ):
            if _metadata_is_link_or_reparse_point(metadata):
                entry_type = "symbolic-link"
            elif stat.S_ISDIR(metadata.st_mode):
                entry_type = "dir"
            elif stat.S_ISREG(metadata.st_mode):
                entry_type = "file"
            else:
                entry_type = "special"
            info = {"name": entry.name, "type": entry_type}
            if entry_type == "file":
                info["size"] = metadata.st_size
                info["size_human"] = _human_size(metadata.st_size)
            items.append(info)
        require_directory_identity(
            p,
            directory_identity,
            field="listed directory",
        )
    except PermissionError:
        return {"error": f"Permission denied: {p}", "items": []}
    return {"path": str(p), "count": len(items), "items": items}


def read_text_file(path: str, max_chars: int = 5000, line_start: int = 0, line_end: int = 0) -> dict[str, Any]:
    p = _resolve_lexical(path)
    try:
        with open_binary_read_without_links(p) as source:
            before = os.fstat(source.fileno())
            size = before.st_size
            with io.TextIOWrapper(source, encoding="utf-8", errors="replace") as f:
                content = f.read(max_chars)
                after = os.fstat(f.buffer.fileno())
        if not file_snapshot_is_stable(before, after):
            raise PermissionError(
                f"File changed while it was being read: {p}"
            )
        if line_start > 0:
            lines = content.split("\n")
            s = max(0, line_start - 1)
            e = min(len(lines), line_end) if line_end > 0 else len(lines)
            content = "\n".join(lines[s:e])
            if len(content) > max_chars:
                content = content[:max_chars]
        truncated = len(content) >= max_chars
        return {
            "path": str(p),
            "size": size,
            "content": content,
            "truncated": truncated,
        }
    except Exception as e:
        return {"error": str(e), "path": str(p)}


def inspect_path(path: str) -> dict[str, Any]:
    p = _resolve_lexical(path)
    try:
        st = p.lstat()
    except FileNotFoundError:
        return {"error": f"Path not found: {p}"}
    if _metadata_is_link_or_reparse_point(st):
        path_type = "symbolic-link"
    elif stat.S_ISDIR(st.st_mode):
        path_type = "directory"
    elif stat.S_ISREG(st.st_mode):
        path_type = "file"
    else:
        path_type = "special"
    mime, _ = (
        mimetypes.guess_type(str(p))
        if path_type == "file"
        else (None, None)
    )
    current = p.lstat()
    if not os.path.samestat(st, current):
        return {"error": f"Path changed while it was inspected: {p}"}
    return {
        "name": p.name,
        "path": str(p),
        "type": path_type,
        "size": st.st_size if path_type == "file" else None,
        "size_human": _human_size(st.st_size) if path_type == "file" else None,
        "mime": mime or "unknown",
        "modified": _ts_to_str(st.st_mtime),
        "created": _ts_to_str(st.st_ctime),
    }


def open_local_path(path: str) -> dict[str, Any]:
    resolved: Path | str = path
    try:
        resolved = _resolve_lexical(path)
        open_with_default_application(
            resolved,
            wait=platform.system() != "Windows",
            check=True,
            system_name=platform.system(),
            run_factory=subprocess.run,
            startfile_factory=getattr(os, "startfile", None),
        )
        return {"opened": str(resolved)}
    except Exception as e:
        return {"error": str(e), "path": str(resolved)}


def search_file_content(keyword: str, directory: str = "~", file_pattern: str = "*") -> dict[str, Any]:
    base = (
        user_home_directory()
        if directory == "~"
        else _resolve_lexical(directory)
    )
    try:
        base, base_identity = capture_directory_identity(
            base,
            field="content search directory",
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return {"error": f"Directory not found: {base}"}
    file_pattern = _safe_search_pattern(
        file_pattern,
        field="content search pattern",
    )
    results = []
    count = 0
    for (
        candidate,
        candidate_identity,
        candidate_parent_identity,
    ) in _walk_regular_file_snapshots(
        base,
        base_identity,
        file_pattern,
    ):
        reached_limit = False
        try:
            candidate = require_symlink_free_absolute_path(
                candidate,
                field="content search file",
            )
        except (FileNotFoundError, NotADirectoryError, PermissionError, ValueError):
            continue
        candidate_parent = candidate.parent
        try:
            pending_results: list[dict[str, Any]] = []
            with open_binary_read_without_links(
                candidate,
                expected_identity=candidate_identity,
                expected_parent_identity=candidate_parent_identity,
            ) as source:
                before = os.fstat(source.fileno())
                if before.st_size > 2 * 1024 * 1024:
                    continue
                with io.TextIOWrapper(
                    source,
                    encoding="utf-8",
                    errors="replace",
                ) as f:
                    for i, line in enumerate(f, 1):
                        if keyword.lower() in line.lower():
                            pending_results.append({
                                "file": str(candidate),
                                "line": i,
                                "content": line.strip()[:200],
                            })
                            if count + len(pending_results) >= 30:
                                reached_limit = True
                                break
                    after = os.fstat(f.buffer.fileno())
            if not file_snapshot_is_stable(before, after):
                continue
            require_directory_identity(
                candidate_parent,
                candidate_parent_identity,
                field="content search file parent",
            )
            require_directory_identity(
                base,
                base_identity,
                field="content search directory",
            )
            results.extend(pending_results)
            count += len(pending_results)
        except Exception:
            continue
        if reached_limit:
            break
    require_directory_identity(
        base,
        base_identity,
        field="content search directory",
    )
    return {"keyword": keyword, "directory": str(base), "count": len(results), "matches": results}


# ── Write / destructive tools ────────────────────────────────────────


def move_path(source: str, dest: str) -> dict[str, Any]:
    src = _resolve_lexical(source)
    dst = _resolve_lexical(dest)
    if not os.path.lexists(src):
        return {"error": f"Source not found: {src}"}
    try:
        _reject_write_target_link(dst)
        if os.path.lexists(dst):
            raise FileExistsError(f"Destination already exists: {dst}")
        require_symlink_free_absolute_path(
            src,
            field="move source",
            include_leaf=False,
        )
        require_symlink_free_absolute_path(
            dst,
            field="move destination",
            include_leaf=False,
        )
        source_identity = src.lstat()
        try:
            rename_path_without_overwrite(
                src,
                dst,
                expected_identity=source_identity,
            )
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            _move_across_filesystems(
                src,
                dst,
                expected_source_identity=source_identity,
            )
        return {"moved": str(src), "to": str(dst)}
    except Exception as e:
        return {"error": str(e), "source": str(src), "dest": str(dst)}


def copy_file(source: str, dest: str) -> dict[str, Any]:
    src = _resolve(source)
    dst = _resolve_lexical(dest)
    try:
        source_identity = src.lstat()
    except FileNotFoundError:
        return {"error": f"Source file not found: {src}"}
    if (
        _metadata_is_link_or_reparse_point(source_identity)
        or not stat.S_ISREG(source_identity.st_mode)
    ):
        return {"error": f"Source file not found: {src}"}
    try:
        _copy_file_atomically(
            src,
            dst,
            expected_source_identity=source_identity,
        )
        return {"copied": str(src), "to": str(dst)}
    except Exception as e:
        return {"error": str(e)}


def delete_path(path: str) -> dict[str, Any]:
    p = _resolve_lexical(path)
    if not os.path.lexists(p):
        return {"error": f"Path not found: {p}"}
    try:
        metadata = p.lstat()
        if _metadata_is_link_or_reparse_point(metadata):
            size = metadata.st_size
            remove_link_without_following(p, expected_identity=metadata)
            return {
                "deleted": str(p),
                "type": "symbolic-link",
                "size_human": _human_size(size),
            }
        if stat.S_ISDIR(metadata.st_mode):
            remove_empty_directory_without_links(
                p,
                expected_identity=metadata,
            )
            return {"deleted": str(p), "type": "directory"}
        if stat.S_ISREG(metadata.st_mode):
            size = metadata.st_size
            remove_file_without_links(p, expected_identity=metadata)
            return {"deleted": str(p), "type": "file", "size_human": _human_size(size)}
        return {"error": f"Unsupported file type: {p}", "path": str(p)}
    except Exception as e:
        return {"error": str(e), "path": str(p)}


def extract_archive(archive_path: str, destination: str = "") -> dict[str, Any]:
    p = _resolve(archive_path)
    try:
        archive_identity = p.lstat()
    except FileNotFoundError:
        return {"error": f"Archive not found: {p}"}
    if (
        _metadata_is_link_or_reparse_point(archive_identity)
        or not stat.S_ISREG(archive_identity.st_mode)
    ):
        return {"error": f"Archive not found: {p}"}
    dest = _resolve_lexical(destination) if destination else p.parent / p.stem
    try:
        name_low = p.name.lower()
        if name_low.endswith(".zip"):
            def extract(staging: Path) -> None:
                with open_binary_read_without_links(
                    p,
                    expected_identity=archive_identity,
                ) as source:
                    before = os.fstat(source.fileno())
                    with zipfile.ZipFile(source, "r") as zf:
                        extract_zip_safely(zf, staging)
                    after = os.fstat(source.fileno())
                    if not file_snapshot_is_stable(before, after):
                        raise PermissionError(
                            f"archive changed while it was extracted: {p}"
                        )
        elif name_low.endswith((".tar.gz", ".tgz")):
            def extract(staging: Path) -> None:
                with open_binary_read_without_links(
                    p,
                    expected_identity=archive_identity,
                ) as source:
                    before = os.fstat(source.fileno())
                    with tarfile.open(fileobj=source, mode="r:gz") as tf:
                        extract_tar_safely(tf, staging)
                    after = os.fstat(source.fileno())
                    if not file_snapshot_is_stable(before, after):
                        raise PermissionError(
                            f"archive changed while it was extracted: {p}"
                        )
        elif name_low.endswith(".tar"):
            def extract(staging: Path) -> None:
                with open_binary_read_without_links(
                    p,
                    expected_identity=archive_identity,
                ) as source:
                    before = os.fstat(source.fileno())
                    with tarfile.open(fileobj=source, mode="r:") as tf:
                        extract_tar_safely(tf, staging)
                    after = os.fstat(source.fileno())
                    if not file_snapshot_is_stable(before, after):
                        raise PermissionError(
                            f"archive changed while it was extracted: {p}"
                        )
        else:
            return {"error": f"Unsupported archive format: {p.name}"}
        _extract_directory_transactionally(dest, extract)
        # Count extracted files
        directories, files = inspect_portable_directory_tree(dest)
        extracted = len(directories) + len(files)
        return {"extracted": str(p), "to": str(dest), "files_count": extracted}
    except Exception as e:
        return {"error": str(e), "archive": str(p)}


def _extract_directory_transactionally(dest: Path, extractor) -> None:
    """Publish a complete extraction and preserve a prior destination on error."""

    with _FILE_EXTRACTION_LOCK:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest = require_symlink_free_absolute_path(
            dest,
            field="extraction target",
            include_leaf=False,
        )
        existed = os.path.lexists(dest)
        if path_is_link_or_reparse_point(dest):
            raise PermissionError(f"Extraction target is a symbolic link: {dest}")
        if existed and not dest.is_dir():
            raise FileExistsError(f"Extraction target is not a directory: {dest}")
        identity = None
        destination_identity: os.stat_result | None = None
        if existed:
            stat_result = dest.stat()
            destination_identity = dest.lstat()
            identity = (
                stat_result.st_dev,
                stat_result.st_ino,
                stat_result.st_mtime_ns,
            )

        staging = private_sibling_path(
            dest,
            f".extract-{uuid.uuid4().hex}",
            field="extraction staging directory",
        )
        staging_identity: os.stat_result | None = None
        try:
            if existed:
                copy_directory_without_links(dest, staging)
            else:
                staging.mkdir()
            staging_identity = staging.lstat()
            extractor(staging)

            current_exists = os.path.lexists(dest)
            if current_exists != existed:
                raise FileExistsError(f"Extraction target changed while extracting: {dest}")
            dest = require_symlink_free_absolute_path(
                dest,
                field="extraction target",
                include_leaf=False,
            )
            if existed:
                if path_is_link_or_reparse_point(dest) or not dest.is_dir():
                    raise FileExistsError(f"Extraction target changed while extracting: {dest}")
                current_stat = dest.stat()
                current_identity = (
                    current_stat.st_dev,
                    current_stat.st_ino,
                    current_stat.st_mtime_ns,
                )
                if current_identity != identity:
                    raise FileExistsError(f"Extraction target changed while extracting: {dest}")
            replace_directory_transactionally(
                staging,
                dest,
                overwrite=True,
                expected_staging_identity=staging_identity,
                expected_destination_identity=destination_identity,
            )
        finally:
            if staging_identity is not None:
                try:
                    remove_directory_without_links(
                        staging,
                        expected_identity=staging_identity,
                    )
                except OSError:
                    pass


def write_text_file(path: str, content: str) -> dict[str, Any]:
    p = _resolve_lexical(path)
    existed = os.path.lexists(p)
    try:
        atomic_write_text(p, content)
        return {"written": str(p), "size": p.stat().st_size, "existed": existed}
    except Exception as e:
        return {"error": str(e), "path": str(p)}


def append_text_file(path: str, content: str) -> dict[str, Any]:
    p = _resolve_lexical(path)
    existed = os.path.lexists(p)
    try:
        _reject_write_target_link(p)
        with open_text_append_without_links(p, encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return {"appended": str(p), "size": p.stat().st_size, "existed": existed}
    except Exception as e:
        return {"error": str(e), "path": str(p)}


def create_directory(path: str) -> dict[str, Any]:
    p = _resolve_lexical(path)
    if os.path.lexists(p):
        return {"error": f"Path already exists: {p}"}
    try:
        p.mkdir(parents=True, exist_ok=False)
        p = require_symlink_free_absolute_path(p, field="created directory")
        if not p.is_dir():
            raise NotADirectoryError(p)
        return {"created": str(p)}
    except Exception as e:
        return {"error": str(e), "path": str(p)}


# ── Helpers ───────────────────────────────────────────────────────────


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _ts_to_str(ts: float) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
