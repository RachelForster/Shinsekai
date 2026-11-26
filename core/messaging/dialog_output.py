"""Validation helpers for the runtime dialogue output contract."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from sdk.messages import LLMDialogMessage
from core.messaging.dialog_tokens import (
    BGM_ALIASES,
    CG_ALIASES,
    CHOICE_ALIASES,
    COT_ALIASES,
    NARR_ALIASES,
    SCENE_ALIASES,
    STAT_ALIASES,
    normalize_character_name,
)

_REQUIRED_DIALOG_FIELDS = frozenset({"character_name", "speech"})
_NON_MEDIA_SYSTEM_NAMES = (
    CG_ALIASES | CHOICE_ALIASES | COT_ALIASES | NARR_ALIASES | STAT_ALIASES
)
_REQUIRED_MEDIA_SYSTEM_NAMES = BGM_ALIASES | SCENE_ALIASES


def _has_non_empty_media_value(item: dict[str, Any], field: str) -> bool:
    if field not in item:
        return False
    value = item.get(field)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def parse_and_validate_dialog_output(
    content: Any,
    *,
    media_selection_mode: str = "indexed",
    speaker_requires_media: Callable[[str], bool] | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    """Validate *content* against the runtime dialogue JSON contract and return items."""
    if not isinstance(content, str) or not content.strip():
        return False, []
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return False, []
    if not isinstance(payload, dict):
        return False, []
    dialog = payload.get("dialog")
    if not isinstance(dialog, list) or not dialog:
        return False, []
    required_media_field = (
        "vibe"
        if str(media_selection_mode or "").strip().lower() == "semantic"
        else "sprite"
    )
    validated: list[dict[str, Any]] = []
    for item in dialog:
        if not isinstance(item, dict) or not _REQUIRED_DIALOG_FIELDS.issubset(item):
            return False, []
        raw_speaker = str(item.get("character_name") or "").strip()
        name = normalize_character_name(raw_speaker)
        if name in _NON_MEDIA_SYSTEM_NAMES:
            media_required = False
            strict_non_empty = False
        elif name in _REQUIRED_MEDIA_SYSTEM_NAMES:
            media_required = True
            strict_non_empty = speaker_requires_media is not None
        elif speaker_requires_media is not None:
            media_required = bool(speaker_requires_media(raw_speaker))
            strict_non_empty = True
        else:
            media_required = True
            strict_non_empty = False

        if media_required:
            if strict_non_empty:
                if not _has_non_empty_media_value(item, required_media_field):
                    return False, []
            elif required_media_field not in item:
                return False, []
        try:
            LLMDialogMessage.model_validate(item)
        except (TypeError, ValueError):
            return False, []
        validated.append(dict(item))
    return True, validated


def has_valid_json_dialog_output(
    content: Any,
    *,
    media_selection_mode: str = "indexed",
    speaker_requires_media: Callable[[str], bool] | None = None,
) -> bool:
    """Return whether *content* is exactly one complete dialogue JSON object."""
    valid, _ = parse_and_validate_dialog_output(
        content,
        media_selection_mode=media_selection_mode,
        speaker_requires_media=speaker_requires_media,
    )
    return valid


def has_valid_dialog_output(
    content: Any,
    *,
    media_selection_mode: str = "indexed",
    speaker_requires_media: Callable[[str], bool] | None = None,
    format_id: str | None = None,
) -> bool:
    """Return whether *content* satisfies the active dialogue output format contract."""
    fmt_key = str(format_id or "").strip().lower()
    if fmt_key and fmt_key != "json_v1":
        if not isinstance(content, str):
            return False
        from core.messaging.formats.registry import resolve_dialog_format

        fmt = resolve_dialog_format(fmt_key)
        try:
            return bool(
                fmt.validate(
                    content,
                    media_selection_mode=media_selection_mode,
                    speaker_requires_media=speaker_requires_media,
                )
            )
        except TypeError:
            try:
                return bool(
                    fmt.validate(content, media_selection_mode=media_selection_mode)
                )
            except TypeError:
                return bool(fmt.validate(content))
    return has_valid_json_dialog_output(
        content,
        media_selection_mode=media_selection_mode,
        speaker_requires_media=speaker_requires_media,
    )
