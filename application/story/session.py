"""Feature-gated story session orchestration, branching, and crash recovery."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import threading
from types import MappingProxyType
from typing import Any

from config.feature_flags import FeatureFlag, FeatureFlagConfigManager
from core.story import (
    EffectSpec,
    RuntimeCommand,
    StartStory,
    StoryEvent,
    StoryEventReplayer,
    StoryEventType,
    StoryProgram,
    StoryRuntime,
    StoryState,
    VariableScope,
    VariableType,
    freeze_value,
)
from core.story.state import variable_value_is_valid

from .idempotency import StoryCommandIdempotencyIndex
from .persistence import (
    GlobalEffectOutboxEntry,
    GlobalStoryProgress,
    JsonGlobalStoryProgressStore,
    JsonStorySessionRepository,
    StoryPersistenceError,
    StoryProgramMismatchError,
    story_event_from_payload,
    story_event_to_payload,
    story_state_from_payload,
    story_state_to_payload,
)
from .protocol import story_chat_snapshot, story_event_messages, story_state_view


FailureInjector = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class CausalStoryEvent:
    id: str
    parent_event_id: str | None
    event: StoryEvent

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parentEventId": self.parent_event_id,
            "event": story_event_to_payload(self.event),
        }


@dataclass(slots=True)
class StoryCheckpoint:
    generation: int
    message_count: int
    state: StoryState
    head_event_id: str | None
    event_count: int
    history_entries: tuple[Mapping[str, Any], ...] = ()
    idempotency_payload: tuple[Mapping[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "messageCount": self.message_count,
            "state": story_state_to_payload(self.state),
            "headEventId": self.head_event_id,
            "eventCount": self.event_count,
            "historyEntries": [dict(item) for item in self.history_entries],
            "idempotency": [dict(item) for item in self.idempotency_payload],
        }


@dataclass(slots=True)
class StoryBranch:
    id: str
    parent_id: str | None
    generation: int
    state: StoryState
    head_event_id: str | None
    events: list[CausalStoryEvent] = field(default_factory=list)
    checkpoints: list[StoryCheckpoint] = field(default_factory=list)
    idempotency: StoryCommandIdempotencyIndex = field(
        default_factory=StoryCommandIdempotencyIndex
    )
    history_entries: tuple[Mapping[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parentId": self.parent_id,
            "generation": self.generation,
            "state": story_state_to_payload(self.state),
            "headEventId": self.head_event_id,
            "events": [item.to_payload() for item in self.events],
            "checkpoints": [item.to_payload() for item in self.checkpoints],
            "idempotency": self.idempotency.to_payload(),
            "historyEntries": [dict(item) for item in self.history_entries],
        }


@dataclass(frozen=True, slots=True)
class StorySessionAck:
    command_id: str
    branch_id: str
    generation: int
    revision: int
    event_ids: tuple[str, ...]
    head_event_id: str | None
    duplicate: bool
    story: Mapping[str, Any]
    presentation_events: tuple[Mapping[str, Any], ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "commandId": self.command_id,
            "branchId": self.branch_id,
            "generation": self.generation,
            "revision": self.revision,
            "eventIds": list(self.event_ids),
            "headEventId": self.head_event_id,
            "duplicate": self.duplicate,
            "story": dict(self.story),
            "presentationEvents": [dict(item) for item in self.presentation_events],
        }

    @classmethod
    def from_payload(
        cls,
        raw: Mapping[str, Any],
        *,
        duplicate: bool,
    ) -> StorySessionAck:
        story = raw.get("story")
        events = raw.get("presentationEvents")
        event_ids = raw.get("eventIds")
        if (
            not isinstance(story, Mapping)
            or not isinstance(events, Sequence)
            or isinstance(events, (str, bytes, bytearray))
            or not isinstance(event_ids, Sequence)
            or isinstance(event_ids, (str, bytes, bytearray))
        ):
            raise StoryPersistenceError("stored command ack is invalid")
        return cls(
            command_id=str(raw.get("commandId") or ""),
            branch_id=str(raw.get("branchId") or ""),
            generation=int(raw.get("generation") or 0),
            revision=int(raw.get("revision") or 0),
            event_ids=tuple(str(item) for item in event_ids),
            head_event_id=_optional_text(raw.get("headEventId")),
            duplicate=duplicate,
            story=MappingProxyType(dict(story)),
            presentation_events=tuple(
                MappingProxyType(dict(item))
                for item in events
                if isinstance(item, Mapping)
            ),
        )


class StorySession:
    """Own the branch-local runtime while global progress remains monotonic."""

    def __init__(
        self,
        runtime: StoryRuntime,
        flags: FeatureFlagConfigManager,
        *,
        global_progress: GlobalStoryProgress,
        repository: JsonStorySessionRepository | None = None,
        global_store: JsonGlobalStoryProgressStore | None = None,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        flags.require(FeatureFlag.STORY_SYSTEM)
        self.runtime = runtime
        self.flags = flags
        self.global_progress = global_progress
        self.repository = repository
        self.global_store = global_store
        self.failure_injector = failure_injector or (lambda _point: None)
        self.active_branch_id = "main"
        self.branches: dict[str, StoryBranch] = {}
        self.outbox: list[GlobalEffectOutboxEntry] = []
        self.owner_history_path = ""
        self._lock = threading.RLock()

    @classmethod
    def create(
        cls,
        runtime: StoryRuntime,
        flags: FeatureFlagConfigManager,
        *,
        command_id: str,
        repository: JsonStorySessionRepository | None = None,
        global_store: JsonGlobalStoryProgressStore | None = None,
        history_entries: Sequence[Mapping[str, Any]] = (),
        failure_injector: FailureInjector | None = None,
    ) -> StorySession:
        flags.require(FeatureFlag.STORY_SYSTEM)
        progress = (
            global_store.load(runtime.program)
            if global_store is not None
            else _initial_global_progress(runtime.program)
        )
        session = cls(
            runtime,
            flags,
            global_progress=progress,
            repository=repository,
            global_store=global_store,
            failure_injector=failure_injector,
        )
        command = StartStory(command_id)
        result = runtime.start(command, global_variables=progress.variables)
        branch = StoryBranch(
            id="main",
            parent_id=None,
            generation=0,
            state=result.state,
            head_event_id=None,
            history_entries=_history_entries(history_entries),
        )
        session.branches[branch.id] = branch
        session._commit_result(branch, command, result.events, result.global_effects)
        return session

    @classmethod
    def recover(
        cls,
        runtime: StoryRuntime,
        flags: FeatureFlagConfigManager,
        *,
        repository: JsonStorySessionRepository,
        global_store: JsonGlobalStoryProgressStore,
        failure_injector: FailureInjector | None = None,
    ) -> StorySession:
        flags.require(FeatureFlag.STORY_SYSTEM)
        raw = repository.load()
        if raw is None:
            raise FileNotFoundError(repository.path)
        if (
            str(raw.get("storyId") or "") != runtime.program.story_id
            or int(raw.get("storyVersion") or -1) != runtime.program.story_version
            or str(raw.get("programSourceHash") or "") != runtime.program.source_hash
        ):
            raise StoryProgramMismatchError(
                "saved story session does not match the compiled StoryProgram"
            )
        progress = global_store.load(runtime.program)
        session = cls(
            runtime,
            flags,
            global_progress=progress,
            repository=repository,
            global_store=global_store,
            failure_injector=failure_injector,
        )
        session.active_branch_id = str(raw.get("activeBranchId") or "")
        branches_raw = raw.get("branches")
        outbox_raw = raw.get("globalEffectOutbox", ())
        if not isinstance(branches_raw, Mapping) or not isinstance(outbox_raw, list):
            raise StoryPersistenceError("invalid story session document")
        session.branches = {
            str(branch_id): session._branch_from_payload(branch_raw)
            for branch_id, branch_raw in branches_raw.items()
            if isinstance(branch_raw, Mapping)
        }
        if session.active_branch_id not in session.branches:
            raise StoryPersistenceError("active story branch does not exist")
        session.outbox = [
            GlobalEffectOutboxEntry.from_payload(item)
            for item in outbox_raw
            if isinstance(item, Mapping)
        ]
        session._validate_all_branches()
        session.flush_global_outbox()
        return session

    @property
    def active_branch(self) -> StoryBranch:
        self._require_enabled()
        return self.branches[self.active_branch_id]

    def execute(
        self,
        command: RuntimeCommand,
        *,
        history_entries: Sequence[Mapping[str, Any]] | None = None,
    ) -> StorySessionAck:
        with self._lock:
            self._require_enabled()
            branch = self.active_branch
            duplicate = branch.idempotency.lookup(command)
            if duplicate is not None:
                return StorySessionAck.from_payload(duplicate.ack, duplicate=True)
            result = self.runtime.execute(
                branch.state,
                command,
                global_variables=self.global_progress.variables,
            )
            if history_entries is not None:
                branch.history_entries = _history_entries(history_entries)
            return self._commit_result(
                branch,
                command,
                result.events,
                result.global_effects,
                state=result.state,
            )

    def checkpoint_generation_before_user_index(self, user_index: int) -> int:
        with self._lock:
            self._require_enabled()
            branch = self.active_branch
            prefix = len(branch.history_entries)
            seen = 0
            for index, entry in enumerate(branch.history_entries):
                if str(entry.get("role") or "") != "user":
                    continue
                if seen == user_index:
                    prefix = index
                    break
                seen += 1
            for checkpoint in reversed(branch.checkpoints):
                if checkpoint.message_count <= prefix:
                    return checkpoint.generation
            if not branch.checkpoints:
                raise KeyError("story branch has no checkpoint")
            return branch.checkpoints[0].generation

    def fork(self, branch_id: str, *, generation: int | None = None) -> StoryBranch:
        with self._lock:
            self._require_enabled()
            branch_id = _branch_id(branch_id)
            if branch_id in self.branches:
                raise ValueError(f"story branch {branch_id!r} already exists")
            source = self.active_branch
            checkpoint = self._checkpoint(
                source,
                source.generation if generation is None else generation,
            )
            forked = StoryBranch(
                id=branch_id,
                parent_id=source.id,
                generation=checkpoint.generation,
                state=checkpoint.state,
                head_event_id=checkpoint.head_event_id,
                events=list(source.events[: checkpoint.event_count]),
                checkpoints=[
                    item
                    for item in source.checkpoints
                    if item.generation <= checkpoint.generation
                ],
                idempotency=StoryCommandIdempotencyIndex.from_payload(
                    list(checkpoint.idempotency_payload)
                ),
                history_entries=checkpoint.history_entries,
            )
            self.branches[branch_id] = forked
            self.active_branch_id = branch_id
            self._save()
            return forked

    def restore_generation(self, generation: int) -> StoryBranch:
        with self._lock:
            self._require_enabled()
            branch = self.active_branch
            checkpoint = self._checkpoint(branch, generation)
            branch.generation = checkpoint.generation
            branch.state = checkpoint.state
            branch.head_event_id = checkpoint.head_event_id
            del branch.events[checkpoint.event_count :]
            branch.checkpoints = [
                item for item in branch.checkpoints if item.generation <= generation
            ]
            branch.idempotency = StoryCommandIdempotencyIndex.from_payload(
                list(checkpoint.idempotency_payload)
            )
            branch.history_entries = checkpoint.history_entries
            self._save()
            return branch

    def switch_branch(self, branch_id: str) -> StoryBranch:
        with self._lock:
            self._require_enabled()
            if branch_id not in self.branches:
                raise KeyError(f"story branch {branch_id!r} does not exist")
            self.active_branch_id = branch_id
            self._save()
            return self.active_branch

    def chat_snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._require_enabled()
            view = story_state_view(
                self.runtime.program,
                self.active_branch.state,
                self.global_progress,
            )
            return story_chat_snapshot(view)

    def to_payload(self) -> dict[str, Any]:
        with self._lock:
            self._require_enabled()
            return {
                "activeBranchId": self.active_branch_id,
                "storyId": self.runtime.program.story_id,
                "storyVersion": self.runtime.program.story_version,
                "programSourceHash": self.runtime.program.source_hash,
                "branches": {
                    branch_id: branch.to_payload()
                    for branch_id, branch in sorted(self.branches.items())
                },
                "globalEffectOutbox": [item.to_payload() for item in self.outbox],
            }

    def flush_global_outbox(self) -> None:
        with self._lock:
            self._require_enabled()
            changed = False
            for entry in self.outbox:
                if entry.applied:
                    continue
                if entry.id not in self.global_progress.applied_outbox_ids:
                    self._apply_global_entry(entry)
                    if self.global_store is not None:
                        self.global_store.save(self.global_progress)
                    self.failure_injector("after_global_apply")
                entry.applied = True
                changed = True
                self._save()
            if changed:
                self.outbox = [item for item in self.outbox if not item.applied][-256:]
                self._save()

    def _commit_result(
        self,
        branch: StoryBranch,
        command: StartStory | RuntimeCommand,
        events: tuple[StoryEvent, ...],
        global_effects: tuple[EffectSpec, ...],
        *,
        state: StoryState | None = None,
    ) -> StorySessionAck:
        if state is not None:
            branch.state = state
        parent = branch.head_event_id
        causal_events = []
        for event in events:
            causal_id = f"{branch.id}:{event.id}"
            causal = CausalStoryEvent(causal_id, parent, event)
            causal_events.append(causal)
            parent = causal_id
        branch.events.extend(causal_events)
        branch.head_event_id = parent
        branch.generation += 1

        ending_ids = tuple(
            str(event.payload.get("nodeId") or "")
            for event in events
            if event.type == StoryEventType.ENDING_REACHED
        )
        if global_effects or ending_ids:
            branch_command_id = str(getattr(command, "command_id"))
            self.outbox.append(
                GlobalEffectOutboxEntry(
                    id=(
                        f"{self.runtime.program.story_id}:{branch.id}:"
                        f"{branch_command_id}"
                    ),
                    source_branch_id=branch.id,
                    source_command_id=branch_command_id,
                    effects=global_effects,
                    ending_ids=ending_ids,
                )
            )

        view = story_state_view(
            self.runtime.program,
            branch.state,
            self.global_progress,
        )
        ack = StorySessionAck(
            command_id=str(getattr(command, "command_id")),
            branch_id=branch.id,
            generation=branch.generation,
            revision=branch.state.revision,
            event_ids=tuple(item.id for item in causal_events),
            head_event_id=branch.head_event_id,
            duplicate=False,
            story=MappingProxyType(view),
            presentation_events=tuple(
                MappingProxyType(item) for item in story_event_messages(events)
            ),
        )
        branch.idempotency.record(
            command,
            accepted=True,
            resulting_revision=branch.state.revision,
            event_ids=ack.event_ids,
            ack=ack.to_payload(),
        )
        branch.checkpoints.append(
            StoryCheckpoint(
                generation=branch.generation,
                message_count=len(branch.history_entries),
                state=branch.state,
                head_event_id=branch.head_event_id,
                event_count=len(branch.events),
                history_entries=branch.history_entries,
                idempotency_payload=tuple(
                    MappingProxyType(item) for item in branch.idempotency.to_payload()
                ),
            )
        )
        branch.checkpoints = branch.checkpoints[-128:]
        self._save()
        self.failure_injector("after_session_commit")
        self.flush_global_outbox()
        return ack

    def _apply_global_entry(self, entry: GlobalEffectOutboxEntry) -> None:
        variables = self.global_progress.variables
        definitions = {
            definition.id: definition
            for definition in self.runtime.program.variables
            if definition.scope == VariableScope.GLOBAL
        }
        for effect in entry.effects:
            if effect.op not in {"set", "increment", "add-set", "remove-set"}:
                raise StoryPersistenceError(f"unsupported global effect {effect.op!r}")
            variable_id = str(effect.args[0])
            definition = definitions.get(variable_id)
            if definition is None:
                raise StoryPersistenceError(
                    f"outbox targets non-global variable {variable_id!r}"
                )
            previous = variables[variable_id]
            operand = effect.args[1]
            if effect.op == "set":
                current = (
                    frozenset(str(item) for item in operand)
                    if definition.type
                    in {VariableType.STRING_SET, VariableType.NODE_SET}
                    else freeze_value(operand)
                )
            elif effect.op == "increment":
                current = int(previous) + int(operand)
                if definition.minimum is not None:
                    current = max(definition.minimum, current)
                if definition.maximum is not None:
                    current = min(definition.maximum, current)
            else:
                items = set(previous)
                if effect.op == "add-set":
                    items.add(str(operand))
                else:
                    items.discard(str(operand))
                current = frozenset(items)
            if not variable_value_is_valid(definition, current):
                raise StoryPersistenceError(
                    f"outbox produced invalid value for {variable_id!r}"
                )
            variables[variable_id] = current
        self.global_progress.unlocked_ending_ids.update(entry.ending_ids)
        self.global_progress.applied_outbox_ids.add(entry.id)
        self.global_progress.revision += 1

    def _branch_from_payload(self, raw: Mapping[str, Any]) -> StoryBranch:
        state_raw = raw.get("state")
        if not isinstance(state_raw, Mapping):
            raise StoryPersistenceError("story branch state must be an object")
        events_raw = raw.get("events", ())
        checkpoints_raw = raw.get("checkpoints", ())
        if not isinstance(events_raw, list) or not isinstance(checkpoints_raw, list):
            raise StoryPersistenceError("story branch logs must be lists")
        events = []
        for item in events_raw:
            if not isinstance(item, Mapping) or not isinstance(
                item.get("event"), Mapping
            ):
                raise StoryPersistenceError("causal story event is invalid")
            events.append(
                CausalStoryEvent(
                    id=str(item.get("id") or ""),
                    parent_event_id=_optional_text(item.get("parentEventId")),
                    event=story_event_from_payload(item["event"]),
                )
            )
        checkpoints = [
            self._checkpoint_from_payload(item)
            for item in checkpoints_raw
            if isinstance(item, Mapping)
        ]
        return StoryBranch(
            id=str(raw.get("id") or ""),
            parent_id=_optional_text(raw.get("parentId")),
            generation=int(raw.get("generation") or 0),
            state=story_state_from_payload(state_raw, program=self.runtime.program),
            head_event_id=_optional_text(raw.get("headEventId")),
            events=events,
            checkpoints=checkpoints,
            idempotency=StoryCommandIdempotencyIndex.from_payload(
                raw.get("idempotency", [])
            ),
            history_entries=_history_entries(raw.get("historyEntries", ())),
        )

    def _checkpoint_from_payload(self, raw: Mapping[str, Any]) -> StoryCheckpoint:
        state_raw = raw.get("state")
        if not isinstance(state_raw, Mapping):
            raise StoryPersistenceError("checkpoint state must be an object")
        idempotency = raw.get("idempotency", ())
        if not isinstance(idempotency, list):
            raise StoryPersistenceError("checkpoint idempotency must be a list")
        return StoryCheckpoint(
            generation=int(raw.get("generation") or 0),
            message_count=int(raw.get("messageCount") or 0),
            state=story_state_from_payload(state_raw, program=self.runtime.program),
            head_event_id=_optional_text(raw.get("headEventId")),
            event_count=int(raw.get("eventCount") or 0),
            history_entries=_history_entries(raw.get("historyEntries", ())),
            idempotency_payload=tuple(
                MappingProxyType(dict(item))
                for item in idempotency
                if isinstance(item, Mapping)
            ),
        )

    def _validate_all_branches(self) -> None:
        initial = self.runtime.initial_state()
        for branch_id, branch in self.branches.items():
            if branch.id != branch_id or not branch.checkpoints:
                raise StoryPersistenceError("invalid story branch identity")
            parent = None
            for causal in branch.events:
                if causal.parent_event_id != parent:
                    raise StoryPersistenceError("broken causal story event chain")
                if not causal.id or ":" not in causal.id:
                    raise StoryPersistenceError("invalid causal story event id")
                parent = causal.id
            if parent != branch.head_event_id:
                raise StoryPersistenceError(
                    "story branch head does not match event chain"
                )
            replayed = StoryEventReplayer().replay(
                initial,
                tuple(item.event for item in branch.events),
                program=self.runtime.program,
            )
            if replayed != branch.state:
                raise StoryPersistenceError(
                    f"story branch {branch.id!r} does not match event replay"
                )

    def _checkpoint(self, branch: StoryBranch, generation: int) -> StoryCheckpoint:
        for checkpoint in reversed(branch.checkpoints):
            if checkpoint.generation == generation:
                return checkpoint
        raise KeyError(f"generation {generation} has no checkpoint")

    def _save(self) -> None:
        if self.repository is not None:
            self.repository.save(self.to_payload())

    def _require_enabled(self) -> None:
        self.flags.require(FeatureFlag.STORY_SYSTEM)


def _initial_global_progress(program: StoryProgram) -> GlobalStoryProgress:
    return GlobalStoryProgress(
        story_id=program.story_id,
        story_version=program.story_version,
        program_source_hash=program.source_hash,
        variables={
            definition.id: freeze_value(definition.initial)
            for definition in program.variables
            if definition.scope == VariableScope.GLOBAL
        },
    )


def _history_entries(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise StoryPersistenceError("history entries must be a list")
    return tuple(
        MappingProxyType(dict(item)) for item in value if isinstance(item, Mapping)
    )


def _branch_id(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 80:
        raise ValueError("branch id must contain 1-80 characters")
    if any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        for character in candidate
    ):
        raise ValueError("branch id contains unsupported characters")
    return candidate


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
