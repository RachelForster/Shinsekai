"""Presentation-safe story projections for chat snapshots and realtime events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.story import ConditionEvaluator, StoryEvent, StoryProgram, StoryState

from .persistence import GlobalStoryProgress


def story_state_view(
    program: StoryProgram,
    state: StoryState,
    global_progress: GlobalStoryProgress,
) -> dict[str, Any]:
    """Project only player-visible story data into the chat protocol."""
    node = program.nodes_by_id[state.current_node_id]
    variables = {**global_progress.variables, **state.variables}
    evaluator = ConditionEvaluator()
    options = []
    for choice in node.choices:
        enabled = evaluator.evaluate(
            choice.when,
            variables=variables,
            completed_node_ids=state.completed_node_ids,
        )
        options.append(
            {
                "id": choice.id,
                "label": choice.label,
                "enabled": enabled,
                "lockedReason": None if enabled else "condition-not-satisfied",
                "source": "story",
                "expectedNodeId": node.id,
                "expectedRevision": state.revision,
            }
        )
    visible_variables = []
    for definition in program.variables:
        if not definition.visible:
            continue
        value = variables[definition.id]
        visible_variables.append(
            {
                "id": definition.id,
                "type": definition.type.value,
                "value": _protocol_value(value),
                "minimum": definition.minimum,
                "maximum": definition.maximum,
            }
        )
    ending = None
    if node.type == "ending":
        ending = {"id": node.id, "title": node.title}
    return {
        "storyId": program.story_id,
        "storyVersion": program.story_version,
        "revision": state.revision,
        "currentNodeId": node.id,
        "currentNodeTitle": node.title,
        "activeCast": [
            {
                "id": character_id,
                "roles": list(program.character_registry.by_id[character_id].roles),
            }
            for character_id in state.cast_state.active_character_ids
        ],
        "objectives": [],
        "visibleVariables": visible_variables,
        "unlockedNotifications": [
            {"id": node_id, "kind": "node"}
            for node_id in sorted(state.unlocked_node_ids)
        ],
        "ending": ending,
        # Authoritative graph actions are grounding material for the scene LLM,
        # not presentation choices. The LLM emits the visible CHOICE item after
        # its dialogue; selecting an exact authoritative label is adjudicated
        # locally by StorySession.
        "options": [],
        "referenceActions": options,
        "castRevision": state.cast_state.cast_revision,
    }


def story_event_messages(events: tuple[StoryEvent, ...]) -> list[dict[str, Any]]:
    event_names = {
        "NodeEntered": "story.node.entered",
        "NodeUnlocked": "story.node.unlocked",
        "CastResolved": "story.cast.replace",
        "EndingReached": "story.ending.reached",
    }
    messages = []
    for event in events:
        event_type = event_names.get(event.type.value)
        if event_type is None:
            continue
        messages.append(
            {
                "type": event_type,
                "eventId": event.id,
                "revision": event.revision,
                "payload": _protocol_value(event.payload),
            }
        )
    return messages


def story_chat_snapshot(view: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "story": dict(view),
        "stats": [
            {
                "icon": "gauge",
                "label": str(item["id"]),
                "value": int(item["value"]),
                **(
                    {"max": int(item["maximum"])}
                    if isinstance(item.get("maximum"), int)
                    else {}
                ),
            }
            for item in view.get("visibleVariables", ())
            if isinstance(item, Mapping)
            and isinstance(item.get("value"), int)
            and not isinstance(item.get("value"), bool)
        ],
    }


def _protocol_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _protocol_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted(_protocol_value(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [_protocol_value(item) for item in value]
    return value
