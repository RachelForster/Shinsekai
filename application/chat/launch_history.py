"""Select and persist the chat-history target for a launch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from application.chat.history_paths import (
    is_unc_history_path,
    resolve_history_path_for_project,
)
from application.chat.templates import (
    _history_id_from_scenario,
    _scenario_from_template_like,
)
from core.chat_history.storage import (
    ACTIVE_HISTORY_FILENAME,
    BRANCH_TREE_FILENAME,
)


@dataclass(frozen=True)
class ChatHistoryLaunchTarget:
    """Resolved history paths for one chat launch."""

    history_path: Path
    previous_history_path: Path
    starts_fresh: bool


def _resolve_history_file(state: Any, raw_path: str | Path) -> Path:
    return resolve_history_path_for_project(state, raw_path)


def resolve_chat_history_path(
    state: Any,
    payload: dict[str, Any],
    template: dict[str, Any],
) -> Path:
    """Resolve an explicit history path or the stable default for a template."""

    raw = str(payload.get("historyPath") or "").strip()
    if raw:
        path = _resolve_history_file(state, raw)
        if path.name in {ACTIVE_HISTORY_FILENAME, BRANCH_TREE_FILENAME}:
            return _resolve_history_file(state, path.parent)
        if (
            path.suffix.lower() == ".json"
            and not is_unc_history_path(path)
            and not path.is_file()
        ):
            return _resolve_history_file(state, path.with_suffix(""))
        return path

    characters = payload.get("characters")
    if not isinstance(characters, list):
        characters = template.get("selectedCharacters")
    scenario = _scenario_from_template_like(template)
    template_hash = _history_id_from_scenario(scenario, characters)
    return _resolve_history_file(state, Path(state.history_dir) / template_hash)


def _new_history_instance_id() -> str:
    readable_time = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{readable_time}-{uuid4().hex[:8]}"


def plan_chat_history_launch(
    state: Any,
    payload: dict[str, Any],
    template: dict[str, Any],
    *,
    start_fresh: bool,
) -> ChatHistoryLaunchTarget:
    """Choose the existing history or a new managed sibling for quick restart."""

    previous_path = resolve_chat_history_path(state, payload, template)
    if not start_fresh:
        return ChatHistoryLaunchTarget(
            history_path=previous_path,
            previous_history_path=previous_path,
            starts_fresh=False,
        )

    default_path = resolve_chat_history_path(
        state,
        {**payload, "historyPath": ""},
        template,
    )
    history_path = default_path.with_name(
        f"{default_path.name}-{_new_history_instance_id()}"
    )
    return ChatHistoryLaunchTarget(
        history_path=_resolve_history_file(state, history_path),
        previous_history_path=previous_path,
        starts_fresh=True,
    )


def persist_confirmed_history_path(state: Any, history_path: str | Path) -> bool:
    """Persist the backend-selected path so resume-last uses the launched history."""

    from application.chat.session_store import (
        load_template_session,
        save_template_session,
    )

    stored = load_template_session(state.template_dir_path)
    if stored is None:
        return True
    updated = dict(stored)
    updated["history_file"] = Path(history_path).as_posix()
    try:
        save_template_session(state.template_dir_path, updated)
    except OSError:
        return False
    return True
