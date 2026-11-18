from collections import Counter
from copy import deepcopy
import random

import pytest

from core.randomness import RandomRequestError, execute_random_request


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("sample", {"items": ["a", "b", "c"], "count": 2}),
        ("shuffle", {"items": ["a", "b", "c"]}),
        ("roll_dice", {"count": 10, "sides": 6}),
        (
            "assign",
            {"participants": ["a", "b", "c"], "labels": {"wolf": 1, "villager": 2}},
        ),
    ],
)
def test_random_operations_replay_without_mutating_input_or_global_rng(
    operation, arguments
):
    original = deepcopy(arguments)
    global_state = random.getstate()
    result = execute_random_request(operation, arguments, source=random.Random(123))
    assert (
        execute_random_request(operation, arguments, source=random.Random(123))
        == result
    )
    assert arguments == original
    assert random.getstate() == global_state
    if operation == "sample":
        assert len(result["items"]) == len(set(result["items"])) == 2
        assert set(result["items"]) <= set(arguments["items"])
    elif operation == "shuffle":
        assert sorted(result["items"]) == sorted(arguments["items"])
    elif operation == "roll_dice":
        assert len(result["rolls"]) == 10
        assert all(1 <= value <= 6 for value in result["rolls"])
        assert result["total"] == sum(result["rolls"])
    else:
        assert set(result["assignments"]) == set(arguments["participants"])
        assert Counter(result["assignments"].values()) == arguments["labels"]


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("unknown", {}),
        ("sample", {"items": [], "count": 1}),
        ("sample", {"items": ["a"], "count": 2}),
        ("sample", {"items": ["a"], "count": True}),
        ("shuffle", {"items": ["a", "a"]}),
        ("shuffle", {"items": [" "]}),
        ("shuffle", {"items": ["a"], "seed": 1}),
        ("shuffle", {"items": [str(i) for i in range(129)]}),
        ("roll_dice", {"count": 101, "sides": 6}),
        ("roll_dice", {"count": 1, "sides": 1}),
        ("assign", {"participants": ["a"], "labels": {"wolf": 2}}),
        ("assign", {"participants": ["a"], "labels": {"wolf": True}}),
        ("assign", {"participants": ["a"], "labels": {"wolf": 0, "villager": 1}}),
    ],
)
def test_invalid_random_requests_are_rejected(operation, arguments):
    with pytest.raises(RandomRequestError):
        execute_random_request(operation, arguments)
