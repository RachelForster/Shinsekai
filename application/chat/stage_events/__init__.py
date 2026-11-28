"""Modular stage-event folding, registry, and replay projection contracts."""

from __future__ import annotations

from .dispatch import STAGE_EVENT_REGISTRY, build_event_registry, fold_event_into_snapshot
from .replay_projection import REPLAY_OBSERVED_EVENTS, project_replay_frame
from .snapshot import (
    PRESENTATION_KEYS,
    EventFoldSpec,
    make_empty_chat_snapshot,
)

__all__ = [
    "EventFoldSpec",
    "PRESENTATION_KEYS",
    "REPLAY_OBSERVED_EVENTS",
    "STAGE_EVENT_REGISTRY",
    "build_event_registry",
    "fold_event_into_snapshot",
    "make_empty_chat_snapshot",
    "project_replay_frame",
]
