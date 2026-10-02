"""Optional process-local notifications; never a substitute for required cleanup."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sdk.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ChatLifecycleEvent:
    kind: Literal["ready", "stopped", "failed"]
    session_id: str


class ChatLifecycle:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._observers: list[Callable[[ChatLifecycleEvent], None]] = []

    def register(self, observer: Callable[[ChatLifecycleEvent], None]) -> Callable[[], None]:
        # A separate entry lets the same callable be registered/unregistered independently.
        def entry(event: ChatLifecycleEvent) -> None:
            observer(event)
        with self._lock:
            self._observers.append(entry)

        def unregister() -> None:
            with self._lock:
                if entry in self._observers:
                    self._observers.remove(entry)

        return unregister

    def notify(self, event: ChatLifecycleEvent) -> None:
        with self._lock:
            observers = tuple(self._observers)
        for observer in observers:
            try:
                observer(event)
            except Exception:
                logger.exception("Chat lifecycle observer failed", extra={"kind": event.kind})
