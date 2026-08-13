"""Versioned and atomic persistence primitives for story sessions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from types import MappingProxyType
from typing import Any

from core.sprite.chat_branch_storage import STORY_SESSION_FILENAME

from core.story import (
    CanonFact,
    CastState,
    EffectSpec,
    SemanticSignalState,
    StoryEvent,
    StoryEventReplayer,
    StoryEventType,
    StoryProgram,
    StoryState,
    VariableScope,
    VariableType,
    freeze_mapping,
    freeze_value,
)
from core.story.state import variable_value_is_valid


STORY_SESSION_STORAGE_VERSION = 2
_GLOBAL_PROGRESS_SLUG_LIMIT = 100
_GLOBAL_PROGRESS_HASH_LENGTH = 16
_VARIABLE_EVENT_TYPES = frozenset(
    {
        StoryEventType.VARIABLE_CHANGED,
        StoryEventType.METRIC_CHANGED,
        StoryEventType.SET_VALUE_ADDED,
        StoryEventType.SET_VALUE_REMOVED,
    }
)


class StoryPersistenceError(ValueError):
    pass


class StoryProgramMismatchError(StoryPersistenceError):
    pass


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_json_value(item) for item in value), key=str)
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def story_event_to_payload(event: StoryEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "revision": event.revision,
        "type": event.type.value,
        "payload": _json_value(event.payload),
        "causeCommandId": event.cause_command_id,
    }


def story_event_from_payload(raw: Mapping[str, Any]) -> StoryEvent:
    try:
        event_type = StoryEventType(str(raw["type"]))
        event_id = str(raw["id"])
        revision = int(raw["revision"])
        command_id = str(raw["causeCommandId"])
    except (KeyError, TypeError, ValueError) as error:
        raise StoryPersistenceError("invalid story event payload") from error
    payload = raw.get("payload")
    if (
        not event_id
        or revision < 1
        or not command_id
        or not isinstance(payload, Mapping)
    ):
        raise StoryPersistenceError("invalid story event fields")
    return StoryEvent(
        id=event_id,
        revision=revision,
        type=event_type,
        payload=_restore_event_payload(event_type, payload),
        cause_command_id=command_id,
    )


def story_state_to_payload(state: StoryState) -> dict[str, Any]:
    semantic = state.semantic_signal_state
    cast = state.cast_state
    return {
        "schemaVersion": state.schema_version,
        "storyId": state.story_id,
        "storyVersion": state.story_version,
        "programSourceHash": state.program_source_hash,
        "revision": state.revision,
        "currentNodeId": state.current_node_id,
        "variables": _json_value(state.variables),
        "completedNodeIds": sorted(state.completed_node_ids),
        "failedNodeIds": sorted(state.failed_node_ids),
        "unlockedNodeIds": sorted(state.unlocked_node_ids),
        "canon": [
            {
                "id": fact.id,
                "text": fact.text,
                "sourceEventId": fact.source_event_id,
            }
            for fact in state.canon
        ],
        "semanticSignalState": {
            "sequence": semantic.sequence,
            "usage": dict(semantic.usage),
            "turnId": semantic.turn_id,
            "sceneId": semantic.scene_id,
            "chapterId": semantic.chapter_id,
            "recentFingerprints": [list(item) for item in semantic.recent_fingerprints],
            "acceptedCauseGroups": list(semantic.accepted_cause_groups),
        },
        "castState": {
            "registeredStoryCharacterIds": sorted(cast.registered_story_character_ids),
            "activeCharacterIds": list(cast.active_character_ids),
            "offstageCharacterIds": sorted(cast.offstage_character_ids),
            "storyScopedCharacterIds": sorted(cast.story_scoped_character_ids),
            "adHocCharacterIds": sorted(cast.ad_hoc_character_ids),
            "roleBindings": dict(cast.role_bindings),
            "resolvedForNodeId": cast.resolved_for_node_id,
            "castRevision": cast.cast_revision,
        },
        "eventCursor": state.event_cursor,
    }


def story_state_from_payload(
    raw: Mapping[str, Any],
    *,
    program: StoryProgram,
) -> StoryState:
    if (
        str(raw.get("storyId") or "") != program.story_id
        or int(raw.get("storyVersion") or -1) != program.story_version
        or str(raw.get("programSourceHash") or "") != program.source_hash
    ):
        raise StoryProgramMismatchError(
            "saved story state does not match the compiled StoryProgram"
        )
    variables_raw = _mapping(raw.get("variables"), "variables")
    branch_definitions = {
        definition.id: definition
        for definition in program.variables
        if definition.scope == VariableScope.BRANCH
    }
    variables: dict[str, Any] = {}
    if set(variables_raw) != set(branch_definitions):
        raise StoryPersistenceError("saved branch variables do not match schema")
    for variable_id, definition in branch_definitions.items():
        value = _persisted_variable_value(definition.type, variables_raw[variable_id])
        if not variable_value_is_valid(definition, value):
            raise StoryPersistenceError(
                f"saved value is invalid for branch variable {variable_id!r}"
            )
        variables[variable_id] = value

    semantic_raw = _mapping(
        raw.get("semanticSignalState", {}),
        "semanticSignalState",
    )
    cast_raw = _mapping(raw.get("castState", {}), "castState")
    fingerprints = tuple(
        (str(item[0]), int(item[1]))
        for item in _sequence(
            semantic_raw.get("recentFingerprints", ()),
            "recentFingerprints",
        )
        if isinstance(item, Sequence)
        and not isinstance(item, (str, bytes, bytearray))
        and len(item) == 2
    )
    canon = tuple(
        CanonFact(
            id=str(item.get("id") or ""),
            text=str(item.get("text") or ""),
            source_event_id=str(item.get("sourceEventId") or ""),
        )
        for item in _mapping_sequence(raw.get("canon", ()), "canon")
    )
    state = StoryState(
        schema_version=int(raw.get("schemaVersion") or 1),
        story_id=program.story_id,
        story_version=program.story_version,
        program_source_hash=program.source_hash,
        revision=int(raw.get("revision") or 0),
        current_node_id=str(raw.get("currentNodeId") or ""),
        variables=freeze_mapping(variables),
        completed_node_ids=frozenset(
            str(item)
            for item in _sequence(raw.get("completedNodeIds", ()), "completedNodeIds")
        ),
        failed_node_ids=frozenset(
            str(item)
            for item in _sequence(raw.get("failedNodeIds", ()), "failedNodeIds")
        ),
        unlocked_node_ids=frozenset(
            str(item)
            for item in _sequence(raw.get("unlockedNodeIds", ()), "unlockedNodeIds")
        ),
        canon=canon,
        semantic_signal_state=SemanticSignalState(
            sequence=int(semantic_raw.get("sequence") or 0),
            usage=freeze_mapping(
                _mapping(semantic_raw.get("usage", {}), "semantic usage")
            ),
            turn_id=_optional_text(semantic_raw.get("turnId")),
            scene_id=_optional_text(semantic_raw.get("sceneId")),
            chapter_id=_optional_text(semantic_raw.get("chapterId")),
            recent_fingerprints=fingerprints,
            accepted_cause_groups=tuple(
                str(item)
                for item in _sequence(
                    semantic_raw.get("acceptedCauseGroups", ()),
                    "acceptedCauseGroups",
                )
            ),
        ),
        cast_state=CastState(
            registered_story_character_ids=frozenset(
                str(item)
                for item in _sequence(
                    cast_raw.get("registeredStoryCharacterIds", ()),
                    "registeredStoryCharacterIds",
                )
            ),
            active_character_ids=tuple(
                str(item)
                for item in _sequence(
                    cast_raw.get("activeCharacterIds", ()),
                    "activeCharacterIds",
                )
            ),
            offstage_character_ids=frozenset(
                str(item)
                for item in _sequence(
                    cast_raw.get("offstageCharacterIds", ()),
                    "offstageCharacterIds",
                )
            ),
            story_scoped_character_ids=frozenset(
                str(item)
                for item in _sequence(
                    cast_raw.get("storyScopedCharacterIds", ()),
                    "storyScopedCharacterIds",
                )
            ),
            ad_hoc_character_ids=frozenset(
                str(item)
                for item in _sequence(
                    cast_raw.get("adHocCharacterIds", ()),
                    "adHocCharacterIds",
                )
            ),
            role_bindings=freeze_mapping(
                _mapping(cast_raw.get("roleBindings", {}), "roleBindings")
            ),
            resolved_for_node_id=_optional_text(cast_raw.get("resolvedForNodeId")),
            cast_revision=int(cast_raw.get("castRevision") or 0),
        ),
        event_cursor=int(raw.get("eventCursor") or 0),
    )
    StoryEventReplayer().replay(state, (), program=program)
    return state


@dataclass(slots=True)
class GlobalStoryProgress:
    story_id: str
    story_version: int
    program_source_hash: str
    variables: dict[str, Any]
    unlocked_ending_ids: set[str] = field(default_factory=set)
    applied_outbox_ids: set[str] = field(default_factory=set)
    revision: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "storyId": self.story_id,
            "storyVersion": self.story_version,
            "programSourceHash": self.program_source_hash,
            "variables": _json_value(self.variables),
            "unlockedEndingIds": sorted(self.unlocked_ending_ids),
            "appliedOutboxIds": sorted(self.applied_outbox_ids),
            "revision": self.revision,
        }


@dataclass(slots=True)
class GlobalEffectOutboxEntry:
    id: str
    source_branch_id: str
    source_command_id: str
    effects: tuple[EffectSpec, ...]
    ending_ids: tuple[str, ...] = ()
    applied: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sourceBranchId": self.source_branch_id,
            "sourceCommandId": self.source_command_id,
            "effects": [
                {"op": effect.op, "args": _json_value(effect.args)}
                for effect in self.effects
            ],
            "endingIds": list(self.ending_ids),
            "applied": self.applied,
        }

    @classmethod
    def from_payload(cls, raw: Mapping[str, Any]) -> GlobalEffectOutboxEntry:
        effects = tuple(
            EffectSpec(
                op=str(item.get("op") or ""),
                args=tuple(_sequence(item.get("args", ()), "effect args")),
            )
            for item in _mapping_sequence(raw.get("effects", ()), "effects")
        )
        return cls(
            id=str(raw.get("id") or ""),
            source_branch_id=str(raw.get("sourceBranchId") or ""),
            source_command_id=str(raw.get("sourceCommandId") or ""),
            effects=effects,
            ending_ids=tuple(
                str(item) for item in _sequence(raw.get("endingIds", ()), "endingIds")
            ),
            applied=bool(raw.get("applied", False)),
        )


class JsonStorySessionRepository:
    """Store one v2 story document beside, but separate from, legacy history."""

    def __init__(self, session_root: str | Path) -> None:
        self.session_root = Path(session_root).resolve(strict=False)
        self.path = self.session_root / STORY_SESSION_FILENAME

    def load(self) -> dict[str, Any] | None:
        if not self.path.is_file():
            return None
        try:
            with self.path.open(encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise StoryPersistenceError(
                "story session document is unreadable"
            ) from error
        if not isinstance(payload, dict):
            raise StoryPersistenceError("story session document must be an object")
        if int(payload.get("version") or 0) != STORY_SESSION_STORAGE_VERSION:
            raise StoryPersistenceError("unsupported story session storage version")
        return payload

    def save(self, payload: Mapping[str, Any]) -> None:
        document = dict(payload)
        document["version"] = STORY_SESSION_STORAGE_VERSION
        self.session_root.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.path, document)


class JsonGlobalStoryProgressStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve(strict=False)

    def load(self, program: StoryProgram) -> GlobalStoryProgress:
        path = self._path(program.story_id)
        if not path.is_file():
            variables = {
                definition.id: freeze_value(definition.initial)
                for definition in program.variables
                if definition.scope == VariableScope.GLOBAL
            }
            return GlobalStoryProgress(
                story_id=program.story_id,
                story_version=program.story_version,
                program_source_hash=program.source_hash,
                variables=variables,
            )
        try:
            with path.open(encoding="utf-8") as file:
                raw = json.load(file)
        except (OSError, json.JSONDecodeError) as error:
            raise StoryPersistenceError(
                "global story progress is unreadable"
            ) from error
        if not isinstance(raw, Mapping):
            raise StoryPersistenceError("global story progress must be an object")
        if (
            str(raw.get("storyId") or "") != program.story_id
            or int(raw.get("storyVersion") or -1) != program.story_version
            or str(raw.get("programSourceHash") or "") != program.source_hash
        ):
            raise StoryProgramMismatchError(
                "global story progress belongs to another StoryProgram"
            )
        variables = dict(_mapping(raw.get("variables", {}), "global variables"))
        definitions = {
            definition.id: definition
            for definition in program.variables
            if definition.scope == VariableScope.GLOBAL
        }
        if set(variables) != set(definitions):
            raise StoryPersistenceError("saved global variables do not match schema")
        for variable_id, definition in definitions.items():
            variables[variable_id] = _persisted_variable_value(
                definition.type,
                variables[variable_id],
            )
            if not variable_value_is_valid(definition, variables[variable_id]):
                raise StoryPersistenceError(
                    f"saved value is invalid for global variable {variable_id!r}"
                )
        return GlobalStoryProgress(
            story_id=program.story_id,
            story_version=program.story_version,
            program_source_hash=program.source_hash,
            variables=variables,
            unlocked_ending_ids=set(
                str(item)
                for item in _sequence(
                    raw.get("unlockedEndingIds", ()),
                    "unlockedEndingIds",
                )
            ),
            applied_outbox_ids=set(
                str(item)
                for item in _sequence(
                    raw.get("appliedOutboxIds", ()),
                    "appliedOutboxIds",
                )
            ),
            revision=int(raw.get("revision") or 0),
        )

    def save(self, progress: GlobalStoryProgress) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self._path(progress.story_id), progress.to_payload())

    def _path(self, story_id: str) -> Path:
        return self.root / global_progress_filename(story_id)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(_json_value(payload), file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StoryPersistenceError(f"{label} must be an object")
    return value


def _sequence(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise StoryPersistenceError(f"{label} must be a list")
    return value


def _mapping_sequence(value: Any, label: str) -> tuple[Mapping[str, Any], ...]:
    sequence = _sequence(value, label)
    if not all(isinstance(item, Mapping) for item in sequence):
        raise StoryPersistenceError(f"{label} must contain objects")
    return tuple(item for item in sequence if isinstance(item, Mapping))


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _persisted_variable_value(variable_type: Any, value: Any) -> Any:
    if variable_type in {VariableType.STRING_SET, VariableType.NODE_SET}:
        return frozenset(str(item) for item in _sequence(value, "set variable"))
    return freeze_value(value)


def _restore_event_variable_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes, bytearray)):
        return frozenset(str(item) for item in value)
    return freeze_value(value)


def _restore_event_payload(
    event_type: StoryEventType,
    payload: Mapping[str, Any],
) -> Mapping[str, Any]:
    restored = dict(payload)
    if event_type in _VARIABLE_EVENT_TYPES:
        for key in ("previous", "current"):
            if key in restored:
                restored[key] = _restore_event_variable_value(restored[key])
    return freeze_mapping(restored)


def global_progress_filename(story_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", story_id).strip(".-")
    if not slug:
        raise StoryPersistenceError("story id cannot map to an empty filename")
    if len(slug) > _GLOBAL_PROGRESS_SLUG_LIMIT:
        digest = hashlib.sha256(story_id.encode("utf-8")).hexdigest()[
            :_GLOBAL_PROGRESS_HASH_LENGTH
        ]
        prefix_len = _GLOBAL_PROGRESS_SLUG_LIMIT - _GLOBAL_PROGRESS_HASH_LENGTH - 1
        slug = f"{slug[:prefix_len]}-{digest}"
    return f"{slug}.json"
