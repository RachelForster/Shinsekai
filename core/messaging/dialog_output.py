"""Validation helpers for the runtime dialogue output contract."""

from __future__ import annotations

import json
import re
from typing import Any

from sdk.messages import LLMDialogMessage
from core.messaging.dialog_tokens import (
    CG_ALIASES,
    CHOICE_ALIASES,
    COT_ALIASES,
    NARR_ALIASES,
    STAT_ALIASES,
    normalize_character_name,
)

_REQUIRED_DIALOG_FIELDS = frozenset({"character_name", "speech"})
_NON_MEDIA_SYSTEM_NAMES = (
    CG_ALIASES | CHOICE_ALIASES | COT_ALIASES | NARR_ALIASES | STAT_ALIASES
)


def has_valid_dialog_item(item: Any, *, media_selection_mode: str = "indexed") -> bool:
    """Validate one wire-format item before sending it to media/TTS workers."""
    if not isinstance(item, dict) or not _REQUIRED_DIALOG_FIELDS.issubset(item):
        return False
    media_is_optional = (
        normalize_character_name(item.get("character_name", ""))
        in _NON_MEDIA_SYSTEM_NAMES
    )
    semantic = str(media_selection_mode or "").strip().lower() == "semantic"
    field = "vibe" if semantic else "sprite"
    if not media_is_optional:
        if field not in item:
            return False
        if (
            not semantic
            and re.fullmatch(r"(?:-1|[0-9]+)", str(item[field]).strip()) is None
        ):
            return False
    try:
        LLMDialogMessage.model_validate(item)
    except (TypeError, ValueError):
        return False
    return True


def has_valid_dialog_output(
    content: Any,
    *,
    media_selection_mode: str = "indexed",
) -> bool:
    """Return whether *content* is exactly one complete dialogue JSON object."""
    if not isinstance(content, str) or not content.strip():
        return False
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    dialog = payload.get("dialog")
    if not isinstance(dialog, list) or not dialog:
        return False
    return all(
        has_valid_dialog_item(item, media_selection_mode=media_selection_mode)
        for item in dialog
    )
