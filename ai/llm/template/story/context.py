"""Plain rendering inputs; session and compiler objects stay in application."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ai.llm.template.core.context import TemplateContext


@dataclass(frozen=True)
class StoryGuidanceTransition:
    condition: str
    next_title: str


@dataclass(frozen=True)
class StoryGuidanceContext(TemplateContext):
    title: str
    instruction: str
    turn_count: int
    max_rounds: int | None
    transitions: tuple[StoryGuidanceTransition, ...] = ()
    background: str | None = None


@dataclass(frozen=True)
class StoryRequestContext(TemplateContext):
    """An application-prepared request, serialized as one intact JSON object."""

    payload: Mapping[str, Any]
