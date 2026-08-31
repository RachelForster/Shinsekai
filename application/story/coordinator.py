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

from .characters import (
    CharacterImportTokenStore,
    CharacterResourceManager,
    CharacterSourceResolver,
    ConfigCharacterLibrary,
    StoryCastApplicationService,
)
from .persistence import JsonGlobalStoryProgressStore, JsonStorySessionRepository
from .project_loader import load_story_project
from .session import StorySession
from .scene import ConfigSceneModel, SceneOrchestrator


def apply_story_resource_bindings(
    state: Any, bindings: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Copy catalog-validated opening media onto the live chat session."""
    if not bindings:
        return {}
    background = _binding_text(
        bindings, "openingBackground", "background", "backgroundId"
    )
    if not background:
        return {}
    chat_session = dict(getattr(state, "chat_session", {}) or {})
    chat_session["backgroundName"] = background
    state.chat_session = chat_session
    background_path = ""
    config_manager = getattr(state, "config_manager", None)
    getter = getattr(config_manager, "get_background_by_name", None)
    if callable(getter):
        record = getter(background)
        sprites = getattr(record, "sprites", None) if record is not None else None
        if sprites:
            sprite = sprites[0]
            background_path = str(
                sprite.path if hasattr(sprite, "path") else sprite.get("path", "")
            )
    return {"backgroundName": background, "backgroundPath": background_path}


def _binding_text(bindings: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = bindings.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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
    state.story_media_patch = apply_story_resource_bindings(
        state, project.metadata.resource_bindings
    )
    story_root = (
        resolved_story_path
        if resolved_story_path.is_dir()
        else resolved_story_path.parent
    )
    import_tokens = getattr(state, "story_import_tokens", None)
    if import_tokens is None:
        import_tokens = CharacterImportTokenStore(flags)
        state.story_import_tokens = import_tokens
    resolver = CharacterSourceResolver(
        flags,
        story_id=program.story_id,
        story_root=story_root,
        local_library=ConfigCharacterLibrary(state.config_manager),
        import_tokens=import_tokens,
        library_root=root,
    )
    cast_service = StoryCastApplicationService(
        flags,
        CharacterResourceManager(
            flags,
            registry=program.character_registry,
            resolver=resolver,
        ),
    )
    repository = JsonStorySessionRepository(chat_history_session_dir(history_path))
    global_store = JsonGlobalStoryProgressStore(
        Path(state.history_dir).resolve(strict=False) / ".story-global"
    )
    recovering = repository.load() is not None
    if not recovering:
        session = StorySession.create(
            runtime,
            flags,
            command_id=command_id,
            repository=repository,
            global_store=global_store,
            cast_plan_preparer=cast_service.prepare,
            cast_plan_committed=cast_service.committed,
            cast_resources_rebuilder=cast_service.rebuild,
        )
    else:
        session = StorySession.recover(
            runtime,
            flags,
            repository=repository,
            global_store=global_store,
            cast_plan_preparer=cast_service.prepare,
            cast_plan_committed=cast_service.committed,
            cast_resources_rebuilder=cast_service.rebuild,
        )
        cast_service.rebuild(
            session.active_branch.state.cast_state.active_character_ids
        )
    session.owner_history_path = str(Path(history_path).resolve(strict=False))
    state.story_session = session
    state.story_cast_service = cast_service
    state.story_scene_service = SceneOrchestrator(
        flags,
        program=program,
        session=session,
        cast_service=cast_service,
        model=ConfigSceneModel(flags, state.config_manager),
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
    return session


def story_snapshot_patch(state: Any) -> dict[str, Any]:
    session = bound_story_session(state)
    if session is None:
        return {}
    patch = session.chat_snapshot()
    patch.update(_approved_resource_patch(state))
    media_patch = getattr(state, "story_media_patch", None)
    if isinstance(media_patch, Mapping):
        patch.update(dict(media_patch))
    return patch


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
    if not _story_system_enabled(state):
        return
    session_id = str(getattr(state, "chat_session", {}).get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)
    if not session_id or chat_stream is None:
        return
    live_patch = dict(patch)
    resource_patch = _approved_resource_patch(state)
    live_patch.update(resource_patch)
    events: list[dict[str, Any]] = []
    if history_entries is not None:
        events.append(
            {
                "type": "history.replace",
                "entries": [dict(item) for item in history_entries],
            }
        )
    story = live_patch.get("story")
    if isinstance(story, dict):
        events.append({"type": "story.state.replace", "story": dict(story)})
    options = live_patch.get("options")
    if isinstance(options, list):
        events.append({"type": "options.show", "options": list(options)})
    events.extend(_story_sprite_events(chat_stream, session_id, resource_patch))
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
    snapshot_patch = dict(live_patch)
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


def _story_system_enabled(state: Any) -> bool:
    flags = getattr(getattr(state, "config_manager", None), "feature_flags", None)
    return flags is not None and flags.is_enabled(FeatureFlag.STORY_SYSTEM)


def _approved_resource_patch(state: Any) -> dict[str, Any]:
    if not _story_system_enabled(state):
        return {}
    cast_service = getattr(state, "story_cast_service", None)
    if cast_service is None:
        return {}
    patch = dict(cast_service.chat_patch())
    sprites = patch.get("sprites")
    if not isinstance(sprites, list):
        return patch
    chat_stream = getattr(state, "chat_stream", None)
    media_url = getattr(chat_stream, "media_url", None)
    approved: list[dict[str, Any]] = []
    for sprite in sprites:
        if not isinstance(sprite, dict):
            continue
        item = dict(sprite)
        path = str(item.get("path") or "").strip()
        if path and callable(media_url):
            item["path"] = str(media_url(path) or path)
        elif path:
            approve = getattr(chat_stream, "approve_external_media_path", None)
            if callable(approve):
                approve(path)
        approved.append(item)
    if approved:
        patch["sprites"] = approved
    return patch


def _story_sprite_events(
    chat_stream: Any,
    session_id: str,
    resource_patch: Mapping[str, Any],
) -> list[dict[str, Any]]:
    next_sprites = [
        dict(item)
        for item in resource_patch.get("sprites") or []
        if isinstance(item, dict)
    ]
    get_snapshot = getattr(chat_stream, "get_snapshot", None)
    current = get_snapshot(session_id) if callable(get_snapshot) else None
    previous = [
        dict(item)
        for item in (current or {}).get("sprites") or []
        if isinstance(item, dict) and str(item.get("id") or "").startswith("story:")
    ]
    next_ids = {str(item.get("id") or "") for item in next_sprites}
    events: list[dict[str, Any]] = []
    for sprite in previous:
        sprite_id = str(sprite.get("id") or "")
        if sprite_id and sprite_id not in next_ids:
            events.append(
                {
                    "type": "sprite.remove",
                    "characterName": str(sprite.get("characterName") or sprite_id),
                }
            )
    for sprite in next_sprites:
        events.append(
            {
                "type": "sprite.show",
                "characterName": str(sprite.get("characterName") or ""),
                "url": str(sprite.get("path") or ""),
                "scale": sprite.get("scale"),
            }
        )
    return events
