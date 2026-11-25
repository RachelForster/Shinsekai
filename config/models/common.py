"""Shared validation helpers and identity constants for pure config models."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Any, TypeVar

from pydantic import BeforeValidator
from pydantic_core import PydanticUseDefault


def default_if_none(value: Any) -> Any:
    """Fall back to the field's default value when YAML/JSON supplies ``None``."""
    if value is None:
        raise PydanticUseDefault()
    return value


T = TypeVar("T")
DefaultIfNone = Annotated[T, BeforeValidator(default_if_none)]

COMPACT_TARGET_RATIO_MIN_GAP = 0.05

SELF_PERSONA_ID = "__self__"
SELF_PERSONA_NAME = "自设"
SELF_PERSONA_SPRITE_PREFIX = "__self__"
DEFAULT_SPRITE_GROUP = "默认"


def is_self_persona_name(name: Any) -> bool:
    """Return True when ``name`` refers to the built-in pinned self-persona slot."""
    return str(name or "").strip() == SELF_PERSONA_NAME


def _clean_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def resolve_character_prompt_name(
    character: Any,
    fallback_name: str = "",
    *,
    colliding_names: Iterable[str] = (),
) -> str:
    """Return the LLM-facing character name, using ``display_name`` for ``自设`` when safe."""
    raw_name = _clean_str(getattr(character, "name", None)) or _clean_str(fallback_name)
    if is_self_persona_name(raw_name):
        display_name = _clean_str(getattr(character, "display_name", None))
        collision_keys = {
            cleaned.casefold()
            for item in colliding_names
            if (cleaned := _clean_str(item)) and not is_self_persona_name(cleaned)
        }
        if display_name and display_name.casefold() not in collision_keys:
            return display_name
    return raw_name or _clean_str(fallback_name)


def resolve_character_by_prompt_name(config: Any, name: str) -> Any | None:
    """Look up a character by canonical name first, then by built-in ``自设.display_name``."""
    cleaned = _clean_str(name)
    if not cleaned or config is None:
        return None
    getter = getattr(config, "get_character_by_name", None)
    if callable(getter):
        direct = getter(cleaned)
        if direct is not None:
            return direct
        self_char = getter(SELF_PERSONA_NAME)
        if self_char is not None and is_self_persona_name(_clean_str(getattr(self_char, "name", None))):
            display_name = _clean_str(getattr(self_char, "display_name", None))
            if display_name and display_name.casefold() == cleaned.casefold():
                return self_char
        return None

    target = cleaned.casefold()
    self_match = None
    for char in getattr(getattr(config, "config", None), "characters", ()) or ():
        char_name = _clean_str(getattr(char, "name", None))
        if char_name.casefold() == target:
            return char
        if self_match is None and is_self_persona_name(char_name):
            display_name = _clean_str(getattr(char, "display_name", None))
            if display_name and display_name.casefold() == target:
                self_match = char
    return self_match


def clamp_compact_target_ratio(
    compact_threshold: float,
    compact_target_ratio: float,
) -> float:
    """Keep compaction target safely below the trigger threshold."""
    try:
        threshold = float(compact_threshold)
        target = float(compact_target_ratio)
    except (TypeError, ValueError):
        return compact_target_ratio
    max_target = max(0.0, threshold - COMPACT_TARGET_RATIO_MIN_GAP)
    return round(min(target, max_target), 6)


__all__ = [
    "COMPACT_TARGET_RATIO_MIN_GAP",
    "DEFAULT_SPRITE_GROUP",
    "DefaultIfNone",
    "SELF_PERSONA_ID",
    "SELF_PERSONA_NAME",
    "SELF_PERSONA_SPRITE_PREFIX",
    "clamp_compact_target_ratio",
    "default_if_none",
    "is_self_persona_name",
    "resolve_character_by_prompt_name",
    "resolve_character_prompt_name",
]
