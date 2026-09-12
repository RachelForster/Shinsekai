"""Re-run persisted media instructions through the active lookup pipeline."""

from __future__ import annotations

from typing import Any

from core.chat_history.text import parse_assistant_dialog_content
from core.messaging.dialog_tokens import (
    match_bgm_name,
    match_cg_name,
    match_cot_dialog,
    match_scene_dialog,
    match_system_dialog,
)
from sdk.messages import LLMDialogMessage


def latest_media_dialogs(
    messages: list[Any],
    *,
    opencc: Any,
) -> tuple[LLMDialogMessage, ...]:
    """Return the latest scene, BGM, and character instructions in source order."""

    latest: dict[str, tuple[int, LLMDialogMessage]] = {}
    position = 0
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for item in parse_assistant_dialog_content(message.get("content", "")):
            try:
                dialog = LLMDialogMessage.model_validate(item)
            except (TypeError, ValueError):
                continue
            position += 1
            if match_scene_dialog(opencc, dialog.name):
                kind = "scene"
            elif match_bgm_name(dialog.name):
                kind = "bgm"
            elif (
                match_cot_dialog(opencc, dialog.name)
                or match_system_dialog(opencc, dialog.name)
                or match_cg_name(dialog.name)
            ):
                continue
            else:
                kind = "character"
            latest[kind] = (position, dialog)

    return tuple(
        dialog for _, dialog in sorted(latest.values(), key=lambda item: item[0])
    )


def enqueue_latest_media_replay(
    messages: list[Any],
    *,
    dialog_queue: Any,
    opencc: Any,
) -> bool:
    """Replay raw media inputs with the active strategies, without replaying speech."""

    dialogs = latest_media_dialogs(messages, opencc=opencc)
    for dialog in dialogs:
        dialog_queue.put(
            dialog.model_copy(
                update={"_presentation_replay": True, "turn_id": None},
            )
        )
    return any(
        not (match_scene_dialog(opencc, dialog.name) or match_bgm_name(dialog.name))
        for dialog in dialogs
    )


__all__ = ["enqueue_latest_media_replay", "latest_media_dialogs"]
