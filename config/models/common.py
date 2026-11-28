"""Shared validation helpers and identity constants for pure config models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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


def is_self_persona_id(char_id: Any) -> bool:
    """Return True when ``char_id`` matches the immutable built-in self-persona primary key."""
    return str(char_id or "").strip() == SELF_PERSONA_ID


def is_self_persona_name(name: Any) -> bool:
    """Return True when ``name`` matches the default legacy self-persona name."""
    return str(name or "").strip() == SELF_PERSONA_NAME


def _read_attr_or_key(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def is_self_persona(character: Any) -> bool:
    """Return True when ``character`` represents the built-in pinned self-persona slot."""
    if character is None:
        return False
    char_id = str(_read_attr_or_key(character, "id", "") or "").strip()
    if is_self_persona_id(char_id):
        return True
    if bool(_read_attr_or_key(character, "is_builtin", False)):
        return True
    return not char_id and is_self_persona_name(_read_attr_or_key(character, "name", ""))


def find_self_persona(characters: Iterable[Any]) -> Any | None:
    """Find the built-in self-persona entity by stable ``id`` first, then fallback flags/name."""
    fallback: Any | None = None
    for item in characters:
        if is_self_persona_id(_read_attr_or_key(item, "id", "")):
            return item
        if fallback is None and is_self_persona(item):
            fallback = item
    return fallback


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
    "find_self_persona",
    "is_self_persona",
    "is_self_persona_id",
    "is_self_persona_name",
]
