"""Enqueue already-published dialogue into the chat TTS pipeline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sdk.messages import LLMDialogMessage


def enqueue_spoken_dialog_lines(
    tts_queue: Any,
    chat_turn_service: Any,
    lines: Sequence[Mapping[str, Any]],
    *,
    audio_only: bool = True,
) -> int:
    """Begin a TTS turn for pre-rendered lines and return how many were queued."""
    pending: list[LLMDialogMessage] = []
    for raw in lines:
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("name") or "").strip()
        text = str(raw.get("text") or "").strip()
        if not name or not text:
            continue
        sprite = str(raw.get("sprite") or "-1").strip() or "-1"
        pending.append(
            LLMDialogMessage(
                name=name,
                text=text,
                asset_id=sprite,
                effect=str(raw.get("effect") or ""),
                audio_only=audio_only,
            )
        )
    if not pending:
        return 0
    if chat_turn_service.is_active():
        chat_turn_service.interrupt()
    turn = chat_turn_service.begin_turn()
    for message in pending:
        tts_queue.put(message.model_copy(update={"turn_id": turn.id}))
    chat_turn_service.mark_generation_complete(turn)
    return len(pending)
