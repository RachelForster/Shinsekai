"""Presentation-neutral facts emitted by the story runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class StoryEventType(str, Enum):
    COMMAND_PROCESSED = "CommandProcessed"
    STORY_STARTED = "StoryStarted"
    CHOICE_SELECTED = "ChoiceSelected"
    INTENT_PERFORMED = "IntentPerformed"
    VARIABLE_CHANGED = "VariableChanged"
    SET_VALUE_ADDED = "SetValueAdded"
    SET_VALUE_REMOVED = "SetValueRemoved"
    NODE_UNLOCKED = "NodeUnlocked"
    NODE_ENTERED = "NodeEntered"
    NODE_COMPLETED = "NodeCompleted"
    CANON_APPENDED = "CanonAppended"
    SEMANTIC_SIGNAL_ACCEPTED = "SemanticSignalAccepted"
    SEMANTIC_SIGNAL_REJECTED = "SemanticSignalRejected"
    METRIC_CHANGED = "MetricChanged"
    CAST_RESOLVED = "CastResolved"
    ENDING_REACHED = "EndingReached"


@dataclass(frozen=True, slots=True)
class StoryEvent:
    id: str
    revision: int
    type: StoryEventType
    payload: Mapping[str, Any]
    cause_command_id: str
