from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

ACTIVE_HISTORY_FILENAME = "active.json"
BRANCH_TREE_FILENAME = "branches.json"
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


def chat_history_download_path(path: str | Path) -> Path:
    tree_path = chat_history_branch_tree_path(path)
    if tree_path.is_file():
        return tree_path
    return chat_history_active_path(path)


def remove_chat_history_storage(path: str | Path) -> None:
    candidate = Path(path)
    if candidate.suffix.lower() == ".json" and not _is_branch_file(candidate):
        file_targets = [candidate, Path(str(candidate) + ".tmp")]
        directory_targets = [candidate.with_suffix("")]
    elif _is_branch_file(candidate):
        file_targets = []
        directory_targets = [candidate.parent]
    else:
        file_targets = []
        directory_targets = [chat_history_session_dir(candidate)]

    # A history directory is not an ownership boundary. Remove only files
    # created by chat storage, then remove the directory if it is empty.
    # Never recursively delete unrelated content from an external directory.
    for directory in directory_targets:
        for name in (
            BRANCH_TREE_FILENAME,
            f"{ACTIVE_HISTORY_FILENAME}.tmp",
            ACTIVE_HISTORY_FILENAME,
        ):
            target = directory / name
            target.unlink(missing_ok=True)
        try:
            directory.rmdir()
        except OSError:
            pass

    # Legacy aliases are removed last. If branch metadata is locked, the
    # authoritative active history remains intact and the clear is reported as
    # failed instead of leaving a partially-cleared session.
    for target in file_targets:
        target.unlink(missing_ok=True)


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
    with tree_path.open("w", encoding="utf-8") as file:
        json.dump(branch_state_payload(branch_state), file, ensure_ascii=False, indent=2)
    return tree_path
