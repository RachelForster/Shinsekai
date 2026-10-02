"""Project stable chat session metadata without owning process lifecycle."""

from __future__ import annotations

from typing import Any

from ai.tools.chat_ui_tools import sanitize_user_display_name
from application.runtime.state import BridgeState
from config.character_assets import get_character_assets
from application.chat.character_visual import resolve_character_visual

TRANSPARENT_BACKGROUND_NAME = "透明场景"
_TRANSPARENT_BACKGROUND_ALIAS = "透明背景"
DEFAULT_USER_DISPLAY_NAME = "你"


def is_transparent_background_name(name: str | None) -> bool:
    value = str(name or "").strip()
    return not value or value in {TRANSPARENT_BACKGROUND_NAME, _TRANSPARENT_BACKGROUND_ALIAS}


def chat_experimental_features(state: BridgeState) -> dict[str, bool]:
    config_manager = getattr(state, "config_manager", None)
    system_config = getattr(getattr(config_manager, "config", None), "system_config", None)
    return {
        "conversationTree": bool(getattr(system_config, "react_chat_flowchart_experimental_enabled", False)),
        "forkHistory": bool(getattr(system_config, "react_chat_fork_experimental_enabled", False)),
    }


def chat_turn_options(state: BridgeState) -> dict[str, Any]:
    config_manager = getattr(state, "config_manager", None)
    api_config = getattr(getattr(config_manager, "config", None), "api_config", None)
    return {
        "interruptEnabled": bool(getattr(api_config, "interrupt_enabled", True)),
        "batchEnabled": bool(getattr(api_config, "is_batch_input_enabled", False)),
        "batchIdleSeconds": float(getattr(api_config, "batch_input_timeout", 5.0) or 5.0),
    }


def sprite_path(sprite: Any) -> str:
    return str(sprite.path if hasattr(sprite, "path") else sprite.get("path", ""))


def chat_session_media(state: BridgeState) -> tuple[str, str, list[dict[str, Any]]]:
    config = state.config_manager.config
    character_name = str(state.chat_session.get("characterName") or "")
    background_name = str(state.chat_session.get("backgroundName") or "")
    character = state.config_manager.get_character_by_name(character_name) if character_name else None
    background = (
        None
        if is_transparent_background_name(background_name)
        else state.config_manager.get_background_by_name(background_name)
    )
    if character is None:
        character = config.characters[0] if config.characters else None
    sprites = []
    if character and get_character_assets(character).sprites:
        visual = resolve_character_visual(character, 0, state.resource_urls)
        sprites.append({"id": f"{character.name}-0", "label": character.name, **visual.snapshot_fields()})
    bg_path = ""
    if background and background.sprites:
        sprite = background.sprites[0]
        bg_path = sprite_path(sprite)
    return bg_path, character.name if character else "", sprites


def chat_voice_language(state: BridgeState) -> str:
    session_language = str(state.chat_session.get("voiceLanguage") or "").strip().lower()
    if session_language:
        return session_language
    config_manager = getattr(state, "config_manager", None)
    system_config = getattr(getattr(config_manager, "config", None), "system_config", None)
    configured_language = str(getattr(system_config, "voice_language", "") or "").strip().lower()
    return configured_language or "ja"


def sanitize_session_display_name(value: Any) -> str:
    return sanitize_user_display_name(value)


def chat_user_display_name(state: BridgeState) -> str:
    return sanitize_session_display_name(state.chat_session.get("userDisplayName")) or DEFAULT_USER_DISPLAY_NAME


def chat_user_display_name_from_snapshot(
    state: BridgeState,
    snapshot: dict[str, Any] | None = None,
) -> str:
    if snapshot is None:
        session_id = str(state.chat_session.get("sessionId") or "").strip()
        chat_stream = getattr(state, "chat_stream", None)
        if session_id and chat_stream is not None:
            candidate = chat_stream.get_snapshot(session_id)
            if isinstance(candidate, dict):
                snapshot = candidate
    stream_name = sanitize_session_display_name((snapshot or {}).get("userDisplayName"))
    if stream_name:
        state.chat_session = {**state.chat_session, "userDisplayName": stream_name}
        return stream_name
    return chat_user_display_name(state)
