"""Domain commands accepted by the deterministic story runtime."""

from __future__ import annotations

from dataclasses import dataclass

from .semantic import SemanticSignalCandidate, SemanticSignalContext


@dataclass(frozen=True, slots=True)
class StartStory:
    command_id: str


@dataclass(frozen=True, slots=True)
class StoryCommand:
    command_id: str
    expected_revision: int


@dataclass(frozen=True, slots=True)
class SelectChoice(StoryCommand):
    choice_id: str
    expected_node_id: str


@dataclass(frozen=True, slots=True)
class PerformIntent(StoryCommand):
    intent_id: str
    expected_node_id: str


@dataclass(frozen=True, slots=True)
class ApplySemanticSignals(StoryCommand):
    candidates: tuple[SemanticSignalCandidate, ...]
    context: SemanticSignalContext


@dataclass(frozen=True, slots=True)
class EnterNode(StoryCommand):
    node_id: str


@dataclass(frozen=True, slots=True)
class CompleteNode(StoryCommand):
    node_id: str


@dataclass(frozen=True, slots=True)
class RequestCharacterEntry(StoryCommand):
    character_id: str
    reason_id: str
    expected_node_id: str


@dataclass(frozen=True, slots=True)
class RequestCharacterExit(StoryCommand):
    character_id: str
    reason_id: str
    expected_node_id: str


@dataclass(frozen=True, slots=True)
class RequestCharacterReplace(StoryCommand):
    outgoing_character_id: str
    incoming_character_id: str
    reason_id: str
    expected_node_id: str


RuntimeCommand = (
    SelectChoice
    | PerformIntent
    | ApplySemanticSignals
    | EnterNode
    | CompleteNode
    | RequestCharacterEntry
    | RequestCharacterExit
    | RequestCharacterReplace
)
