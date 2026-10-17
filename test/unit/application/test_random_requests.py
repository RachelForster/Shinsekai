from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

import pytest

from application.random_requests import RandomRequestExecutor
from core.randomness import RandomRequestError


def test_records_survive_restart_and_do_not_expose_or_accept_a_seed(tmp_path):
    path = tmp_path / "random.json"

    def save(state):
        path.write_text(json.dumps(state), encoding="utf-8")

    executor = RandomRequestExecutor(scope="author:one", save=save)
    args = {"participants": ["A", "B", "C"], "labels": {"wolf": 1, "villager": 2}}
    result = executor.execute("assign", "identities", args)
    saved = json.loads(path.read_text())
    restored = RandomRequestExecutor(scope="author:one", state=saved, save=save)
    assert restored.execute("assign", "identities", args) == result
    assert "seed" not in result
    result["assignments"].clear()
    assert len(restored.execute("assign", "identities", args)["assignments"]) == 3
    with pytest.raises(RandomRequestError, match="different decision"):
        restored.execute("roll_dice", "identities", {"count": 1, "sides": 6})
    with pytest.raises(ValueError, match="scope"):
        RandomRequestExecutor(scope="session:new", state=saved)
    second_states = []
    RandomRequestExecutor(scope="author:two", save=second_states.append)
    assert second_states[0]["seed"] != saved["seed"]


def test_failed_save_does_not_publish_result_and_retry_reuses_seed():
    saved = []
    fail = False

    def save(state):
        if fail:
            raise OSError("disk unavailable")
        saved.append(deepcopy(state))

    executor = RandomRequestExecutor(scope="author", save=save)
    initial = saved[0]
    fail = True
    with pytest.raises(OSError):
        executor.execute("roll_dice", "roll", {"count": 6, "sides": 20})
    fail = False
    retry = executor.execute("roll_dice", "roll", {"count": 6, "sides": 20})
    restarted = RandomRequestExecutor(scope="author", state=initial)
    assert restarted.execute("roll_dice", "roll", {"count": 6, "sides": 20}) == retry


def test_duplicate_concurrent_calls_commit_once():
    saved = []
    executor = RandomRequestExecutor(scope="author", save=saved.append)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: executor.execute(
                    "shuffle", "order", {"items": list("abcdef")}
                ),
                range(12),
            )
        )
    assert all(result == results[0] for result in results)
    assert len(saved) == 2  # Initial seed plus one committed decision.
