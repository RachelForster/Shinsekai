"""Path policy for chat history stored inside or outside the project root."""

from __future__ import annotations

import ntpath
import os
from pathlib import Path
from typing import Any

from .security import reject_control_chars, safe_project_path


def _state_project_root(state: Any) -> Path:
    raw = (
        str(getattr(state, "project_root_dir", "") or "").strip()
        or os.environ.get("SHINSEKAI_PROJECT_ROOT", "").strip()
        or os.environ.get("EASYAI_PROJECT_ROOT", "").strip()
        or str(Path.cwd())
    )
    return Path(raw).expanduser().resolve(strict=False)


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


def _validate_history_storage_target(path: Path) -> Path:
    """Reject an existing unrelated file/directory as a history storage root."""

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
    raw = str(raw_path or "").strip()
    if not raw:
        raise ValueError("history path is required")
    raw = reject_control_chars(raw, field="history path")

    if _history_path_kind(raw) == "absolute":
        candidate = _absolute_history_path(raw)
    else:
        # Relative history paths are managed by the selected project/data root
        # and never gain external privileges after a containment failure.
        candidate = safe_project_path(raw, root=_state_project_root(state))
    return _validate_history_storage_target(candidate)
