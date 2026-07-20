"""Validation helpers for the runtime dialogue output contract."""

from __future__ import annotations

import json
from typing import Any

from sdk.messages import LLMDialogMessage

_REQUIRED_DIALOG_FIELDS = frozenset({"character_name", "speech", "sprite"})


def has_valid_dialog_output(content: Any) -> bool:
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
    for item in dialog:
        if not isinstance(item, dict) or not _REQUIRED_DIALOG_FIELDS.issubset(item):
            return False
        try:
            LLMDialogMessage.model_validate(item)
        except (TypeError, ValueError):
            return False
    return True
