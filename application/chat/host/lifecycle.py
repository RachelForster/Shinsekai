"""Serialize chat launch and stop operations sharing one bridge state."""

from __future__ import annotations

import threading
from typing import Any


_lock_creation_guard = threading.Lock()


def chat_lifecycle_lock(state: Any) -> threading.RLock:
    # Older integrations can provide a lightweight state instead of BridgeState.
    with _lock_creation_guard:
        lock = getattr(state, "chat_lifecycle_lock", None)
        if lock is None:
            lock = threading.RLock()
            state.chat_lifecycle_lock = lock
        return lock
