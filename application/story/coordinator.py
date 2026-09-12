"""Feature-gated composition of a compiled story with an active chat session."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from application.chat.history_paths import resolve_history_path_for_project
from config.feature_flags import FeatureFlag
from core.chat_history.storage import (
    STORY_SESSION_FILENAME,
    chat_history_session_dir,
)
from core.story import StoryCompiler, StoryRuntime
from sdk.path_utils import safe_existing_path

from .persistence import JsonGlobalStoryProgressStore, JsonStorySessionRepository
from .project_loader import load_story_project
from .session import StorySession
from .prompt_runtime import BINDING_FILENAME, bind_story_prompt, load_prompt_session


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

    project = load_story_project(resolved_story_path)
    program = StoryCompiler().compile(project)
    runtime = StoryRuntime(program)
    repository = JsonStorySessionRepository(chat_history_session_dir(history_path))
    global_store = JsonGlobalStoryProgressStore(
        Path(state.history_dir).resolve(strict=False) / ".story-global"
    )
    recovering = repository.load() is not None
    if not recovering:
        stream = getattr(state, "chat_stream", None)
        snapshot = (
            stream.get_snapshot(state.chat_session.get("sessionId")) if stream else None
        )
        session = StorySession.create(
            runtime,
            flags,
            command_id=command_id,
            repository=repository,
            global_store=global_store,
            history_entries=(snapshot or {}).get("historyEntries", ()),
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
    state.story_cast_service = None
    state.story_scene_service = None
    state.story_media_patch = None
    bind_story_prompt(
        history_path,
        resolved_story_path,
        root,
        Path(state.history_dir).resolve() / ".story-global",
    )
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
    fresh = load_prompt_session(current, flags)
    if fresh is not None:
        state.story_session = fresh
        return fresh
    return session


def story_snapshot_patch(state: Any) -> dict[str, Any]:
    session = bound_story_session(state)
    if session is None:
        return {}
    # Story state is additive. The normal chat owns options, stats, history,
    # backgrounds and sprites, including all workflow-generated media.
    return {"story": session.chat_snapshot()["story"]}


def clear_story_session(state: Any) -> None:
    session = getattr(state, "story_session", None)
    closer = getattr(session, "close", None)
    if callable(closer):
        closer()
    setattr(state, "story_session", None)
    setattr(state, "story_cast_service", None)
    setattr(state, "story_scene_service", None)
    setattr(state, "story_media_patch", None)


def discard_story_session_storage(history_path: str | Path) -> None:
    path = chat_history_session_dir(history_path) / STORY_SESSION_FILENAME
    path.unlink(missing_ok=True)
    (chat_history_session_dir(history_path) / BINDING_FILENAME).unlink(missing_ok=True)


def release_unbound_story_session(state: Any, history_path: str | Path) -> None:
    session = getattr(state, "story_session", None)
    if session is None:
        return
    owner = str(getattr(session, "owner_history_path", "") or "").strip()
    if not owner:
        return
    try:
        if Path(owner).resolve(strict=False) != Path(history_path).resolve(
            strict=False
        ):
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
    if not _story_system_enabled(state):
        return
    session_id = str(getattr(state, "chat_session", {}).get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)
    if not session_id or chat_stream is None:
        return
    story = patch.get("story")
    if not isinstance(story, Mapping):
        return
    event = {"type": "story.state.replace", "story": dict(story)}
    publish = getattr(chat_stream, "publish_event", None)
    if callable(publish):
        publish(session_id, event)
    update = getattr(chat_stream, "update_session_snapshot", None)
    if callable(update):
        update(session_id, {"story": dict(story)})


def _story_system_enabled(state: Any) -> bool:
    flags = getattr(getattr(state, "config_manager", None), "feature_flags", None)
    return flags is not None and flags.is_enabled(FeatureFlag.STORY_SYSTEM)
