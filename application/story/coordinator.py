"""Feature-gated composition of a compiled story with an active chat session."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from application.chat.history_paths import resolve_history_path_for_project
from config.feature_flags import FeatureFlag
from core.sprite.chat_branch_storage import (
    STORY_SESSION_FILENAME,
    chat_history_session_dir,
)
from core.story import StoryCompiler, StoryRuntime
from sdk.path_utils import safe_existing_path

from .persistence import JsonGlobalStoryProgressStore, JsonStorySessionRepository
from .project_loader import load_story_project
from .session import StorySession


def start_or_recover_story_session(
    state: Any,
    story_path: str | Path,
    *,
    command_id: str,
) -> StorySession:
    """Attach one story to the current chat without changing legacy storage."""
    flags = state.config_manager.feature_flags
    flags.require(FeatureFlag.STORY_SYSTEM)
    root = Path(state.project_root_dir).resolve(strict=False)
    resolved_story_path = safe_existing_path(
        story_path,
        roots=(root,),
        field="story path",
    )
    history_path = resolve_history_path_for_project(
        state,
        state.chat_session.get("historyPath"),
    )
    if str(history_path).startswith("\\\\"):
        raise ValueError("story sessions do not support UNC history storage")

    program = StoryCompiler().compile(load_story_project(resolved_story_path))
    runtime = StoryRuntime(program)
    repository = JsonStorySessionRepository(chat_history_session_dir(history_path))
    global_store = JsonGlobalStoryProgressStore(
        Path(state.history_dir).resolve(strict=False) / ".story-global"
    )
    if repository.load() is None:
        session = StorySession.create(
            runtime,
            flags,
            command_id=command_id,
            repository=repository,
            global_store=global_store,
        )
    else:
        session = StorySession.recover(
            runtime,
            flags,
            repository=repository,
            global_store=global_store,
        )
    session.owner_history_path = str(Path(history_path).resolve(strict=False))
    state.story_session = session
    return session


def bound_story_session(state: Any) -> StorySession | None:
    config_manager = getattr(state, "config_manager", None)
    flags = getattr(config_manager, "feature_flags", None)
    session = getattr(state, "story_session", None)
    if flags is None or session is None:
        return None
    if not flags.is_enabled(FeatureFlag.STORY_SYSTEM):
        return None
    owner = str(getattr(session, "owner_history_path", "") or "").strip()
    if not owner:
        return session
    current = str(getattr(state, "chat_session", {}).get("historyPath") or "").strip()
    if not current:
        return None
    try:
        if Path(owner).resolve(strict=False) != Path(current).resolve(strict=False):
            return None
    except OSError:
        return None
    return session


def story_snapshot_patch(state: Any) -> dict[str, Any]:
    session = bound_story_session(state)
    if session is None:
        return {}
    return session.chat_snapshot()


def clear_story_session(state: Any) -> None:
    setattr(state, "story_session", None)


def discard_story_session_storage(history_path: str | Path) -> None:
    path = chat_history_session_dir(history_path) / STORY_SESSION_FILENAME
    path.unlink(missing_ok=True)


def release_unbound_story_session(state: Any, history_path: str | Path) -> None:
    session = getattr(state, "story_session", None)
    if session is None:
        return
    owner = str(getattr(session, "owner_history_path", "") or "").strip()
    if not owner:
        return
    try:
        if Path(owner).resolve(strict=False) != Path(history_path).resolve(strict=False):
            clear_story_session(state)
    except OSError:
        clear_story_session(state)


def publish_story_transition(
    state: Any,
    patch: dict[str, Any],
    *,
    history_entries: list[dict[str, Any]] | None = None,
    presentation_events: tuple[Any, ...] = (),
) -> None:
    session_id = str(getattr(state, "chat_session", {}).get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)
    if not session_id or chat_stream is None:
        return
    events: list[dict[str, Any]] = []
    if history_entries is not None:
        events.append(
            {
                "type": "history.replace",
                "entries": [dict(item) for item in history_entries],
            }
        )
    story = patch.get("story")
    if isinstance(story, dict):
        events.append({"type": "story.state.replace", "story": dict(story)})
    options = patch.get("options")
    if isinstance(options, list):
        events.append({"type": "options.show", "options": list(options)})
    for item in presentation_events:
        if isinstance(item, dict):
            events.append(dict(item))
    publish = getattr(chat_stream, "publish_event", None)
    published_any = False
    if callable(publish):
        for event in events:
            if publish(session_id, event):
                published_any = True
    update = getattr(chat_stream, "update_session_snapshot", None)
    if not callable(update):
        return
    snapshot_patch = dict(patch)
    if history_entries is not None:
        snapshot_patch["historyEntries"] = [dict(item) for item in history_entries]
    if not published_any:
        get_snapshot = getattr(chat_stream, "get_snapshot", None)
        current = get_snapshot(session_id) if callable(get_snapshot) else None
        try:
            current_seq = int((current or {}).get("eventSeq") or 0)
        except (TypeError, ValueError):
            current_seq = 0
        snapshot_patch["eventSeq"] = current_seq + max(1, len(events) or 1)
    update(session_id, snapshot_patch)
