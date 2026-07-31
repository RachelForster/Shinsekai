"""Project-root-bound persistence for the React template launch session."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sdk.file_transactions import (
    atomic_write_text,
    capture_directory_identity,
    read_text_snapshot_without_links,
    require_directory_identity,
)
from sdk.path_contract import (
    managed_child_path,
    managed_project_storage,
    project_root as runtime_project_root,
    require_directory_without_links,
    resolve_managed_project_path,
    resolve_project_path,
)

from sdk.path_references import make_path_reference, path_reference_value

_SESSION_VERSION = 1
_PATH_CONTRACT_VERSION = 1
_SESSION_FILENAME = "template_tab_last_launch.json"
_PATH_FIELD_CONTRACTS = {
    "history_file": {
        "legacy_project_prefixes": (("data", "chat_history"),),
        "resource_prefixes": (),
    },
    "init_sprite_path": {
        "legacy_project_prefixes": (("data", "sprite"),),
        "resource_prefixes": (("assets",),),
    },
    "workflow_path": {
        "legacy_project_prefixes": (
            ("data", "workflows"),
            ("test", "e2e"),
        ),
        "resource_prefixes": (("assets", "system", "workflow"),),
    },
}


def _authoritative_root(project_root: str | Path | None) -> Path:
    return (
        runtime_project_root()
        if project_root is None
        else resolve_project_path(".", root=project_root)
    )


def template_session_file(
    template_dir_path: str | Path,
    *,
    project_root: str | Path | None = None,
) -> Path:
    """Return the fixed session file without inferring ownership from its input."""

    root = _authoritative_root(project_root)
    # Validate the context value even though storage has a fixed location.
    # A stale absolute path from a previous installation must not become a
    # second data root merely because its parent happens to contain ``data``.
    resolve_managed_project_path(template_dir_path, root=root)
    config_root = managed_project_storage("data/config", root=root)
    return managed_child_path(
        config_root,
        _SESSION_FILENAME,
        field="template session filename",
    )


def _normalize_session_path_fields(
    data: dict[str, Any],
    *,
    project_root: Path,
    prefer_stored_references: bool,
    recover_legacy_absolute: bool,
) -> dict[str, Any]:
    normalized = dict(data)
    stored_references = data.get("path_refs")
    stored_references = (
        stored_references if isinstance(stored_references, dict) else {}
    )
    references: dict[str, dict[str, str]] = {}
    for field, contract in _PATH_FIELD_CONTRACTS.items():
        has_stored_reference = (
            prefer_stored_references and field in stored_references
        )
        reference = (
            stored_references.get(field) if has_stored_reference else None
        )
        value = path_reference_value(
            reference,
            project_prefixes=contract["legacy_project_prefixes"],
            resource_prefixes=contract["resource_prefixes"],
        )
        if not has_stored_reference:
            raw = str(data.get(field) or "")
            reference = (
                make_path_reference(
                    raw,
                    project_root,
                    legacy_project_prefixes=contract[
                        "legacy_project_prefixes"
                    ],
                    resource_prefixes=contract["resource_prefixes"],
                    recover_legacy_absolute=recover_legacy_absolute,
                )
                if raw
                else None
            )
            value = path_reference_value(
                reference,
                project_prefixes=contract["legacy_project_prefixes"],
                resource_prefixes=contract["resource_prefixes"],
            )
        normalized[field] = value or ""
        if isinstance(reference, dict) and value is not None:
            scope = str(reference["scope"])
            references[field] = {
                "scope": scope,
                "path": (
                    value
                    if scope.strip().lower() in {"project", "resource"}
                    else str(reference["path"])
                ),
            }
    normalized["path_refs"] = references
    normalized["path_contract_version"] = _PATH_CONTRACT_VERSION
    return normalized


def _has_current_path_contract(data: dict[str, Any]) -> bool:
    value = data.get("path_contract_version")
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= _PATH_CONTRACT_VERSION
    )


def load_template_session(
    template_dir_path: str | Path,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any] | None:
    path = template_session_file(
        template_dir_path,
        project_root=project_root,
    )
    try:
        parent, parent_identity = capture_directory_identity(
            path.parent,
            field="template session directory",
        )
        raw, _file_identity = read_text_snapshot_without_links(
            path,
            expected_parent_identity=parent_identity,
        )
        require_directory_identity(
            parent,
            parent_identity,
            field="template session directory",
        )
        data = json.loads(raw)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != _SESSION_VERSION:
        return None
    recover_legacy_absolute = not _has_current_path_contract(data)
    normalized = _normalize_session_path_fields(
        data,
        project_root=_authoritative_root(project_root),
        prefer_stored_references=True,
        recover_legacy_absolute=recover_legacy_absolute,
    )
    if recover_legacy_absolute:
        atomic_write_text(
            path,
            json.dumps(normalized, ensure_ascii=False, indent=2),
            expected_parent_identity=parent_identity,
        )
        require_directory_identity(
            parent,
            parent_identity,
            field="template session directory",
        )
    return normalized


def save_template_session(
    template_dir_path: str | Path,
    data: dict[str, Any],
    *,
    project_root: str | Path | None = None,
) -> None:
    path = template_session_file(
        template_dir_path,
        project_root=project_root,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    parent, parent_identity = capture_directory_identity(
        require_directory_without_links(
            path.parent,
            field="template session directory",
        ),
        field="template session directory",
    )
    payload = {
        "version": _SESSION_VERSION,
        **_normalize_session_path_fields(
            data,
            project_root=_authoritative_root(project_root),
            prefer_stored_references=False,
            recover_legacy_absolute=False,
        ),
    }
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2),
        expected_parent_identity=parent_identity,
    )
    require_directory_identity(
        parent,
        parent_identity,
        field="template session directory",
    )


__all__ = [
    "load_template_session",
    "save_template_session",
    "template_session_file",
]
