"""Scoped LLM schemas for general randomness; no global chat registration."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from typing import Any

from core.randomness import MAX_DICE, MAX_ITEMS, MAX_SIDES, RandomRequestError

RANDOM_TOOL_OPERATIONS = {
    "random_sample": "sample",
    "random_shuffle": "shuffle",
    "random_roll_dice": "roll_dice",
    "random_assign": "assign",
}
_ITEMS = {
    "type": "array",
    "minItems": 1,
    "maxItems": MAX_ITEMS,
    "uniqueItems": True,
    "items": {"type": "string", "minLength": 1, "maxLength": 256},
}


def random_tool_definitions() -> list[dict[str, Any]]:
    """Return fresh definitions for explicit author or future session scopes."""
    specs = {
        "random_sample": (
            "Sample distinct items without replacement.",
            {
                "items": _ITEMS,
                "count": {"type": "integer", "minimum": 1, "maximum": MAX_ITEMS},
            },
        ),
        "random_shuffle": (
            "Return a random permutation of the supplied items.",
            {"items": _ITEMS},
        ),
        "random_roll_dice": (
            "Roll count independent fair dice and return their values and sum.",
            {
                "count": {"type": "integer", "minimum": 1, "maximum": MAX_DICE},
                "sides": {"type": "integer", "minimum": 2, "maximum": MAX_SIDES},
            },
        ),
        "random_assign": (
            "Randomly assign labels to participants with exact label counts. "
            "Counts must sum to the participant count; each participant gets one label.",
            {
                "participants": _ITEMS,
                "labels": {
                    "type": "object",
                    "minProperties": 1,
                    "maxProperties": MAX_ITEMS,
                    "additionalProperties": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_ITEMS,
                    },
                },
            },
        ),
    }
    definitions = []
    for name, (description, fields) in specs.items():
        properties = {
            "requestId": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "description": "Stable logical decision ID, e.g. culprit or role-deal. "
                "Reuse it with identical arguments on retries; use a new ID for a new decision.",
            },
            **fields,
        }
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": list(properties),
                        "additionalProperties": False,
                    },
                },
            }
        )
    return copy.deepcopy(definitions)


def execute_random_tool(
    name: str,
    arguments: Mapping[str, Any],
    *,
    execute: Callable[[str, str, Mapping[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Adapt a tool call to a host-owned execution context (authoring or session)."""
    if name not in RANDOM_TOOL_OPERATIONS:
        raise RandomRequestError(
            "unknown tool; only the supplied random tools are available"
        )
    if not isinstance(arguments, Mapping):
        raise RandomRequestError("tool arguments must be an object")
    request_id = arguments.get("requestId")
    if (
        not isinstance(request_id, str)
        or not request_id.strip()
        or len(request_id) > 128
    ):
        raise RandomRequestError(
            "requestId must be a nonempty string up to 128 characters"
        )
    return execute(
        RANDOM_TOOL_OPERATIONS[name],
        request_id,
        {key: value for key, value in arguments.items() if key != "requestId"},
    )
