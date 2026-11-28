"""Thread-safe waiter registry for realtime chat command acknowledgements."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import threading
from typing import Any


@dataclass
class _PendingCommandAck:
    command_id: str
    done: threading.Event = field(default_factory=threading.Event)
    payload: dict[str, Any] = field(default_factory=dict)


class CommandAckRegistry:
    """Correlate outgoing ``cmdId`` commands with incoming ``cmd.ack`` events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, _PendingCommandAck] = {}

    def register(self, command_id: str) -> str:
        cid = str(command_id or "").strip()
        if not cid:
            raise ValueError("command_id must not be empty")
        with self._lock:
            self._pending[cid] = _PendingCommandAck(command_id=cid)
        return cid

    def resolve(self, event: Mapping[str, Any]) -> bool:
        cid = str(event.get("cmdId") or "").strip()
        if not cid:
            return False
        with self._lock:
            waiter = self._pending.get(cid)
            if waiter is None:
                return False
            waiter.payload = dict(event)
            waiter.done.set()
        return True

    def wait(self, command_id: str, *, timeout: float = 5.0) -> dict[str, Any] | None:
        cid = str(command_id or "").strip()
        if not cid:
            return None
        with self._lock:
            waiter = self._pending.get(cid)
        if waiter is None:
            return None
        completed = waiter.done.wait(timeout=max(0.0, float(timeout)))
        with self._lock:
            self._pending.pop(cid, None)
            return dict(waiter.payload) if completed else None

    def discard(self, command_id: str) -> None:
        cid = str(command_id or "").strip()
        if not cid:
            return
        with self._lock:
            self._pending.pop(cid, None)

    def cancel_all(self, reason: str = "Session disconnected") -> None:
        with self._lock:
            waiters = list(self._pending.values())
        for waiter in waiters:
            if not waiter.done.is_set():
                waiter.payload = {
                    "type": "cmd.ack",
                    "cmdId": waiter.command_id,
                    "ok": False,
                    "disconnected": True,
                    "error": str(reason or "Session disconnected"),
                }
                waiter.done.set()


__all__ = ["CommandAckRegistry"]
