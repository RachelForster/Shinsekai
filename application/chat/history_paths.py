"""Project-root-aware chat history path resolution and import.

Relative references are project-managed and stay inside the configured history
collection. Explicit absolute references are external capabilities and retain
their storage identity across launch, save, resume, and clear operations.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import re
import stat
import threading
from pathlib import Path
from typing import Any

from core.sprite.chat_branch_storage import (
    ACTIVE_HISTORY_FILENAME,
    BRANCH_TREE_FILENAME,
    chat_history_session_dir,
)
from core.file_transactions import (
    atomic_write_text,
    copy_directory_without_links,
    copy_file_exclusive,
    create_private_temporary_directory,
    inspect_portable_directory_tree,
    read_text_without_links,
    rename_path_without_overwrite,
    remove_directory_without_links,
)
from core.paths import (
    _metadata_is_link_or_reparse_point,
    path_is_link_or_reparse_point,
    require_directory_without_links,
    require_regular_file_without_links,
    require_symlink_free_absolute_path,
    resolve_managed_project_path,
    validate_exact_path_text,
)

from sdk.path_references import (
    display_path,
    is_absolute_path_text,
    legacy_project_relative_path,
    portable_path_text,
    project_relative_path,
    resolved_path_is_within,
    state_project_root,
)
from sdk.path_utils import safe_project_path


_HISTORY_LEGACY_PREFIXES = (("data", "chat_history"),)
_IMPORT_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_IMPORT_MARKER_FILENAME = ".shinsekai-import.json"
_IMPORT_MARKER_VERSION = 1
_IMPORT_PUBLICATION_LOCK = threading.Lock()
_MAX_IMPORT_NAME_ATTEMPTS = 10_000


def history_root_for_state(state: Any) -> Path:
    """Return the configured history directory inside the authoritative root."""

    root = state_project_root(state)
    raw = str(getattr(state, "history_dir", "") or "data/chat_history")
    history_root = resolve_managed_project_path(raw, root=root)
    if history_root == root or not resolved_path_is_within(history_root, root):
        raise PermissionError("chat history directory is outside project root")
    return history_root


def _history_path_shape(path: Path) -> Path:
    if path.name in {ACTIVE_HISTORY_FILENAME, BRANCH_TREE_FILENAME}:
        return path.parent
    if path.suffix.lower() == ".json" and not path.is_file():
        return path.with_suffix("")
    return path


def _managed_history_path(path: Path, history_root: Path) -> Path:
    """Return one concrete session path, never the history collection root.

    A path such as ``data/chat_history/active.json`` shapes to its parent.  If
    that parent is the collection root, passing it to the recursive clear
    helper would erase every session.  Keep this invariant at the path
    boundary so every reader and destructive caller receives the same value.
    """

    try:
        root = history_root.resolve(strict=False)
        lexical = path
        if lexical == root:
            raise PermissionError(
                "chat history path must identify a session, not the history root"
            )
        if not resolved_path_is_within(lexical, root):
            raise PermissionError(
                "chat history must be stored under the history directory"
            )
        # Validate the unresolved value before shaping legacy ``*.json`` paths.
        # Otherwise a linked session directory can be flattened into the real
        # target and later clear/branch operations may mutate a different
        # session while still appearing to remain under the history root.
        inspected = resolve_managed_project_path(path, root=root)
        shaped = _history_path_shape(inspected)
        if shaped == root:
            raise PermissionError(
                "chat history path must identify a session, not the history root"
            )
        resolved = resolve_managed_project_path(shaped, root=root)
    except PermissionError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("historyPath could not be resolved") from exc
    if resolved == root:
        raise PermissionError("chat history path must identify a session, not the history root")
    if not resolved_path_is_within(resolved, root):
        raise PermissionError("chat history must be stored under the history directory")

    session_dir = resolved if not resolved.is_file() else None
    if session_dir is not None:
        for name in (
            ACTIVE_HISTORY_FILENAME,
            BRANCH_TREE_FILENAME,
            f"{ACTIVE_HISTORY_FILENAME}.tmp",
        ):
            if path_is_link_or_reparse_point(session_dir / name):
                raise PermissionError("chat history session files must not be symbolic links")
    return resolved


def history_storage_exists(path: Path) -> bool:
    """Return whether a legacy file or directory-based history has data."""

    try:
        if path_is_link_or_reparse_point(path):
            return False
        if path.is_file() and path.suffix.lower() == ".json":
            return True
        session_dir = path if path.is_dir() else chat_history_session_dir(path)
        if path_is_link_or_reparse_point(session_dir):
            return False
        return any(
            not path_is_link_or_reparse_point(candidate) and candidate.is_file()
            for candidate in (
                session_dir / ACTIVE_HISTORY_FILENAME,
                session_dir / BRANCH_TREE_FILENAME,
                session_dir / f"{ACTIVE_HISTORY_FILENAME}.tmp",
            )
        )
    except OSError:
        return False


def _import_slug(
    source: Path,
    *,
    source_is_file: bool | None = None,
) -> str:
    if source_is_file is None:
        metadata = source.lstat()
        source_is_file = stat.S_ISREG(metadata.st_mode)
    stem = source.stem if source_is_file else source.name
    slug = _IMPORT_NAME_RE.sub("-", stem).strip(".-")[:48] or "history"
    identity = os.path.normcase(str(source))
    digest = hashlib.sha256(identity.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
    return f"imported-{slug}-{digest}"


def _import_source_identity(source: Path) -> str:
    return os.path.normcase(str(source))


def _import_marker_payload(
    source: Path,
    *,
    source_is_file: bool | None = None,
) -> dict[str, Any]:
    if source_is_file is None:
        metadata = source.lstat()
        source_is_file = stat.S_ISREG(metadata.st_mode)
    return {
        "kind": "file" if source_is_file else "directory",
        "source": _import_source_identity(source),
        "version": _IMPORT_MARKER_VERSION,
    }


def _write_import_marker(destination: Path, payload: dict[str, Any]) -> None:
    marker = destination / _IMPORT_MARKER_FILENAME
    atomic_write_text(
        marker,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )


def _owned_import_destination(candidate: Path, marker_payload: dict[str, Any]) -> bool:
    if path_is_link_or_reparse_point(candidate) or not candidate.is_dir():
        return False
    marker = candidate / _IMPORT_MARKER_FILENAME
    if path_is_link_or_reparse_point(marker) or not marker.is_file():
        return False
    try:
        raw = json.loads(read_text_without_links(marker))
    except (OSError, ValueError):
        return False
    return (
        isinstance(raw, dict)
        and raw.get("version") == marker_payload["version"]
        and raw.get("kind") == marker_payload["kind"]
        and raw.get("source") == marker_payload["source"]
        and history_storage_exists(candidate)
    )


def _select_import_destination(
    history_root: Path,
    slug: str,
    marker_payload: dict[str, Any],
) -> tuple[Path, bool]:
    """Pick an owned destination without overwriting an unrelated collision."""

    for index in range(_MAX_IMPORT_NAME_ATTEMPTS):
        name = slug if index == 0 else f"{slug}-{index}"
        candidate = history_root / name
        # lexists is deliberate: a broken symlink is still an occupied name.
        if not os.path.lexists(candidate):
            return safe_project_path(candidate, root=history_root), False
        if _owned_import_destination(candidate, marker_payload):
            return _managed_history_path(candidate, history_root), True
    raise RuntimeError("too many chat history import name collisions")


def _validate_history_directory(source: Path) -> None:
    if not history_storage_exists(source):
        raise ValueError(f"所选目录不是有效的聊天历史目录: {display_path(source)}")
    try:
        inspect_portable_directory_tree(source)
    except (OSError, ValueError) as exc:
        raise PermissionError(
            f"聊天历史目录包含符号链接或非常规路径，无法安全导入: {display_path(source)}"
        ) from exc


def import_external_history(state: Any, source: str | os.PathLike[str]) -> Path:
    """Copy an external history into project-managed storage and return it."""

    raw_source = validate_exact_path_text(source, field="external chat history path")
    unresolved_source = Path(raw_source)
    if not unresolved_source.is_absolute():
        raise ValueError("external chat history path must be absolute")
    try:
        require_symlink_free_absolute_path(
            unresolved_source,
            field="external chat history path",
        )
    except PermissionError as exc:
        raise PermissionError(
            "external chat history path must not use symbolic links or reparse points: "
            f"{display_path(unresolved_source)}"
        ) from exc
    source = unresolved_source.resolve(strict=True)
    if source.name in {ACTIVE_HISTORY_FILENAME, BRANCH_TREE_FILENAME}:
        source = source.parent.resolve(strict=True)
    source_identity = source.lstat()
    if _metadata_is_link_or_reparse_point(source_identity):
        raise PermissionError(
            "external chat history path must not use symbolic links or reparse points"
        )
    source_is_file = stat.S_ISREG(source_identity.st_mode)
    source_is_directory = stat.S_ISDIR(source_identity.st_mode)
    if source_is_file and source.suffix.lower() != ".json":
        raise ValueError(f"聊天历史文件必须是 JSON: {display_path(source)}")
    if not source_is_file and not source_is_directory:
        raise FileNotFoundError(display_path(source))

    history_root = history_root_for_state(state)
    history_root.mkdir(parents=True, exist_ok=True)
    history_root = require_directory_without_links(
        history_root,
        field="chat history import directory",
    )
    slug = _import_slug(source, source_is_file=source_is_file)
    marker_payload = _import_marker_payload(
        source,
        source_is_file=source_is_file,
    )
    if source_is_directory:
        _validate_history_directory(source)
        if not os.path.samestat(source_identity, source.lstat()):
            raise PermissionError(
                "external chat history directory changed while it was validated"
            )

    # Every import is published as a directory session.  In particular, a
    # legacy ``foo.json`` becomes ``<managed>/.../active.json`` instead of a
    # root-level file whose paired ``foo/`` directory could belong to someone
    # else and be recursively removed by legacy cleanup semantics.
    with _IMPORT_PUBLICATION_LOCK:
        destination, already_imported = _select_import_destination(
            history_root,
            slug,
            marker_payload,
        )
        if already_imported:
            return destination

        staging, staging_identity = create_private_temporary_directory(
            directory=history_root,
            prefix=f".{slug}.tmp-",
        )
        try:
            staged_history = staging / "history"
            if source_is_file:
                staged_history.mkdir()
                copy_file_exclusive(
                    source,
                    staged_history,
                    ACTIVE_HISTORY_FILENAME,
                    field="history filename",
                    expected_source_identity=source_identity,
                )
            else:
                copy_directory_without_links(
                    source,
                    staged_history,
                    expected_source_identity=source_identity,
                )
                _validate_history_directory(staged_history)
            _write_import_marker(staged_history, marker_payload)

            # The process-local lock serializes bridge threads.  A second
            # bridge process can still publish between selection and rename;
            # retry that race and either reuse its owned snapshot or choose a
            # collision suffix.  A complete session directory is non-empty,
            # so rename cannot replace a peer publication on supported hosts.
            while True:
                if os.path.lexists(destination):
                    destination, already_imported = _select_import_destination(
                        history_root,
                        slug,
                        marker_payload,
                    )
                    if already_imported:
                        return destination
                    continue
                try:
                    rename_path_without_overwrite(
                        staged_history,
                        destination,
                        expected_identity=staged_history.lstat(),
                    )
                except OSError:
                    if os.path.lexists(destination):
                        destination, already_imported = _select_import_destination(
                            history_root,
                            slug,
                            marker_payload,
                        )
                        if already_imported:
                            return destination
                        continue
                    raise
                break
        finally:
            try:
                remove_directory_without_links(
                    staging,
                    expected_identity=staging_identity,
                )
            except OSError:
                pass
    return _managed_history_path(destination, history_root)


def resolve_history_reference(
    state: Any,
    raw_path: str | os.PathLike[str],
    *,
    recover_legacy_absolute: bool = False,
) -> Path:
    """Resolve a user/session history reference to project-managed storage.

    Missing absolute paths are external identities during normal operation.
    The optional legacy recovery is reserved for one-time persistence
    migrations; otherwise an unrelated missing path whose tail happens to be
    ``data/chat_history`` could be silently rebound to the active project.
    """

    raw = portable_path_text(raw_path, field="historyPath")
    project_root = state_project_root(state)
    history_root = history_root_for_state(state)

    def collapses_to_collection_root() -> bool:
        collapsed: list[str] = []
        for component in raw.replace("\\", "/").split("/"):
            if component in {"", "."}:
                continue
            if component == "..":
                if collapsed:
                    collapsed.pop()
                continue
            collapsed.append(component)
        try:
            history_relative = history_root.relative_to(project_root).as_posix()
        except ValueError:
            return False
        return "/".join(collapsed) == history_relative

    try:
        validate_exact_path_text(
            raw,
            field="historyPath",
            allow_non_native_absolute=True,
        )
    except PermissionError:
        if collapses_to_collection_root():
            raise PermissionError(
                "chat history path must identify a session, not the history root"
            ) from None
        raise

    if not is_absolute_path_text(raw):
        try:
            candidate = resolve_managed_project_path(raw, root=project_root)
        except PermissionError:
            # Preserve the higher-level collection-root invariant for values
            # such as ``session/..`` while still rejecting any linked
            # component through the original managed-path error.
            if collapses_to_collection_root():
                raise PermissionError(
                    "chat history path must identify a session, not the history root"
                )
            raise
        if resolved_path_is_within(candidate, history_root):
            return _managed_history_path(candidate, history_root)
        # An existing relative path is an explicit source selection.  Import
        # it before applying the basename shorthand; otherwise a real
        # ``<project>/session.json`` would be silently ignored in favor of a
        # new empty ``data/chat_history/session``.
        if candidate.exists():
            return _managed_history_path(import_external_history(state, candidate), history_root)
        # Preserve the useful shorthand ``session.json`` while ensuring it is
        # created under the dedicated mutable-history directory.
        normalized_parts = Path(raw.replace("\\", "/")).parts
        if len(normalized_parts) == 1:
            return _managed_history_path(
                safe_project_path(history_root / normalized_parts[0], root=history_root),
                history_root,
            )
        raise PermissionError("chat history must be stored under data/chat_history")

    native_candidate = Path(raw).expanduser()
    if native_candidate.is_absolute():
        try:
            require_symlink_free_absolute_path(
                native_candidate,
                field="external chat history path",
            )
        except PermissionError as exc:
            raise PermissionError(
                "external chat history path must not use symbolic links or reparse points: "
                f"{display_path(native_candidate)}"
            ) from exc
        try:
            resolved = native_candidate.resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError("historyPath could not be resolved") from exc
        if resolved_path_is_within(native_candidate, history_root) or resolved_path_is_within(
            resolved,
            history_root,
        ):
            return _managed_history_path(native_candidate, history_root)
        if resolved.exists():
            return _managed_history_path(import_external_history(state, resolved), history_root)

    if recover_legacy_absolute:
        legacy_relative = legacy_project_relative_path(
            raw,
            _HISTORY_LEGACY_PREFIXES,
        )
        if legacy_relative is not None:
            migrated = safe_project_path(legacy_relative, root=project_root)
            if resolved_path_is_within(migrated, history_root):
                return _managed_history_path(migrated, history_root)

    raise FileNotFoundError(f"外部聊天历史不存在，无法导入: {display_path(raw)}")


def prepare_history_reference_for_launch(
    state: Any,
    raw_path: str | os.PathLike[str],
) -> Path:
    """Create and revalidate the exact managed history identity passed to chat.

    Launchers must not call ``resolve()`` after this boundary. Doing so would
    let a link inserted between selection and process creation silently change
    the path consumed by the child process.
    """

    path = resolve_history_reference(state, raw_path)
    if path.suffix.lower() == ".json" and os.path.lexists(path):
        path = require_regular_file_without_links(
            path,
            field="chat history file",
        )
        require_directory_without_links(
            path.parent,
            field="chat history directory",
        )
        return path

    session_dir = chat_history_session_dir(path)
    session_dir.mkdir(parents=True, exist_ok=True)
    require_directory_without_links(
        session_dir,
        field="chat history session directory",
    )
    return path


def project_history_value(state: Any, path: Path) -> str:
    """Serialize a managed history as a portable project-relative value."""

    managed = _managed_history_path(path, history_root_for_state(state))
    relative = project_relative_path(managed, state_project_root(state))
    if relative is None:
        raise PermissionError("chat history is outside project root")
    return relative


def history_reference_value(state: Any, path: Path) -> str:
    """Serialize one live history path without changing its storage scope.

    Project-managed sessions stay portable and project-relative. An explicitly
    external session stays external so a save/resume cycle cannot silently
    redirect the runtime to a copied or guessed location.
    """

    candidate = resolve_history_path_for_project(state, path)
    if is_unc_history_path(candidate):
        return candidate.as_posix()
    history_root = history_root_for_state(state)
    if resolved_path_is_within(candidate, history_root):
        return project_history_value(state, candidate)
    return candidate.as_posix()


def _state_project_root(state: Any) -> Path:
    """Compatibility wrapper around the bridge's authoritative root policy."""

    return state_project_root(state)


def _validate_unc_share(value: str) -> None:
    parts = value.split("\\")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError("history path must include a UNC server and share")
    if parts[0] in {".", ".."} or parts[1] in {".", ".."}:
        raise ValueError("history path contains an invalid UNC server or share")


def _windows_history_path_kind(raw: str) -> str:
    """Classify a Windows history path without touching the filesystem."""

    value = raw.replace("/", "\\")
    upper = value.upper()
    if upper.startswith("\\\\.\\") or upper.startswith("\\??\\"):
        raise ValueError("Windows device paths are not allowed for chat history")

    if upper.startswith("\\\\?\\"):
        tail = value[4:]
        if tail.upper().startswith("UNC\\"):
            _validate_unc_share(tail[4:])
            return "absolute"
        drive, remainder = ntpath.splitdrive(tail)
        if len(drive) == 2 and drive[1] == ":" and remainder.startswith("\\"):
            return "absolute"
        raise ValueError("unsupported Windows verbatim path for chat history")

    if value.startswith("\\\\"):
        _validate_unc_share(value[2:])
        return "absolute"

    drive, remainder = ntpath.splitdrive(value)
    if drive:
        if len(drive) == 2 and drive[1] == ":" and remainder.startswith("\\"):
            return "absolute"
        raise ValueError("drive-relative history paths are not allowed")
    if value.startswith("\\"):
        raise ValueError("root-relative history paths are not allowed")
    return "relative"


def _history_path_kind(raw: str) -> str:
    if os.name == "nt":
        return _windows_history_path_kind(raw)
    return "absolute" if Path(raw).is_absolute() else "relative"


def _absolute_history_path(raw: str) -> Path:
    # This is deliberately lexical. Resolving an offline UNC share can block,
    # and an explicit absolute history path is allowed outside the project.
    value = ntpath.normpath(raw) if os.name == "nt" else os.path.normpath(raw)
    return Path(value)


def is_unc_history_path(path: str | Path) -> bool:
    """Identify UNC paths lexically so an offline share is never probed."""

    if os.name != "nt":
        return False
    value = str(path).replace("/", "\\")
    upper = value.upper()
    if upper.startswith("\\\\?\\UNC\\"):
        return True
    return value.startswith("\\\\") and not upper.startswith(
        ("\\\\?\\", "\\\\.\\", "\\??\\")
    )


def _validate_history_storage_target(path: Path) -> Path:
    """Reject an existing unrelated file/directory as a history storage root."""

    if is_unc_history_path(path):
        return path
    if not path.exists():
        return path
    if path.is_file():
        if path.suffix.lower() != ".json":
            raise ValueError("an existing chat history file must use the .json suffix")
        return path
    if not path.is_dir():
        raise ValueError("chat history path is not a regular file or directory")

    known_names = {
        "active.json",
        "active.json.tmp",
        "branches.json",
    }
    try:
        entries = list(path.iterdir())
    except OSError as exc:
        raise ValueError(f"chat history directory is not accessible: {path}") from exc
    if entries and not any(entry.name in known_names for entry in entries):
        raise ValueError("existing directory is not a chat history session directory")
    return path


def resolve_history_path_for_project(state: Any, raw_path: Any) -> Path:
    """Resolve a live history path without deriving relative paths from cwd.

    Relative references are project-managed. Explicit absolute references are
    permitted for the React chat runtime (including another Windows drive or
    an offline UNC share) and remain lexical so resolving an unavailable share
    cannot block startup.
    """

    raw = portable_path_text(
        os.fspath(raw_path) if raw_path is not None else "",
        field="history path",
    )

    history_root = history_root_for_state(state)
    if _history_path_kind(raw) == "absolute":
        candidate = _absolute_history_path(raw)
        if not is_unc_history_path(candidate):
            candidate = require_symlink_free_absolute_path(
                candidate,
                field="external chat history path",
            )
    else:
        # Relative references never gain external privileges. A one-component
        # legacy shorthand is rooted in the history collection; every other
        # relative value must already identify a descendant of that collection.
        candidate = safe_project_path(raw, root=_state_project_root(state))
        if not resolved_path_is_within(candidate, history_root):
            parts = Path(raw.replace("\\", "/")).parts
            if len(parts) != 1:
                raise PermissionError(
                    "relative chat history must be stored under the history directory"
                )
            candidate = safe_project_path(
                history_root / parts[0],
                root=history_root,
            )
    if candidate == history_root or (
        candidate.parent == history_root
        and candidate.name
        in {
            ACTIVE_HISTORY_FILENAME,
            BRANCH_TREE_FILENAME,
            f"{ACTIVE_HISTORY_FILENAME}.tmp",
        }
    ):
        raise PermissionError(
            "chat history path must identify a session, not the history root"
        )
    return _validate_history_storage_target(candidate)
