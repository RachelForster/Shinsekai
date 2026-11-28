"""Public SDK contracts for plugin-provided SessionBehavior controllers."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import threading
from typing import TYPE_CHECKING, Any, Literal, Protocol

from sdk.casting import CastingMap
from sdk.exception.types import AppError
from sdk.hooks import BeforeCompactContext
from sdk.messages import LLMDialogMessage

if TYPE_CHECKING:
    pass

PlaybackEndAction = Literal["idle", "auto_advance", "show_options"]


class BehaviorStateSnapshotLike(Protocol):
    """Structural snapshot view passed to :meth:`SessionBehavior.on_state_restored`."""

    @property
    def branch_id(self) -> str: ...

    @property
    def turn_seq(self) -> int: ...

    @property
    def behavior_id(self) -> str: ...

    @property
    def state_version(self) -> int: ...

    @property
    def state(self) -> dict[str, Any]: ...

    @property
    def created_at_ms(self) -> int: ...


@dataclass(frozen=True)
class CharacterSummaryView:
    """Read-only character catalog entry exposed to session behavior plugins."""

    name: str
    description: str = ""
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    sprite_groups: tuple[str, ...] = ()
    has_voice: bool = False


@dataclass(frozen=True)
class InteractionPolicy:
    """Stage interaction controls declared dynamically by the active SessionBehavior."""

    hide_input_layer: bool = False
    playback_end_action: PlaybackEndAction = "idle"
    allow_free_text_interject: bool = True
    allow_unbound_speakers: bool = False

    def to_camel_dict(self) -> dict[str, Any]:
        return {
            "hideInputLayer": bool(self.hide_input_layer),
            "playbackEndAction": str(self.playback_end_action),
            "allowFreeTextInterject": bool(self.allow_free_text_interject),
            "allowUnboundSpeakers": bool(self.allow_unbound_speakers),
        }


@dataclass(frozen=True)
class BehaviorOption:
    """Explicit stage option or action button exposed by a SessionBehavior."""

    id: str
    label: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_camel_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "action": self.action,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class BehaviorStateEnvelope:
    """Authoritative frontend projection published via ``behavior.state.replace``."""

    behavior_id: str
    state_version: int
    stage_policy: InteractionPolicy = field(default_factory=InteractionPolicy)
    hud: dict[str, Any] = field(default_factory=dict)
    options: tuple[BehaviorOption, ...] = ()
    casting: dict[str, Any] = field(default_factory=dict)

    def to_camel_dict(self) -> dict[str, Any]:
        return {
            "behaviorId": self.behavior_id,
            "stateVersion": int(self.state_version),
            "stagePolicy": self.stage_policy.to_camel_dict(),
            "hud": dict(self.hud),
            "options": [opt.to_camel_dict() for opt in self.options],
            "casting": dict(self.casting),
        }


@dataclass(frozen=True)
class BehaviorCommand:
    """Validated ``behavior-command`` payload with optimistic concurrency metadata."""

    command_id: str
    action: str
    expected_state_version: int
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BehaviorTransition:
    """Authoritative state mutation and raw LLM turns to commit atomically."""

    next_state: dict[str, Any]
    messages_to_commit: tuple[dict[str, Any], ...] = ()
    envelope: BehaviorStateEnvelope | None = None
    invalidate_prefetch: bool = False
    reset_history_context: bool = False


@dataclass(frozen=True)
class CommandResolution:
    """Outcome of handling one ``behavior-command``."""

    status: Literal["accepted", "duplicate", "stale_version", "rejected"]
    envelope: BehaviorStateEnvelope | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class UserInputInterceptResult:
    """Outcome of :meth:`SessionBehavior.on_user_input` interception."""

    handled: bool
    transition: BehaviorTransition | None = None
    passthrough_text: str | None = None


class SessionRuntimePort(Protocol):
    """Host capabilities exposed safely to an attached plugin SessionBehavior."""

    def complete_llm(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
        extra_params: Mapping[str, Any] | None = None,
    ) -> str: ...

    def list_characters(self) -> tuple[CharacterSummaryView, ...]: ...

    def deliver_dialogs(
        self,
        dialogs: Sequence[LLMDialogMessage | Mapping[str, Any]],
    ) -> int: ...

    def commit_async_transition(
        self,
        *,
        expected_state_version: int,
        transition: BehaviorTransition,
        branch_id: str | None = None,
    ) -> BehaviorStateEnvelope: ...

    def present_plugin_page(
        self,
        page_id: str,
        *,
        title: str = "",
        params: Mapping[str, Any] | None = None,
    ) -> str: ...

    def dismiss_plugin_page(self, page_id: str | None = None) -> None: ...

    def emit_custom_event(
        self,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> None: ...


@dataclass(frozen=True)
class SessionBehaviorInitContext:
    """Construction parameters passed to a registered ``SessionBehaviorFactory``."""

    behavior_id: str
    plugin_id: str
    config: dict[str, Any] = field(default_factory=dict)
    character_names: tuple[str, ...] = ()
    runtime: SessionRuntimePort | None = None


def parse_behavior_command(raw_payload: object) -> BehaviorCommand:
    """Parse and validate a raw ``behavior-command`` dictionary."""
    if not isinstance(raw_payload, Mapping):
        raise AppError(
            "behavior.command.invalid_payload",
            fallback_message="Behavior command payload must be an object.",
            http_status=400,
        )
    command_id = str(raw_payload.get("commandId") or "").strip()
    action = str(raw_payload.get("action") or "").strip()
    expected = raw_payload.get("expectedStateVersion")
    if not command_id:
        raise AppError(
            "behavior.command.missing_command_id",
            fallback_message="Behavior command requires a non-empty commandId.",
            http_status=400,
        )
    if not action:
        raise AppError(
            "behavior.command.missing_action",
            fallback_message="Behavior command requires a non-empty action.",
            http_status=400,
        )
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise AppError(
            "behavior.command.invalid_version",
            fallback_message="expectedStateVersion must be a non-negative integer.",
            http_status=400,
        )
    inner_payload = raw_payload.get("payload")
    payload_dict = dict(inner_payload) if isinstance(inner_payload, Mapping) else {}
    return BehaviorCommand(
        command_id=command_id,
        action=action,
        expected_state_version=expected,
        payload=payload_dict,
    )


class CommandIdempotencyCache:
    """Bounded FIFO/LRU idempotency cache keyed by ``(branch_id, command_id)``."""

    def __init__(self, *, max_entries: int = 128) -> None:
        self._max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[tuple[str, str], CommandResolution] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, branch_id: str, command_id: str) -> CommandResolution | None:
        key = (str(branch_id or "main"), str(command_id or ""))
        with self._lock:
            hit = self._entries.get(key)
            if hit is not None:
                self._entries.move_to_end(key)
            return hit

    def record(
        self, branch_id: str, command_id: str, resolution: CommandResolution
    ) -> None:
        key = (str(branch_id or "main"), str(command_id or ""))
        with self._lock:
            self._entries[key] = resolution
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear_branch(self, branch_id: str | None = None) -> None:
        with self._lock:
            if branch_id is None:
                self._entries.clear()
                return
            target = str(branch_id)
            for key in [k for k in self._entries if k[0] == target]:
                del self._entries[key]


class SessionBehavior(Protocol):
    """Public plugin/host protocol driving stage policies, commands, and compaction."""

    @property
    def behavior_id(self) -> str: ...

    def describe_state(
        self, state: Mapping[str, Any], state_version: int
    ) -> BehaviorStateEnvelope: ...

    def handle_command(
        self,
        command: BehaviorCommand,
        *,
        state: Mapping[str, Any],
        state_version: int,
        branch_id: str,
    ) -> BehaviorTransition | CommandResolution: ...

    def on_playback_idle(
        self,
        *,
        state: Mapping[str, Any],
        state_version: int,
        branch_id: str,
    ) -> BehaviorTransition | None: ...

    def on_before_compact(
        self,
        context: BeforeCompactContext,
        *,
        state: Mapping[str, Any],
    ) -> None: ...

    def get_casting_map(self, state: Mapping[str, Any]) -> CastingMap | None: ...

    def on_state_restored(
        self,
        snapshot: BehaviorStateSnapshotLike | None,
    ) -> None: ...


class BaseSessionBehavior:
    """Convenience base class implementing default optional SessionBehavior hooks."""

    behavior_id: str = ""

    def build_initial_state(
        self, context: SessionBehaviorInitContext
    ) -> Mapping[str, Any]:
        del context
        return {}

    def on_runtime_bound(self, runtime: SessionRuntimePort) -> None:
        del runtime

    def on_session_ready(
        self,
        *,
        state: Mapping[str, Any],
        state_version: int,
        branch_id: str,
        runtime: SessionRuntimePort,
    ) -> BehaviorTransition | None:
        del state, state_version, branch_id, runtime
        return None

    def on_user_input(
        self,
        text: str,
        *,
        attachments: Sequence[Mapping[str, Any]] = (),
        state: Mapping[str, Any],
        state_version: int,
        branch_id: str,
        runtime: SessionRuntimePort,
    ) -> UserInputInterceptResult | None:
        del text, attachments, state, state_version, branch_id, runtime
        return None

    def describe_state(
        self, state: Mapping[str, Any], state_version: int
    ) -> BehaviorStateEnvelope:
        del state
        return BehaviorStateEnvelope(
            behavior_id=self.behavior_id,
            state_version=state_version,
        )

    def handle_command(
        self,
        command: BehaviorCommand,
        *,
        state: Mapping[str, Any],
        state_version: int,
        branch_id: str,
    ) -> BehaviorTransition | CommandResolution:
        del command, state, state_version, branch_id
        return CommandResolution(
            status="rejected",
            error_code="behavior.command.unsupported",
            error_message="Unsupported behavior command.",
        )

    def on_playback_idle(
        self,
        *,
        state: Mapping[str, Any],
        state_version: int,
        branch_id: str,
    ) -> BehaviorTransition | None:
        del state, state_version, branch_id
        return None

    def on_before_compact(
        self,
        context: BeforeCompactContext,
        *,
        state: Mapping[str, Any],
    ) -> None:
        del context, state

    def get_casting_map(self, state: Mapping[str, Any]) -> CastingMap | None:
        del state
        return None

    def on_state_restored(
        self,
        snapshot: BehaviorStateSnapshotLike | None,
    ) -> None:
        del snapshot

    def on_shutdown(self) -> None:
        return None


SessionBehaviorFactory = Callable[[SessionBehaviorInitContext], SessionBehavior]


@dataclass(frozen=True)
class SessionBehaviorContribution:
    """Declarative SessionBehavior registration submitted by a plugin."""

    behavior_id: str
    factory: SessionBehaviorFactory
    plugin_id: str = ""
    plugin_version: str = ""
    name: str = ""
    description: str = ""
    default_config: dict[str, Any] = field(default_factory=dict)
    order: int = 100
    i18n: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


__all__ = [
    "BaseSessionBehavior",
    "BehaviorCommand",
    "BehaviorOption",
    "BehaviorStateEnvelope",
    "BehaviorStateSnapshotLike",
    "BehaviorTransition",
    "CharacterSummaryView",
    "CommandIdempotencyCache",
    "CommandResolution",
    "InteractionPolicy",
    "PlaybackEndAction",
    "SessionBehavior",
    "SessionBehaviorContribution",
    "SessionBehaviorFactory",
    "SessionBehaviorInitContext",
    "SessionRuntimePort",
    "UserInputInterceptResult",
    "parse_behavior_command",
]
