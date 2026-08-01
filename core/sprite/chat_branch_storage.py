from __future__ import annotations

import copy
import json
import os
import re
import stat
import threading
from pathlib import Path
from typing import Any

from sdk.file_transactions import (
    atomic_write_text,
    read_text_without_links,
    remove_empty_directory_without_links,
    remove_file_without_links,
    snapshot_directory_entries_without_links,
)
from core.paths import (
    _metadata_is_link_or_reparse_point,
    path_is_link_or_reparse_point,
    path_is_within,
    project_root,
    resolve_managed_project_path,
    resolve_project_path,
    resolve_project_read_path,
    validate_exact_path_text,
)

ACTIVE_HISTORY_FILENAME = "active.json"
BRANCH_TREE_FILENAME = "branches.json"
BRANCH_TREE_VERSION = 1
_BRANCH_STORAGE_LOCK = threading.RLock()


def _exact_history_path(path: str | Path) -> Path:
    """Preserve a history reference's lexical identity at the storage boundary."""

    raw = validate_exact_path_text(path, field="chat history path")
    return resolve_project_read_path(raw, root=project_root())


def _is_branch_file(path: Path) -> bool:
    return path.name in {ACTIVE_HISTORY_FILENAME, BRANCH_TREE_FILENAME}


def is_legacy_history_file(path: str | Path) -> bool:
    candidate = _exact_history_path(path)
    if candidate.suffix.lower() != ".json" or _is_branch_file(candidate):
        return False
    session_dir = candidate.with_suffix("")
    return candidate.is_file() and not (session_dir / BRANCH_TREE_FILENAME).exists()


def chat_history_session_dir(path: str | Path) -> Path:
    candidate = _exact_history_path(path)
    if candidate.suffix.lower() == ".json":
        if _is_branch_file(candidate):
            return candidate.parent
        return candidate.with_suffix("")
    return candidate


def chat_history_active_path(path: str | Path) -> Path:
    candidate = _exact_history_path(path)
    if is_legacy_history_file(candidate):
        return candidate
    return chat_history_session_dir(candidate) / ACTIVE_HISTORY_FILENAME


def chat_history_branch_tree_path(path: str | Path) -> Path:
    return chat_history_session_dir(path) / BRANCH_TREE_FILENAME


def chat_history_download_path(path: str | Path) -> Path:
    tree_path = chat_history_branch_tree_path(path)
    if tree_path.is_file():
        return tree_path
    return chat_history_active_path(path)


def _history_session_directory_identity(
    path: Path,
) -> os.stat_result | None:
    try:
        _directory, identity, entries = (
            snapshot_directory_entries_without_links(
                path,
                field="chat history session directory",
            )
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return None
    reserved = {
        ACTIVE_HISTORY_FILENAME,
        BRANCH_TREE_FILENAME,
        f"{ACTIVE_HISTORY_FILENAME}.tmp",
    }
    if any(
        child.name in reserved
        and not _metadata_is_link_or_reparse_point(metadata)
        and stat.S_ISREG(metadata.st_mode)
        for child, metadata in entries
    ):
        return identity
    return None


def _looks_like_history_session_dir(path: Path) -> bool:
    return _history_session_directory_identity(path) is not None


def validate_chat_history_removal_target(
    target: str | Path,
    root: str | Path,
) -> Path:
    """Return a resolved strict descendant suitable for destructive actions."""

    raw_root = os.fspath(root)
    raw_target = os.fspath(target)
    try:
        active_project_root = project_root()
        resolved_root = resolve_project_path(raw_root, root=active_project_root)
        unresolved_root = Path(raw_root).expanduser()
        if not unresolved_root.is_absolute():
            unresolved_root = active_project_root / unresolved_root
        if path_is_link_or_reparse_point(unresolved_root):
            raise PermissionError("chat history root must not be a symbolic link")
        project_candidate = resolve_project_path(raw_target, root=active_project_root)
        raw_target_path = Path(raw_target).expanduser()
        if raw_target_path.is_absolute():
            unresolved_target = raw_target_path
        elif path_is_within(project_candidate, resolved_root):
            # Preserve unresolved components for the managed resolver so it
            # can detect an in-boundary symbolic-link hop.
            unresolved_target = active_project_root / raw_target_path
        else:
            # A shorthand such as ``session`` is relative to the explicitly
            # declared history collection, never to process cwd.
            resolve_project_path(raw_target, root=resolved_root)
            unresolved_target = resolved_root / raw_target_path
        resolved_target = resolve_managed_project_path(
            unresolved_target,
            root=resolved_root,
        )
    except PermissionError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("chat history removal target could not be resolved") from exc
    removal_container = (
        resolved_target.parent
        if _is_branch_file(resolved_target)
        else resolved_target
    )
    if removal_container == resolved_root:
        raise PermissionError("refusing to remove the chat history collection root")
    return resolved_target


def remove_chat_history_storage(
    path: str | Path,
    *,
    root: str | Path | None = None,
) -> None:
    """Remove one history session, optionally enforcing its managed boundary.

    A legacy ``session.json`` may have a companion ``session/`` branch store.
    Only remove that companion when it actually has the reserved history
    layout; an unrelated same-named directory must survive.
    """

    managed_root = Path(root) if root is not None else None
    candidate = (
        validate_chat_history_removal_target(path, managed_root)
        if managed_root is not None
        else _exact_history_path(path)
    )
    with _BRANCH_STORAGE_LOCK:
        default_history_root = resolve_managed_project_path(
            "data/chat_history",
            root=project_root(),
        )
        managed = managed_root is not None or path_is_within(
            candidate,
            default_history_root,
        )
        removal_container = candidate.parent if _is_branch_file(candidate) else candidate
        if managed and managed_root is None and removal_container == default_history_root:
            raise PermissionError(
                "refusing to remove the chat history collection root"
            )
        _remove_reserved_history_storage(candidate)


def _remove_regular_history_file(path: Path) -> None:
    """Remove one reserved file without following or deleting an alias."""

    try:
        identity = path.lstat()
    except FileNotFoundError:
        return
    if _metadata_is_link_or_reparse_point(identity):
        raise PermissionError(f"chat history file must not be a symbolic link: {path}")
    if not stat.S_ISREG(identity.st_mode):
        raise PermissionError(f"chat history file has an unsafe type: {path}")
    remove_file_without_links(path, expected_identity=identity)


def _remove_reserved_history_storage(candidate: Path) -> None:
    """Clear reserved chat files without treating a directory as fully owned."""

    if candidate.suffix.lower() == ".json" and not _is_branch_file(candidate):
        file_targets = (candidate, Path(f"{candidate}.tmp"))
        directory_targets = (candidate.with_suffix(""),)
    elif _is_branch_file(candidate):
        file_targets = ()
        directory_targets = (candidate.parent,)
    else:
        file_targets = ()
        directory_targets = (chat_history_session_dir(candidate),)

    for directory in directory_targets:
        try:
            directory_identity = directory.lstat()
        except FileNotFoundError:
            continue
        if (
            _metadata_is_link_or_reparse_point(directory_identity)
            or not stat.S_ISDIR(directory_identity.st_mode)
        ):
            raise PermissionError(
                f"chat history session must be a regular directory: {directory}"
            )
        # Metadata goes first and the authoritative active history last. If a
        # locked file aborts cleanup, the readable conversation stays intact.
        for name in (
            BRANCH_TREE_FILENAME,
            f"{ACTIVE_HISTORY_FILENAME}.tmp",
            ACTIVE_HISTORY_FILENAME,
        ):
            _remove_regular_history_file(directory / name)
        try:
            remove_empty_directory_without_links(
                directory,
                expected_identity=directory_identity,
            )
        except OSError:
            # Unrelated external content deliberately keeps the directory alive.
            pass

    for target in file_targets:
        _remove_regular_history_file(target)


def sanitize_branch_id(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip(".-")
    return slug[:80] or "branch"


def _copy_jsonable_list(value: Any) -> list[Any]:
    return copy.deepcopy(value) if isinstance(value, list) else []


def normalize_branch_state(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    raw_branches = raw.get("branches")
    if isinstance(raw_branches, dict):
        branch_items = raw_branches.values()
    elif isinstance(raw_branches, list):
        branch_items = raw_branches
    else:
        branch_items = []

    branches: dict[str, dict[str, Any]] = {}
    max_counter = 1
    for item in branch_items:
        if not isinstance(item, dict):
            continue
        branch_id = str(item.get("id") or "").strip()
        if not branch_id:
            continue
        match = re.fullmatch(r"branch-(\d+)", branch_id)
        if match:
            max_counter = max(max_counter, int(match.group(1)))
        branches[branch_id] = {
            "createdAt": item.get("createdAt"),
            "forkedFromEntryId": str(item.get("forkedFromEntryId") or ""),
            "forkedFromText": str(item.get("forkedFromText") or ""),
            "history": _copy_jsonable_list(item.get("history")),
            "id": branch_id,
            "label": str(item.get("label") or branch_id),
            "messages": _copy_jsonable_list(item.get("messages")),
            "parentId": item.get("parentId") if item.get("parentId") else None,
            "updatedAt": item.get("updatedAt"),
        }

    if not branches:
        return None
    active = str(raw.get("activeBranchId") or raw.get("active") or "").strip()
    if active not in branches:
        active = "main" if "main" in branches else next(iter(branches))
    try:
        counter = max(max_counter, int(raw.get("counter") or 1))
    except (TypeError, ValueError):
        counter = max_counter
    return {"active": active, "counter": counter, "branches": branches}


def load_branch_state(path: str | Path) -> dict[str, Any] | None:
    tree_path = chat_history_branch_tree_path(path)
    if not tree_path.is_file():
        return None
    try:
        return normalize_branch_state(json.loads(read_text_without_links(tree_path)))
    except (OSError, json.JSONDecodeError):
        return None


def reconcile_active_branch_state(
    branch_state: dict[str, Any],
    loaded_messages: list[Any],
    loaded_history: list[Any],
    *,
    active_history_present: bool = False,
) -> tuple[list[Any], list[Any]]:
    """Reconcile branch metadata with the crash-recoverable active history.

    ``active.json`` and its incremental ``.tmp`` file are loaded before the
    branch tree. When they contain data, they are newer and must not be
    overwritten by a stale ``branches.json`` left behind by an interrupted
    shutdown.
    """

    branches = branch_state.get("branches")
    if not isinstance(branches, dict):
        return copy.deepcopy(loaded_messages), copy.deepcopy(loaded_history)
    active_id = str(branch_state.get("active") or "").strip()
    active_branch = branches.get(active_id)
    if not isinstance(active_branch, dict):
        return copy.deepcopy(loaded_messages), copy.deepcopy(loaded_history)

    # An existing empty active.json is an explicit cleared state, not a missing
    # snapshot. This prevents stale branch metadata from resurrecting history
    # after a clear whose metadata cleanup was interrupted.
    if active_history_present or loaded_messages or loaded_history:
        active_branch["messages"] = copy.deepcopy(loaded_messages)
        active_branch["history"] = copy.deepcopy(loaded_history)
        return copy.deepcopy(loaded_messages), copy.deepcopy(loaded_history)

    return (
        _copy_jsonable_list(active_branch.get("messages")),
        _copy_jsonable_list(active_branch.get("history")),
    )


def branch_state_payload(branch_state: dict[str, Any]) -> dict[str, Any]:
    branches = branch_state.get("branches") if isinstance(branch_state, dict) else {}
    if not isinstance(branches, dict):
        branches = {}
    return {
        "activeBranchId": str(branch_state.get("active") or "main"),
        "branches": copy.deepcopy(branches),
        "counter": int(branch_state.get("counter") or 1),
        "version": BRANCH_TREE_VERSION,
    }


def save_branch_state(path: str | Path, branch_state: dict[str, Any]) -> Path:
    tree_path = chat_history_branch_tree_path(path)
    with _BRANCH_STORAGE_LOCK:
        if path_is_link_or_reparse_point(tree_path.parent):
            raise PermissionError("chat history session must not be a symbolic link")
        tree_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            tree_path,
            json.dumps(
                branch_state_payload(branch_state),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
    return tree_path
