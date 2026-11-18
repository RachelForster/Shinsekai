"""Validated random operations independent of models, games, and persistence."""

from __future__ import annotations

from collections.abc import Mapping
import random
from typing import Any

MAX_ITEMS = 128
MAX_DICE = 100
MAX_SIDES = 1_000_000


class RandomRequestError(ValueError):
    pass


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise RandomRequestError(
            f"{name} must be an integer between {minimum} and {maximum}"
        )
    return value


def _items(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_ITEMS:
        raise RandomRequestError(f"{name} must contain 1 to {MAX_ITEMS} unique strings")
    if any(
        not isinstance(item, str) or not item.strip() or len(item) > 256
        for item in value
    ):
        raise RandomRequestError(
            f"{name} entries must be nonempty strings up to 256 characters"
        )
    if len(set(value)) != len(value):
        raise RandomRequestError(f"{name} entries must be unique")
    return list(value)


def validate_random_request(
    operation: str, arguments: Mapping[str, Any]
) -> dict[str, Any]:
    fields = {
        "sample": {"items", "count"},
        "shuffle": {"items"},
        "roll_dice": {"count", "sides"},
        "assign": {"participants", "labels"},
    }
    if operation not in fields:
        raise RandomRequestError("unknown random operation")
    if not isinstance(arguments, Mapping) or set(arguments) != fields[operation]:
        raise RandomRequestError(
            f"{operation} requires exactly {sorted(fields[operation])}"
        )
    if operation in {"sample", "shuffle"}:
        items = _items(arguments["items"], "items")
        result = {"items": items}
        if operation == "sample":
            result["count"] = _integer(arguments["count"], "count", 1, len(items))
        return result
    if operation == "roll_dice":
        return {
            "count": _integer(arguments["count"], "count", 1, MAX_DICE),
            "sides": _integer(arguments["sides"], "sides", 2, MAX_SIDES),
        }
    participants = _items(arguments["participants"], "participants")
    labels = arguments["labels"]
    if not isinstance(labels, Mapping) or not labels or len(labels) > MAX_ITEMS:
        raise RandomRequestError(
            "labels must be a nonempty mapping of labels to counts"
        )
    for label, count in labels.items():
        if not isinstance(label, str) or not label.strip() or len(label) > 256:
            raise RandomRequestError(
                "labels must be nonempty strings up to 256 characters"
            )
        _integer(count, "label count", 1, MAX_ITEMS)
    if sum(labels.values()) != len(participants):
        raise RandomRequestError("label counts must sum to the number of participants")
    return {"participants": participants, "labels": dict(labels)}


def execute_random_request(
    operation: str, arguments: Mapping[str, Any], *, source: random.Random | None = None
) -> dict[str, Any]:
    """Use host-provided entropy; never modify the input or global RNG state."""
    args = validate_random_request(operation, arguments)
    rng = source if source is not None else random.SystemRandom()
    if operation == "sample":
        return {"items": rng.sample(args["items"], args["count"])}
    if operation == "shuffle":
        rng.shuffle(args["items"])
        return {"items": args["items"]}
    if operation == "roll_dice":
        rolls = [rng.randint(1, args["sides"]) for _ in range(args["count"])]
        return {"rolls": rolls, "total": sum(rolls)}
    # Canonical label order makes JSON object key order irrelevant.
    deck = [
        label for label, count in sorted(args["labels"].items()) for _ in range(count)
    ]
    rng.shuffle(deck)
    return {"assignments": dict(zip(args["participants"], deck))}
