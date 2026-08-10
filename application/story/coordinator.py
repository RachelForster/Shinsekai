"""Feature-gated composition of a compiled story with an active chat session."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from application.chat.history_paths import resolve_history_path_for_project
from config.feature_flags import FeatureFlag
from core.sprite.chat_branch_storage import chat_history_session_dir
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
    state.story_session = session
    return session


def story_snapshot_patch(state: Any) -> dict[str, Any]:
    config_manager = getattr(state, "config_manager", None)
    flags = getattr(config_manager, "feature_flags", None)
    session = getattr(state, "story_session", None)
    if flags is None or session is None:
        return {}
    if not flags.is_enabled(FeatureFlag.STORY_SYSTEM):
        return {}
    return session.chat_snapshot()
