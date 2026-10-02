"""Build chat snapshots and expose legacy theme configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from application.runtime.state import BridgeState
from application.chat.session_metadata import (
    chat_experimental_features,
    chat_turn_options,
    chat_session_media,
    chat_voice_language,
    chat_user_display_name,
    chat_user_display_name_from_snapshot,
)
from application.chat.read_history import chat_history_entries
from application.chat import runtime_process
from application.chat.snapshot_contributions import SnapshotContext


def build_chat_snapshot(
    state: BridgeState,
    status: str | None = None,
    message: str = "",
    *,
    extra: dict[str, Any] | None = None,
    renderer_id: str = "",
) -> dict[str, Any]:
    session_id = str(state.chat_session.get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)
    voice_language = chat_voice_language(state)
    runtime_mode = runtime_process._chat_runtime_mode(state)
    experimental_features = chat_experimental_features(state)
    user_display_name = chat_user_display_name(state)
    runtime_state = {
        "chatProcessRunning": runtime_process._chat_process_running(),
        "chatRuntimeClosing": runtime_process._chat_runtime_closing(state),
        "turnOptions": chat_turn_options(state),
    }
    if session_id and chat_stream is not None:
        snapshot = (
            chat_stream.get_snapshot(session_id, renderer_id=renderer_id)
            if renderer_id
            else chat_stream.get_snapshot(session_id)
        )
        if snapshot is not None:
            next_snapshot = dict(snapshot)
            user_display_name = chat_user_display_name_from_snapshot(state, next_snapshot)
            next_snapshot["runtimeMode"] = runtime_mode
            next_snapshot["experimentalFeatures"] = experimental_features
            next_snapshot["userDisplayName"] = user_display_name
            if not experimental_features["conversationTree"]:
                next_snapshot.pop("conversationTree", None)
            if voice_language and not str(next_snapshot.get("voiceLanguage") or "").strip():
                next_snapshot["voiceLanguage"] = voice_language
            next_snapshot["historyEntries"] = chat_history_entries(state)
            if message:
                next_snapshot["dialogText"] = message
                next_snapshot.pop("dialogHtml", None)
                next_snapshot["characterName"] = ""
                next_snapshot["statusMessage"] = message
            if status is not None:
                next_snapshot["status"] = status
                next_snapshot["numericInfo"] = status
            next_snapshot.update(runtime_state)
            return _with_contributions(state, next_snapshot, extra, streaming=True)
    bg_path, character_name, sprites = chat_session_media(state)
    history_path = str(state.chat_session.get("historyPath") or "")
    next_snapshot = {
        "backgroundPath": bg_path,
        "characterName": "" if message else character_name,
        "dialogText": message,
        "eventSeq": 0,
        "historyEntries": chat_history_entries(state),
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
    }
    return _with_contributions(state, next_snapshot, extra, streaming=False)


def _with_contributions(
    state: BridgeState,
    snapshot: dict[str, Any],
    extra: dict[str, Any] | None,
    *,
    streaming: bool,
) -> dict[str, Any]:
    from application.bootstrap.chat_runtime import get_chat_runtime

    contributors = get_chat_runtime(state).snapshots
    context = SnapshotContext.create(state.chat_session, snapshot, streaming=streaming)
    before = contributors.project(context)
    after = contributors.project(context, after_extra=True)
    # Preserve the pre-refactor precedence: story wins over extra on a stream,
    # while an explicit action patch wins on the fallback path.
    snapshot.update(before)
    if not streaming:
        snapshot.update(after)
    snapshot.update(extra or {})
    if streaming:
        snapshot.update(after)
    return snapshot


def initial_chat_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Create a stream snapshot without carrying sprites from a previous session.

    The runtime producer is authoritative for the initial or history-restored
    sprite and will publish it before chat initialization completes.
    """
    initial = dict(snapshot)
    initial["sprites"] = []
    return initial


def read_chat_theme(state: BridgeState) -> dict[str, Any]:
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
