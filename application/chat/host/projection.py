"""Build renderer snapshots and configuration projections without owning a child."""

from __future__ import annotations
from typing import Any
from pathlib import Path
from collections.abc import Callable
import json
from application.chat.presentation.user_display import sanitize_user_display_name
from core.chat_history.text import DEFAULT_USER_DISPLAY_NAME
from config.character_assets import get_character_assets
from application.chat.presentation.character_visual import resolve_character_visual

TRANSPARENT_BACKGROUND_NAME = "透明场景"
_TRANSPARENT_BACKGROUND_ALIAS = "透明背景"


def _is_transparent_background_name(name: str | None) -> bool:
    value = str(name or "").strip()
    return not value or value in {
        TRANSPARENT_BACKGROUND_NAME,
        _TRANSPARENT_BACKGROUND_ALIAS,
    }


def _chat_runtime_mode(_state: Any) -> str:
    """Return the only supported chat UI runtime."""
    return "react"


def _chat_experimental_features(state: Any) -> dict[str, bool]:
    config_manager = getattr(state, "config_manager", None)
    system_config = getattr(
        getattr(config_manager, "config", None), "system_config", None
    )
    return {
        "conversationTree": bool(
            getattr(system_config, "react_chat_flowchart_experimental_enabled", False)
        ),
        "forkHistory": bool(
            getattr(system_config, "react_chat_fork_experimental_enabled", False)
        ),
    }


def _chat_turn_options(state: Any) -> dict[str, Any]:
    config_manager = getattr(state, "config_manager", None)
    api_config = getattr(getattr(config_manager, "config", None), "api_config", None)
    return {
        "interruptEnabled": bool(getattr(api_config, "interrupt_enabled", True)),
        "batchEnabled": bool(getattr(api_config, "is_batch_input_enabled", False)),
        "batchIdleSeconds": float(
            getattr(api_config, "batch_input_timeout", 5.0) or 5.0
        ),
    }


def _chat_runtime_closing(state: Any) -> bool:
    lock = getattr(state, "chat_runtime_lock", None)
    if lock is None:
        return bool(getattr(state, "chat_runtime_closing", False))
    with lock:
        return bool(getattr(state, "chat_runtime_closing", False))


def _set_chat_runtime_closing(state: Any, closing: bool) -> None:
    lock = getattr(state, "chat_runtime_lock", None)
    if lock is None:
        state.chat_runtime_closing = closing
        return
    with lock:
        state.chat_runtime_closing = closing


def _sprite_path(sprite: Any) -> str:
    return str(sprite.path if hasattr(sprite, "path") else sprite.get("path", ""))


def _chat_session_media(state: Any) -> tuple[str, str, list[dict[str, Any]]]:
    config = state.config_manager.config
    character_name = str(state.chat_session.get("characterName") or "")
    background_name = str(state.chat_session.get("backgroundName") or "")
    character = (
        state.config_manager.get_character_by_name(character_name)
        if character_name
        else None
    )
    background = (
        None
        if _is_transparent_background_name(background_name)
        else state.config_manager.get_background_by_name(background_name)
    )
    if character is None:
        character = config.characters[0] if config.characters else None
    sprites = []
    if character and get_character_assets(character).sprites:
        visual = resolve_character_visual(character, 0, state.resource_urls)
        sprites.append(
            {
                "id": f"{character.name}-0",
                "label": character.name,
                **visual.snapshot_fields(),
            }
        )
    bg_path = ""
    if background and background.sprites:
        sprite = background.sprites[0]
        bg_path = _sprite_path(sprite)
    return (bg_path, character.name if character else "", sprites)


def _chat_voice_language(state: Any) -> str:
    session_language = (
        str(state.chat_session.get("voiceLanguage") or "").strip().lower()
    )
    if session_language:
        return session_language
    config_manager = getattr(state, "config_manager", None)
    system_config = getattr(
        getattr(config_manager, "config", None), "system_config", None
    )
    configured_language = (
        str(getattr(system_config, "voice_language", "") or "").strip().lower()
    )
    return configured_language or "ja"


def _chat_user_display_name(state: Any) -> str:
    return (
        sanitize_user_display_name(state.chat_session.get("userDisplayName"))
        or DEFAULT_USER_DISPLAY_NAME
    )


def _chat_user_display_name_from_snapshot(
    state: Any, snapshot: dict[str, Any] | None = None
) -> str:
    if snapshot is None:
        session_id = str(state.chat_session.get("sessionId") or "").strip()
        chat_stream = getattr(state, "chat_stream", None)
        if session_id and chat_stream is not None:
            candidate = chat_stream.get_snapshot(session_id)
            if isinstance(candidate, dict):
                snapshot = candidate
    stream_name = sanitize_user_display_name((snapshot or {}).get("userDisplayName"))
    if stream_name:
        state.chat_session = {**state.chat_session, "userDisplayName": stream_name}
        return stream_name
    return _chat_user_display_name(state)


def _chat_stream_initial_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Create a stream snapshot without carrying sprites from a previous session.

    The runtime producer is authoritative for the initial or history-restored
    sprite and will publish it before chat initialization completes.
    """
    initial = dict(snapshot)
    initial["sprites"] = []
    return initial


def _chat_theme_payload(state: Any) -> dict[str, Any]:
    system_config = state.config_manager.config.system_config
    raw_path = str(system_config.chat_ui_theme_path or "").strip()
    path = Path(raw_path) if raw_path else Path("data") / "chat_ui_theme.json"
    if not path.is_absolute():
        path = Path.cwd() / path
    data: Any = {}
    if path.is_file():
        with path.open(encoding="utf-8") as file:
            parsed = json.load(file)
        if isinstance(parsed, dict):
            data = parsed
    return {
        "path": path.as_posix() if path.exists() else "",
        "raw": data,
        "themeColor": str(system_config.theme_color or ""),
    }


class SnapshotProjection:
    def __init__(
        self,
        *,
        history: Callable[[Any], list[dict[str, Any]]],
        running: Callable[[], bool],
        story_patch: Callable[[Any], dict],
        mobile_info: Callable[[Any], Any],
    ) -> None:
        self.history, self.running = history, running
        self.story_patch, self.mobile_info = story_patch, mobile_info

    def build(
        self,
        state: Any,
        status: str | None = None,
        message: str = "",
        *,
        extra: dict[str, Any] | None = None,
        renderer_id: str = "",
    ) -> dict[str, Any]:
        session_id = str(state.chat_session.get("sessionId") or "").strip()
        chat_stream = getattr(state, "chat_stream", None)
        voice_language = _chat_voice_language(state)
        runtime_mode = _chat_runtime_mode(state)
        experimental_features = _chat_experimental_features(state)
        user_display_name = _chat_user_display_name(state)
        runtime_state = {
            "chatProcessRunning": self.running(),
            "chatRuntimeClosing": _chat_runtime_closing(state),
            "turnOptions": _chat_turn_options(state),
        }
        story_patch = self.story_patch(state)
        mobile_access_info = self.mobile_info(state)
        if mobile_access_info is not None:
            runtime_state["mobileAccess"] = mobile_access_info.to_payload()
        if session_id and chat_stream is not None:
            snapshot = (
                chat_stream.get_snapshot(session_id, renderer_id=renderer_id)
                if renderer_id
                else chat_stream.get_snapshot(session_id)
            )
            if snapshot is not None:
                next_snapshot = dict(snapshot)
                user_display_name = _chat_user_display_name_from_snapshot(
                    state, next_snapshot
                )
                next_snapshot["runtimeMode"] = runtime_mode
                next_snapshot["experimentalFeatures"] = experimental_features
                next_snapshot["userDisplayName"] = user_display_name
                if not experimental_features["conversationTree"]:
                    next_snapshot.pop("conversationTree", None)
                if voice_language and (
                    not str(next_snapshot.get("voiceLanguage") or "").strip()
                ):
                    next_snapshot["voiceLanguage"] = voice_language
                next_snapshot["historyEntries"] = self.history(state)
                if message:
                    next_snapshot["dialogText"] = message
                    next_snapshot.pop("dialogHtml", None)
                    next_snapshot["characterName"] = ""
                    next_snapshot["statusMessage"] = message
                if status is not None:
                    next_snapshot["status"] = status
                    next_snapshot["numericInfo"] = status
                next_snapshot.update(runtime_state)
                if mobile_access_info is not None:
                    next_snapshot["wsUrl"] = mobile_access_info.websocket_url
                if extra:
                    next_snapshot.update(extra)
                if story_patch:
                    next_snapshot.update(story_patch)
                return next_snapshot
        (bg_path, character_name, sprites) = _chat_session_media(state)
        history_path = str(state.chat_session.get("historyPath") or "")
        return {
            "backgroundPath": bg_path,
            "characterName": "" if message else character_name,
            "dialogText": message,
            "eventSeq": 0,
            "historyEntries": self.history(state),
            "historyPath": history_path,
            "inputDraft": "",
            "numericInfo": status,
            "options": [],
            "experimentalFeatures": experimental_features,
            "runtimeMode": runtime_mode,
            "sprites": sprites,
            "status": status or "idle",
            "statusMessage": message,
            "userDisplayName": user_display_name,
            "voiceLanguage": voice_language,
            **runtime_state,
            **story_patch,
            **(extra or {}),
        }
