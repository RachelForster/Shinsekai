"""Chat-history branch state and session-path persistence helpers."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.chat_history.sqlite_session_store import (
    HISTORY_DB_FILENAME,
    canonical_session_id_for_dir,
    close_session_store_for_dir,
    durable_history_messages,
    legacy_journal_overlap,
    open_session_store_for_dir,
    peek_open_session_store_for_dir,
    read_full_raw_messages_readonly,
    read_legacy_history_journal,
    register_session_db_directory,
)
from sdk.adapters.session import ConversationSessionPort
from sdk.file_io import durable_rename

ACTIVE_HISTORY_FILENAME = "active.json"
HISTORY_EXPORT_FILENAME = "shinsekai-chat-export.json"
BRANCH_TREE_FILENAME = "branches.json"
BRANCH_TREE_TEMP_PREFIX = ".branches-"
STORY_SESSION_FILENAME = "story-v2.json"
BEHAVIOR_TURN_JOURNAL_FILENAME = "behavior-turn-journal.json"
BEHAVIOR_TURN_JOURNAL_TEMP_PREFIX = ".behavior-journal-"
VOICE_ARCHIVE_DIRECTORY = "audio"
VOICE_INDEX_FILENAME = "index.json"
VOICE_INDEX_TEMP_PREFIX = ".voice-index-"
BRANCH_TREE_VERSION = 1


def _is_branch_file(path: Path) -> bool:
    return path.name in {ACTIVE_HISTORY_FILENAME, BRANCH_TREE_FILENAME}


def is_legacy_history_file(path: str | Path) -> bool:
    candidate = Path(path)
    if candidate.suffix.lower() != ".json" or _is_branch_file(candidate):
        return False
    session_dir = candidate.with_suffix("")
    return candidate.is_file() and not (session_dir / BRANCH_TREE_FILENAME).exists()


def chat_history_session_dir(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.suffix.lower() == ".json":
        if _is_branch_file(candidate):
            return candidate.parent
        return candidate.with_suffix("")
    return candidate


def chat_history_active_path(path: str | Path) -> Path:
    candidate = Path(path)
    if is_legacy_history_file(candidate):
        return candidate
    return chat_history_session_dir(candidate) / ACTIVE_HISTORY_FILENAME


def chat_history_branch_tree_path(path: str | Path) -> Path:
    return chat_history_session_dir(path) / BRANCH_TREE_FILENAME


def chat_history_db_path(path: str | Path) -> Path:
    return chat_history_session_dir(path) / HISTORY_DB_FILENAME


def chat_history_behavior_journal_path(path: str | Path) -> Path:
    return chat_history_session_dir(path) / BEHAVIOR_TURN_JOURNAL_FILENAME


def session_id_for_history_path(path: str | Path) -> str:
    if not str(path or "").strip():
        return ""
    return canonical_session_id_for_dir(chat_history_session_dir(path))


def register_session_history_path(path: str | Path) -> None:
    register_session_db_directory(chat_history_session_dir(path))


def open_session_store(path: str | Path) -> ConversationSessionPort:
    return open_session_store_for_dir(chat_history_session_dir(path))


def peek_open_session_store(path: str | Path) -> ConversationSessionPort | None:
    if not str(path or "").strip():
        return None
    return peek_open_session_store_for_dir(chat_history_session_dir(path))


def close_session_store(path: str | Path) -> None:
    if not str(path or "").strip():
        return
    close_session_store_for_dir(chat_history_session_dir(path))


def legacy_active_history_branch(path: str | Path) -> str:
    """Resolve the one timeline retained from old conversation-tree saves."""
    if not str(path or "").strip():
        return "main"
    tree_path = chat_history_branch_tree_path(path)
    try:
        stat = tree_path.stat()
    except OSError:
        return "main"
    return _legacy_active_history_branch(tree_path, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=32)
def _legacy_active_history_branch(tree_path: Path, _mtime: int, _size: int) -> str:
    state = load_branch_state(tree_path)
    return str(state["active"]) if state else "main"


def chat_history_download_path(path: str | Path) -> Path:
    return chat_history_session_dir(path) / HISTORY_EXPORT_FILENAME


def read_active_chat_history(
    path: str | Path, *, read_snapshot: Callable[[Path], Any] | None = None,
) -> list[Any]:
    """Read the active timeline without migrating or rewriting its files."""
    active = chat_history_active_path(path)
    branch = legacy_active_history_branch(path)
    try:
        if not active.is_file():
            legacy = load_branch_state(path)
            snapshot = legacy["branches"][branch]["messages"] if legacy else []
        elif read_snapshot is not None:
            snapshot = read_snapshot(active)
        else:
            snapshot = json.loads(active.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snapshot = []
    snapshot = snapshot if isinstance(snapshot, list) else []
    durable = read_full_raw_messages_readonly(chat_history_session_dir(path), branch_id=branch)
    messages = durable if durable is not None else snapshot
    try:
        pending = durable_history_messages(read_legacy_history_journal(Path(str(active) + ".tmp")))
    except (OSError, ValueError):
        return messages
    existing = durable_history_messages(messages)
    overlap = legacy_journal_overlap(existing, pending, durable_history_messages(snapshot))
    return messages + pending[overlap:]


def write_active_history_snapshot(path: Path, messages: Sequence[Any]) -> None:
    """Replace the JSON snapshot atomically; SQLite remains the journal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".history-snapshot-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(messages, file, ensure_ascii=False, indent=4)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def chat_history_storage_files(path: str | Path) -> tuple[Path, ...]:
    """Enumerate owned files, keeping migrated legacy aliases last."""
    candidate = Path(path)
    directory = chat_history_session_dir(candidate)
    files = tuple(directory / name for name in (
        BRANCH_TREE_FILENAME,
        f"{HISTORY_DB_FILENAME}-shm",
        f"{HISTORY_DB_FILENAME}-wal",
        HISTORY_DB_FILENAME,
        f"{ACTIVE_HISTORY_FILENAME}.tmp",
        ACTIVE_HISTORY_FILENAME,
        HISTORY_EXPORT_FILENAME,
        STORY_SESSION_FILENAME,
        BEHAVIOR_TURN_JOURNAL_FILENAME,
    ))
    if directory.is_dir():
        files += tuple(
            file
            for file in directory.iterdir()
            if (file.is_file() or file.is_symlink())
            and file.suffix == ".tmp"
            and (
                file.name.startswith(BRANCH_TREE_TEMP_PREFIX)
                or file.name.startswith(BEHAVIOR_TURN_JOURNAL_TEMP_PREFIX)
            )
        )
    for audio_dir in _voice_storage_directories(directory):
        files += tuple(
            file for file in audio_dir.iterdir()
            if (file.is_file() or file.is_symlink()) and (
                re.fullmatch(r"[0-9a-f]{32}-\d+(?:\.[a-z0-9]+)?", file.name)
                or (audio_dir.name == VOICE_ARCHIVE_DIRECTORY and (
                    file.name == VOICE_INDEX_FILENAME
                    or (file.name.startswith(VOICE_INDEX_TEMP_PREFIX) and file.suffix == ".tmp")
                ))
            )
        )
    replay = directory / "replay"
    if replay.is_dir() and replay.resolve().is_relative_to(directory.resolve()):
        files += tuple(file for file in replay.iterdir()
                       if (file.is_file() or file.is_symlink()) and (
                           re.fullmatch(r"[0-9a-f]{64}\.(?:frame\.json|voice\.json|wav)", file.name)
                           or re.fullmatch(r"\.replay-[\w-]+\.tmp", file.name)))
    if candidate.suffix.lower() == ".json" and not _is_branch_file(candidate):
        files += (candidate, Path(str(candidate) + ".tmp"))
    return files


def _voice_storage_directories(directory: Path) -> tuple[Path, ...]:
    audio = directory / VOICE_ARCHIVE_DIRECTORY
    return tuple(
        folder for folder in (audio / "save", audio)
        if folder.is_dir() and folder.resolve().is_relative_to(directory.resolve())
    )


def prune_chat_history_storage(path: str | Path) -> None:
    """Remove empty owned directories, preserving unrelated and external files."""
    directory = chat_history_session_dir(path)
    for folder in (*_voice_storage_directories(directory), directory / "replay", directory):
        try:
            folder.rmdir()
        except OSError:
            pass


def remove_chat_history_storage(path: str | Path) -> None:
    # A history directory is not an ownership boundary. Remove only files
    # created by chat and story session storage, then remove the directory
    # if it is empty. Never recursively delete unrelated content from an
    # external directory.
    # Legacy aliases are removed last. If branch metadata is locked, the
    # authoritative active history remains intact and the clear is reported as
    # failed instead of leaving a partially-cleared session.
    close_session_store(path)
    for target in chat_history_storage_files(path):
        target.unlink(missing_ok=True)
    prune_chat_history_storage(path)


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
        with tree_path.open(encoding="utf-8") as file:
            return normalize_branch_state(json.load(file))
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
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=BRANCH_TREE_TEMP_PREFIX, suffix=".tmp", dir=tree_path.parent
    )
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(
                branch_state_payload(branch_state),
                file,
                ensure_ascii=False,
                indent=2,
            )
            file.flush()
            os.fsync(file.fileno())
        durable_rename(temp_path, tree_path, replace=True)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return tree_path
