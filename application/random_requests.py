"""Host-owned, replayable random requests, reusable by authoring and sessions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import copy
import hashlib
import json
import random
import secrets
import threading
from typing import Any

from core.randomness import (
    RandomRequestError,
    execute_random_request,
    validate_random_request,
)


class RandomRequestExecutor:
    """The caller owns scope, storage, and its lifecycle; tools cannot pick a seed.

    Save must commit atomically or raise. Hosts must serialize access to a scope
    across executor instances. A future game session uses its own scope/store,
    never the author's records. This class does not expose secrets to chat.
    """

    def __init__(
        self,
        *,
        scope: str,
        state: Mapping[str, Any] | None = None,
        save: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._save = save or (lambda state: None)
        self._lock = threading.RLock()
        self._state = (
            copy.deepcopy(dict(state))
            if state is not None
            else {
                "version": 1,
                "scope": scope,
                "seed": secrets.token_hex(32),
                "requests": {},
            }
        )
        if (
            self._state.get("version") != 1
            or self._state.get("scope") != scope
            or not isinstance(self._state.get("seed"), str)
            or len(self._state["seed"]) != 64
            or not isinstance(self._state.get("requests"), dict)
        ):
            raise ValueError("invalid random request checkpoint or mismatched scope")
        if state is None:
            self._save(copy.deepcopy(self._state))

    def resolved_requests(self) -> dict[str, Any]:
        """Author-only context for later stages and retries; never includes the seed."""
        with self._lock:
            return copy.deepcopy(self._state["requests"])

    def execute(
        self, operation: str, request_id: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        if (
            not isinstance(request_id, str)
            or not request_id.strip()
            or len(request_id) > 128
        ):
            raise RandomRequestError("invalid random request ID")
        args = validate_random_request(operation, arguments)
        request = {"operation": operation, "arguments": args}
        with self._lock:
            records = self._state["requests"]
            if request_id in records:
                record = records[request_id]
                if record.get("request") != request:
                    raise RandomRequestError(
                        "requestId already belongs to a different decision"
                    )
                return copy.deepcopy(record["result"])
            if len(records) >= 128:
                raise RandomRequestError("random request limit reached for this scope")
            # Stable across retries even if saving the result is interrupted.
            seed = hashlib.sha256(
                json.dumps(
                    [self._state["seed"], self._state["scope"], request_id, request],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).digest()
            result = execute_random_request(operation, args, source=random.Random(seed))
            next_state = copy.deepcopy(self._state)
            next_state["requests"][request_id] = {"request": request, "result": result}
            self._save(copy.deepcopy(next_state))
            self._state = next_state
            return copy.deepcopy(result)
