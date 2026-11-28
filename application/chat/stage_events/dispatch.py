"""Registry assembly and stage-event snapshot dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from . import (
    audio_effects,
    capabilities_plugins,
    dialog_interaction,
    input_perception,
    session_lifecycle,
    visuals,
)
from .snapshot import (
    EventDict,
    EventFoldSpec,
    SnapshotDict,
    advance_event_seq,
    clear_transient_notification_state,
    normalize_snapshot_defaults,
)


def build_event_registry(
    *tables: Mapping[str, EventFoldSpec],
) -> MappingProxyType[str, EventFoldSpec]:
    """Merge domain handler tables into an immutable registry, rejecting duplicates."""
    merged: dict[str, EventFoldSpec] = {}
    for table in tables:
        for event_type, spec in table.items():
            if event_type in merged:
                raise ValueError(f"Duplicate stage event handler: {event_type}")
            merged[event_type] = spec
    return MappingProxyType(merged)


STAGE_EVENT_REGISTRY: MappingProxyType[str, EventFoldSpec] = build_event_registry(
    visuals.HANDLERS,
    audio_effects.HANDLERS,
    dialog_interaction.HANDLERS,
    session_lifecycle.HANDLERS,
    input_perception.HANDLERS,
    capabilities_plugins.HANDLERS,
)


def fold_event_into_snapshot(
    snapshot: SnapshotDict, event: EventDict
) -> SnapshotDict:
    """Fold one chat stage event into a ChatSnapshot-like dict."""
    event_type = str(event.get("type") or "").strip()
    next_snapshot = normalize_snapshot_defaults(snapshot)
    spec = STAGE_EVENT_REGISTRY.get(event_type)
    if spec is None:
        advance_event_seq(next_snapshot, event)
        return next_snapshot

    if not spec.bypass_seq_advance:
        advance_event_seq(next_snapshot, event)
    if spec.clear_transient_notice:
        clear_transient_notification_state(next_snapshot)

    replaced = spec.handler(next_snapshot, event)
    return next_snapshot if replaced is None else replaced
