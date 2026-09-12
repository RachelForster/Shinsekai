"""Validation helpers for the runtime dialogue output contract."""

from __future__ import annotations

import json
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
    required_media_field = (
        "vibe"
        if str(media_selection_mode or "").strip().lower() == "semantic"
        else "sprite"
    )
    for item in dialog:
        name = (
            normalize_character_name(item.get("character_name", ""))
            if isinstance(item, dict)
            else ""
        )
        media_is_optional = name in _NON_MEDIA_SYSTEM_NAMES
        if (
            not isinstance(item, dict)
            or not _REQUIRED_DIALOG_FIELDS.issubset(item)
            or (not media_is_optional and required_media_field not in item)
        ):
            return False
        try:
            LLMDialogMessage.model_validate(item)
        except (TypeError, ValueError):
            return False
    return True
