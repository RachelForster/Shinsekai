"""Shared validation helpers and identity constants for pure config models."""

from __future__ import annotations

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
]
