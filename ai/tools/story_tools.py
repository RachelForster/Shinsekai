"""LLM-facing story scene tools.

Wrappers only expose OpenAI function schemas. They never mutate story state;
``application.story.scene.SceneOrchestrator`` submits ``StoryCommand`` values
and ``core.story`` adjudicates them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
from types import MappingProxyType
from typing import Any

from core.story import SignalStrength, SpeechAct, StoryProgram
from sdk.tool_registry import iter_registered_tools, tool

STORY_TOOL_GROUP = "story"

_ENUM_BY_TOOL: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {
        "perform_intent": MappingProxyType({"intentId": "allowedIntentIds"}),
        "apply_semantic_signal": MappingProxyType(
            {
                "signalId": "allowedSignalIds",
                "strength": "strengths",
                "speechAct": "speechActs",
            }
        ),
        "request_character_entry": MappingProxyType(
            {
                "characterId": "allowedCharacterIds",
                "reasonId": "allowedReasonIds",
            }
        ),
        "request_character_exit": MappingProxyType(
            {
                "characterId": "allowedCharacterIds",
                "reasonId": "allowedReasonIds",
            }
        ),
        "request_character_replace": MappingProxyType(
            {
                "outgoingCharacterId": "allowedCharacterIds",
                "incomingCharacterId": "allowedCharacterIds",
                "reasonId": "allowedReasonIds",
            }
        ),
    }
)


def _reject_direct_execution(name: str, **arguments: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "errorCode": "scene.tool_not_executable",
        "error": (
            "Story tools are scene proposals. Only SceneOrchestrator may "
            "adjudicate them through StorySession."
        ),
        "name": name,
        "arguments": arguments,
    }


@tool(
    name="perform_intent",
    group=STORY_TOOL_GROUP,
    description=(
        "Propose a published freeform intent for the current node. This is a "
        "proposal only; StorySession adjudicates and may reject it. "
        "intentId must be one of the allowedIntentIds for this turn. "
        "expectedNodeId and expectedRevision must match the current scene."
    ),
)
def perform_intent(
    intentId: str,
    expectedNodeId: str,
    expectedRevision: int,
) -> dict[str, Any]:
    return _reject_direct_execution(
        "perform_intent",
        intentId=intentId,
        expectedNodeId=expectedNodeId,
        expectedRevision=expectedRevision,
    )


@tool(
    name="apply_semantic_signal",
    group=STORY_TOOL_GROUP,
    description=(
        "Propose a published semantic signal. Fingerprints are assigned by "
        "the application, not by the model. signalId, strength, and speechAct "
        "must be in this turn's allowlists."
    ),
)
def apply_semantic_signal(
    signalId: str,
    strength: str,
    confidence: float,
    speechAct: str,
    expectedNodeId: str,
    expectedRevision: int,
) -> dict[str, Any]:
    return _reject_direct_execution(
        "apply_semantic_signal",
        signalId=signalId,
        strength=strength,
        confidence=confidence,
        speechAct=speechAct,
        expectedNodeId=expectedNodeId,
        expectedRevision=expectedRevision,
    )


@tool(
    name="request_character_entry",
    group=STORY_TOOL_GROUP,
    description=(
        "Propose that a published character enter the active cast. "
        "characterId and reasonId must be in this turn's allowlists."
    ),
)
def request_character_entry(
    characterId: str,
    reasonId: str,
    expectedNodeId: str,
    expectedRevision: int,
) -> dict[str, Any]:
    return _reject_direct_execution(
        "request_character_entry",
        characterId=characterId,
        reasonId=reasonId,
        expectedNodeId=expectedNodeId,
        expectedRevision=expectedRevision,
    )


@tool(
    name="request_character_exit",
    group=STORY_TOOL_GROUP,
    description=(
        "Propose that an active character leave the scene. "
        "characterId and reasonId must be in this turn's allowlists."
    ),
)
def request_character_exit(
    characterId: str,
    reasonId: str,
    expectedNodeId: str,
    expectedRevision: int,
) -> dict[str, Any]:
    return _reject_direct_execution(
        "request_character_exit",
        characterId=characterId,
        reasonId=reasonId,
        expectedNodeId=expectedNodeId,
        expectedRevision=expectedRevision,
    )


@tool(
    name="request_character_replace",
    group=STORY_TOOL_GROUP,
    description=(
        "Propose replacing one active character with another published "
        "character. IDs and reasonId must be in this turn's allowlists."
    ),
)
def request_character_replace(
    outgoingCharacterId: str,
    incomingCharacterId: str,
    reasonId: str,
    expectedNodeId: str,
    expectedRevision: int,
) -> dict[str, Any]:
    return _reject_direct_execution(
        "request_character_replace",
        outgoingCharacterId=outgoingCharacterId,
        incomingCharacterId=incomingCharacterId,
        reasonId=reasonId,
        expectedNodeId=expectedNodeId,
        expectedRevision=expectedRevision,
    )


def ensure_story_tools_registered(tool_manager: Any | None = None) -> Any:
    """Register story-group tools onto ``tool_manager`` if they are missing."""
    from ai.tools.tool_manager import ToolManager

    manager = tool_manager or ToolManager()
    if manager.get_definitions(groups=STORY_TOOL_GROUP):
        return manager
    for fn, name, description, group, risk in iter_registered_tools():
        if group != STORY_TOOL_GROUP:
            continue
        manager.register_function(
            fn,
            name=name,
            description=description,
            group=group,
            risk=risk or "low",
        )
    return manager


def scene_tool_protocol_definitions(
    program: StoryProgram,
    node_id: str,
    revision: int,
    public_context: Mapping[str, Any],
    *,
    allowed_intent_ids: Sequence[str],
) -> tuple[Mapping[str, Any], ...]:
    """Compact per-turn allowlists used by the scene JSON protocol."""
    boundary = {
        "expectedNodeId": node_id,
        "expectedRevision": revision,
    }
    tools: list[Mapping[str, Any]] = []
    if allowed_intent_ids:
        tools.append(
            MappingProxyType(
                {
                    "name": "perform_intent",
                    "allowedIntentIds": list(allowed_intent_ids),
                    **boundary,
                }
            )
        )
    if program.semantic_signals:
        tools.append(
            MappingProxyType(
                {
                    "name": "apply_semantic_signal",
                    "allowedSignalIds": [item.id for item in program.semantic_signals],
                    "strengths": [item.value for item in SignalStrength],
                    "speechActs": [item.value for item in SpeechAct],
                    **boundary,
                }
            )
        )
    for action in ("Entry", "Exit", "Replace"):
        reasons = public_context.get(f"character{action}ReasonIds", ())
        if (
            isinstance(reasons, Sequence)
            and not isinstance(reasons, (str, bytes, bytearray))
            and reasons
        ):
            tools.append(
                MappingProxyType(
                    {
                        "name": f"request_character_{action.lower()}",
                        "allowedCharacterIds": sorted(program.character_registry.by_id),
                        "allowedReasonIds": [str(item) for item in reasons],
                        **boundary,
                    }
                )
            )
    return tuple(tools)


def openai_tools_from_protocol(
    protocol_tools: Sequence[Mapping[str, Any]],
    *,
    tool_manager: Any | None = None,
) -> list[dict[str, Any]]:
    """Bind this turn's allowlists onto the registered OpenAI function schemas."""
    if not protocol_tools:
        return []
    manager = ensure_story_tools_registered(tool_manager)
    by_name = {
        item["function"]["name"]: item
        for item in manager.get_definitions(groups=STORY_TOOL_GROUP)
    }
    bound: list[dict[str, Any]] = []
    for protocol in protocol_tools:
        name = str(protocol.get("name") or "").strip()
        base = by_name.get(name)
        if base is None:
            continue
        definition = copy.deepcopy(base)
        properties = definition["function"]["parameters"].setdefault("properties", {})
        _apply_protocol_enums(name, properties, protocol)
        bound.append(definition)
    return bound


def _apply_protocol_enums(
    name: str,
    properties: dict[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    node_id = str(protocol.get("expectedNodeId") or "").strip()
    if node_id:
        _set_enum(properties, "expectedNodeId", [node_id])
    revision = protocol.get("expectedRevision")
    if revision is not None:
        _set_enum(properties, "expectedRevision", [int(revision)])
    for property_name, protocol_key in _ENUM_BY_TOOL.get(name, {}).items():
        values = protocol.get(protocol_key)
        if (
            isinstance(values, Sequence)
            and not isinstance(values, (str, bytes, bytearray))
            and values
        ):
            _set_enum(properties, property_name, list(values))


def _set_enum(
    properties: dict[str, Any],
    property_name: str,
    values: list[Any],
) -> None:
    schema = properties.setdefault(property_name, {"type": "string"})
    schema["enum"] = list(values)
