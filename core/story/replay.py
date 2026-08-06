"""Pure projection of domain events back into authoritative story state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

from .events import StoryEvent, StoryEventType
from .state import (
    CanonFact,
    CastState,
    SemanticSignalState,
    StoryState,
    freeze_mapping,
    freeze_value,
)


class StoryEventReplayError(ValueError):
    """Raised when an event stream is not contiguous or internally consistent."""


class StoryEventReplayer:
    """Rebuild a snapshot from an earlier snapshot plus contiguous domain events."""

    def replay(
        self,
        initial: StoryState,
        events: Iterable[StoryEvent],
    ) -> StoryState:
        variables = dict(initial.variables)
        completed = set(initial.completed_node_ids)
        failed = set(initial.failed_node_ids)
        unlocked = set(initial.unlocked_node_ids)
        canon = list(initial.canon)
        current_node_id = initial.current_node_id
        semantic_sequence = initial.semantic_signal_state.sequence
        semantic_usage = dict(initial.semantic_signal_state.usage)
        fingerprints = list(initial.semantic_signal_state.recent_fingerprints)
        cause_groups = list(initial.semantic_signal_state.accepted_cause_groups)
        active_cast = tuple(initial.cast_state.active_character_ids)
        role_bindings = dict(initial.cast_state.role_bindings)
        resolved_for_node_id = initial.cast_state.resolved_for_node_id
        cast_revision = initial.cast_state.cast_revision
        event_cursor = initial.event_cursor
        revision = initial.revision
        processed = list(initial.processed_command_ids)
        group_revision: int | None = None
        group_command_id: str | None = None

        for event in events:
            expected_cursor = event_cursor + 1
            if event.id != f"event-{event.revision}-{expected_cursor}":
                raise StoryEventReplayError(
                    f"event {event.id!r} is not the expected cursor {expected_cursor}"
                )
            if group_revision is None:
                if event.revision != revision + 1:
                    raise StoryEventReplayError(
                        f"event revision {event.revision} does not follow {revision}"
                    )
                group_revision = event.revision
                group_command_id = event.cause_command_id
            elif event.revision != group_revision:
                revision, processed = self._finish_group(
                    revision,
                    processed,
                    group_revision,
                    group_command_id,
                )
                if event.revision != revision + 1:
                    raise StoryEventReplayError(
                        f"event revision {event.revision} does not follow {revision}"
                    )
                group_revision = event.revision
                group_command_id = event.cause_command_id
            elif event.cause_command_id != group_command_id:
                raise StoryEventReplayError(
                    "events in one revision must share a cause command"
                )

            payload = event.payload
            event_cursor = expected_cursor
            if event.type in {
                StoryEventType.COMMAND_PROCESSED,
                StoryEventType.CHOICE_SELECTED,
                StoryEventType.INTENT_PERFORMED,
                StoryEventType.SEMANTIC_SIGNAL_REJECTED,
                StoryEventType.ENDING_REACHED,
            }:
                continue
            if event.type == StoryEventType.STORY_STARTED:
                if payload.get("storyId") != initial.story_id:
                    raise StoryEventReplayError("StoryStarted targets another story")
            elif event.type in {
                StoryEventType.VARIABLE_CHANGED,
                StoryEventType.METRIC_CHANGED,
                StoryEventType.SET_VALUE_ADDED,
                StoryEventType.SET_VALUE_REMOVED,
            }:
                variables[str(payload["variableId"])] = freeze_value(payload["current"])
            elif event.type == StoryEventType.NODE_UNLOCKED:
                unlocked.add(str(payload["nodeId"]))
            elif event.type == StoryEventType.NODE_ENTERED:
                current_node_id = str(payload["nodeId"])
            elif event.type == StoryEventType.NODE_COMPLETED:
                completed.add(str(payload["nodeId"]))
            elif event.type == StoryEventType.CANON_APPENDED:
                canon.append(
                    CanonFact(
                        id=str(payload.get("canonId", f"canon-{event_cursor}")),
                        text=str(payload["text"]),
                        source_event_id=event.id,
                    )
                )
            elif event.type == StoryEventType.CAST_RESOLVED:
                active_cast = tuple(str(item) for item in payload["activeCharacterIds"])
                role_bindings = {
                    str(key): str(value)
                    for key, value in self._mapping(payload["roleBindings"]).items()
                }
                resolved_for_node_id = str(payload["nodeId"])
                cast_revision += 1
            elif event.type == StoryEventType.SEMANTIC_SIGNAL_ACCEPTED:
                semantic_sequence += 1
                signal_id = str(payload["signalId"])
                fingerprint = str(payload["fingerprint"])
                cause_group = str(payload["causeGroup"])
                fingerprints.append((f"{signal_id}:{fingerprint}", semantic_sequence))
                cause_groups.append(cause_group)
                for scope, key in (
                    ("turn", "turnId"),
                    ("scene", "sceneId"),
                    ("chapter", "chapterId"),
                ):
                    usage_key = f"{scope}:{payload[key]}:{signal_id}"
                    semantic_usage[usage_key] = semantic_usage.get(usage_key, 0) + 1
            else:  # pragma: no cover - protects future event additions
                raise StoryEventReplayError(
                    f"unsupported event type {event.type.value!r}"
                )

        if group_revision is not None:
            revision, processed = self._finish_group(
                revision,
                processed,
                group_revision,
                group_command_id,
            )

        minimum_sequence = max(0, semantic_sequence - 256)
        semantic_state = SemanticSignalState(
            sequence=semantic_sequence,
            usage=freeze_mapping(semantic_usage),
            recent_fingerprints=tuple(
                item for item in fingerprints if item[1] >= minimum_sequence
            )[-256:],
            accepted_cause_groups=tuple(cause_groups[-256:]),
        )
        registered = initial.cast_state.registered_story_character_ids
        cast_state = CastState(
            registered_story_character_ids=registered,
            active_character_ids=active_cast,
            offstage_character_ids=registered.difference(active_cast),
            story_scoped_character_ids=initial.cast_state.story_scoped_character_ids,
            ad_hoc_character_ids=initial.cast_state.ad_hoc_character_ids,
            role_bindings=freeze_mapping(role_bindings),
            resolved_for_node_id=resolved_for_node_id,
            cast_revision=cast_revision,
        )
        return replace(
            initial,
            revision=revision,
            current_node_id=current_node_id,
            variables=freeze_mapping(variables),
            completed_node_ids=frozenset(completed),
            failed_node_ids=frozenset(failed),
            unlocked_node_ids=frozenset(unlocked),
            canon=tuple(canon),
            semantic_signal_state=semantic_state,
            cast_state=cast_state,
            event_cursor=event_cursor,
            processed_command_ids=tuple(processed),
        )

    @staticmethod
    def _finish_group(
        revision: int,
        processed: list[str],
        group_revision: int,
        command_id: str | None,
    ) -> tuple[int, list[str]]:
        if group_revision != revision + 1 or not command_id:
            raise StoryEventReplayError("invalid event revision group")
        if command_id in processed:
            raise StoryEventReplayError(f"command {command_id!r} was already processed")
        return group_revision, [*processed, command_id][-256:]

    @staticmethod
    def _mapping(value: Any) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise StoryEventReplayError("event payload value must be a mapping")
        return value
