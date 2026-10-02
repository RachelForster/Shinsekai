"""Apply an explicit edit to one conversation, keeping its history identity."""

from __future__ import annotations

import uuid
from typing import Any

from application.chat.conversation_library import (
    conversation_details,
    conversation_launch_payload,
    current_conversation,
)
from application.chat.runtime_process import _chat_process_running, _chat_snapshot
from application.chat.stop_chat import stop_chat
from application.story.coordinator import start_or_recover_story_session
from application.story.library import prepare_story_launch


def prepare_conversation_edit(state: Any, conversation_id: str, payload: dict) -> dict:
    """Validate before stopping the runtime; never accept a replacement history."""
    details = conversation_details(state, conversation_id)
    if not isinstance(payload.get("system"), str) or not isinstance(
        payload.get("scenario"), str
    ):
        raise ValueError("conversation edits require system and scenario text")
    names = payload.get("characters")
    if not isinstance(names, list) or any(
        not isinstance(name, str)
        or state.config_manager.get_character_by_name(name) is None
        for name in names
    ):
        raise ValueError("conversation contains an unavailable character")
    from application.chat.player_control import resolve_player
    resolve_player(state.config_manager, names, payload.get("playerCharacter"))
    if details["kind"] == "story":
        if not details["storyPath"]:
            raise ValueError("the original story is unavailable")
        prepare_story_launch(state, details["storyPath"], details["historyPath"])
    return {
        **conversation_launch_payload(state, conversation_id),
        **payload,
        "historyPath": details["historyPath"],
        "resetHistory": False,
        "useCurrentTemplateForHistory": True,
    }


def restart_edited_conversation(
    state: Any, conversation_id: str, payload: dict
) -> None:
    # Revalidate inside the serialized initialization task, immediately before
    # stopping anything. Opening/cancelling the editor never reaches this path.
    prepare_conversation_edit(state, conversation_id, payload)
    if _chat_process_running():
        current = current_conversation(state)
        if current is None or current["id"] != conversation_id:
            raise RuntimeError(
                "Another chat is running. Close it before applying these settings."
            )
        snapshot = _chat_snapshot(state)
        turn = snapshot.get("turnState") or {}
        if (
            snapshot.get("status") not in {"idle", "paused", "error"}
            or turn.get("pendingCount")
            or turn.get("scheduled")
        ):
            raise RuntimeError(
                "Wait for the current reply and queued messages to finish before applying."
            )
        stop_chat(state)
    details = conversation_details(state, conversation_id)
    state.chat_session = {**state.chat_session, "historyPath": details["historyPath"]}
    if details["kind"] == "story":
        start_or_recover_story_session(
            state, details["storyPath"], command_id=uuid.uuid4().hex
        )
