"""Tier-0 raw ingestion buffer (`PerceptionRawBuffer`) for high-frequency perception inputs.

Game mods, plugins, and frontend screen-share frames write into this thread-safe
buffer at arbitrary rates. Continuous state payloads use latest-wins dictionary
merging per `(source, game)`, discrete events append to a bounded ring buffer,
and visual frames overwrite a single latest-frame slot so stale frames never
pile up behind local VLM inference.
"""

from __future__ import annotations

from collections import deque
import copy
import threading
import time
from typing import Any, Mapping

from core.perception.models import (
    PerceptionEvent,
    PerceptionFrame,
    RawPerceptionSnapshot,
)

DEFAULT_MAX_RAW_EVENTS = 64
DEFAULT_MAX_STATE_SOURCES = 16


def _merge_state_dict(
    target: dict[str, Any],
    patch: Mapping[str, Any],
    *,
    depth: int = 0,
    max_depth: int = 3,
) -> dict[str, Any]:
    """Recursively merge nested JSON game-state dictionaries up to `max_depth`."""
    for key, value in patch.items():
        clean_key = str(key)[:128]
        if (
            depth < max_depth
            and isinstance(value, Mapping)
            and isinstance(target.get(clean_key), dict)
        ):
            _merge_state_dict(
                target[clean_key],
                value,
                depth=depth + 1,
                max_depth=max_depth,
            )
        else:
            target[clean_key] = copy.deepcopy(value)
    return target


class PerceptionRawBuffer:
    """Thread-safe Tier-0 raw perception buffer (state merge + event ring + latest frame)."""

    def __init__(
        self,
        *,
        max_events: int = DEFAULT_MAX_RAW_EVENTS,
        max_state_sources: int = DEFAULT_MAX_STATE_SOURCES,
    ) -> None:
        self._max_events = max(8, int(max_events))
        self._max_state_sources = max(2, int(max_state_sources))
        self._lock = threading.RLock()
        self._states: dict[str, dict[str, Any]] = {}
        self._dirty_state_keys: set[str] = set()
        self._events: deque[PerceptionEvent] = deque(maxlen=self._max_events)
        self._latest_frame: PerceptionFrame | None = None
        self._frame_dirty: bool = False
        self._revision: int = 0
        self._last_ingested_at: float = 0.0

    @staticmethod
    def _state_key(source: str, game: str) -> str:
        clean_source = (str(source or "plugin").strip() or "plugin")[:64]
        clean_game = str(game or "").strip()[:64]
        return f"{clean_source}:{clean_game}"

    def ingest_state(
        self,
        state: Mapping[str, Any],
        *,
        source: str = "plugin",
        game: str = "",
        replace: bool = False,
    ) -> int:
        """Merge or replace structured game state for `(source, game)`."""
        if not isinstance(state, Mapping) or not state:
            with self._lock:
                return self._revision
        key = self._state_key(source, game)
        with self._lock:
            if key not in self._states and len(self._states) >= self._max_state_sources:
                oldest_key = next(iter(self._states))
                self._states.pop(oldest_key, None)
                self._dirty_state_keys.discard(oldest_key)
            if replace or key not in self._states:
                self._states[key] = copy.deepcopy(dict(state))
            else:
                _merge_state_dict(self._states[key], state)
            self._dirty_state_keys.add(key)
            self._revision += 1
            self._last_ingested_at = time.time()
            return self._revision

    def ingest_event(
        self,
        event_type: str,
        data: Mapping[str, Any] | None = None,
        *,
        source: str = "plugin",
        game: str = "",
        timestamp: float | None = None,
    ) -> int:
        """Append one discrete game event into the bounded ring buffer."""
        clean_type = str(event_type or "").strip()[:120]
        if not clean_type:
            with self._lock:
                return self._revision
        payload = copy.deepcopy(dict(data)) if isinstance(data, Mapping) else {}
        item = PerceptionEvent(
            event_type=clean_type,
            data=payload,
            source=(str(source or "plugin").strip() or "plugin")[:64],
            game=str(game or "").strip()[:64],
            timestamp=float(timestamp) if timestamp is not None else time.time(),
        )
        with self._lock:
            self._events.append(item)
            self._revision += 1
            self._last_ingested_at = item.timestamp
            return self._revision

    def ingest_frame(self, frame: PerceptionFrame) -> int:
        """Store the newest visual frame, overwriting any unconsumed older frame."""
        if not frame.image_base64 or not frame.image_base64.strip():
            with self._lock:
                return self._revision
        with self._lock:
            if (
                self._latest_frame is not None and self._latest_frame.source == frame.source
                and frame.captured_at < self._latest_frame.captured_at
            ):
                return self._revision
            self._latest_frame = frame
            self._frame_dirty = True
            self._revision += 1
            self._last_ingested_at = frame.captured_at
            return self._revision

    def has_dirty(self) -> bool:
        """Return whether new state, events, or a fresh frame await local digestion."""
        with self._lock:
            return bool(self._dirty_state_keys or self._events or self._frame_dirty)

    def discard_frame(self, source: str) -> None:
        with self._lock:
            if self._latest_frame is not None and self._latest_frame.source == source:
                self._latest_frame = None
                self._frame_dirty = False

    def drain_snapshot(self, *, include_all_states: bool = True) -> RawPerceptionSnapshot:
        """Atomically drain dirty events/frame and capture current merged game states."""
        with self._lock:
            has_work = bool(self._dirty_state_keys or self._events or self._frame_dirty)
            if not has_work:
                return RawPerceptionSnapshot(
                    states={},
                    events=(),
                    frame=None,
                    revision=self._revision,
                )
            if include_all_states:
                states_copy = copy.deepcopy(self._states)
            else:
                states_copy = {
                    k: copy.deepcopy(self._states[k])
                    for k in self._dirty_state_keys
                    if k in self._states
                }
            events_copy = tuple(self._events)
            frame_copy = self._latest_frame if self._frame_dirty else None

            self._dirty_state_keys.clear()
            self._events.clear()
            self._frame_dirty = False
            rev = self._revision

        return RawPerceptionSnapshot(
            states=states_copy,
            events=events_copy,
            frame=frame_copy,
            revision=rev,
        )

    def clear(self) -> None:
        """Reset all buffered states, queued events, and frames."""
        with self._lock:
            self._states.clear()
            self._dirty_state_keys.clear()
            self._events.clear()
            self._latest_frame = None
            self._frame_dirty = False
            self._revision += 1

    def stats(self) -> dict[str, Any]:
        """Return lightweight buffer diagnostics without exposing large frame bytes."""
        with self._lock:
            return {
                "revision": self._revision,
                "stateSourceCount": len(self._states),
                "dirtyStateCount": len(self._dirty_state_keys),
                "pendingEventCount": len(self._events),
                "hasPendingFrame": self._frame_dirty,
                "lastIngestedAt": self._last_ingested_at or None,
            }
