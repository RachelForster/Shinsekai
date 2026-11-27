"""SessionCapability coordinating SessionBehavior, OCC commits, compaction, and prefetch."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import copy
import logging
import threading
from typing import Any

from application.chat.capabilities.contracts import (
    BaseSessionCapability,
    SessionRuntimeCapabilityContext,
    StreamingWiringCapabilityContext,
    TurnContextProvider,
)
from application.session_behavior.casting import CastingMap
from application.session_behavior.prefetch import SpeculativePrefetchCoordinator
from application.session_behavior.runtime_binding import (
    BehaviorTurnContextProvider,
    after_behavior_transition_committed,
    auto_attach_bound_behavior,
    handle_behavior_history_mutated,
    notify_behavior_session_ready,
    resolve_character_media_handler,
    resolve_opencc,
    resolve_ui_worker,
    sync_casting_media_policy,
)
from application.session_behavior.protocol import (
    BehaviorCommand,
    BehaviorStateEnvelope,
    BehaviorTransition,
    CommandIdempotencyCache,
    CommandResolution,
    SessionBehavior,
    parse_behavior_command,
)
from core.chat_history.behavior_state_models import (
    BehaviorCommitResult,
    BehaviorStateSnapshot,
    BehaviorVersionConflictError,
)
from core.chat_history.behavior_state_store import BehaviorStateStore
from sdk.exception.types import AppError
from sdk.hooks import BeforeCompactContext

logger = logging.getLogger(__name__)


class SessionBehaviorCapability(BaseSessionCapability):
    """Host bridge binding an active SessionBehavior to runtime workers and commands."""

    capability_id = "session_behavior"

    def __init__(
        self,
        *,
        emit_event: Callable[[dict[str, Any]], None] | None = None,
        branch_id_provider: Callable[[], str] | None = None,
        llm_manager: Any | None = None,
        character_media_handler: Any | None = None,
        prefetch_coordinator: SpeculativePrefetchCoordinator | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._behavior: SessionBehavior | None = None
        self._state_store: BehaviorStateStore | None = None
        self._emit_event = emit_event
        self._branch_id_provider = branch_id_provider
        self._llm_manager = llm_manager
        self._character_media_handler = character_media_handler
        self._runtime_components: Any | None = None
        self._app_runtime: Any | None = None
        self._hook_dispatcher: Any | None = None
        self._prefetch = prefetch_coordinator
        self._idempotency = CommandIdempotencyCache(max_entries=128)
        self._compact_hook_registered = False
        self._last_envelope: BehaviorStateEnvelope | None = None
        self._history_argument = ""
        self._initial_state: dict[str, Any] = {}
        self._last_state: dict[str, Any] | None = None
        self._turn_provider = BehaviorTurnContextProvider(self)

    def set_history_argument(self, history_arg: str) -> None:
        self._history_argument = str(history_arg or "").strip()

    @property
    def behavior(self) -> SessionBehavior | None:
        return self._behavior

    @property
    def state_store(self) -> BehaviorStateStore | None:
        return self._state_store

    def _current_branch(self) -> str:
        if callable(self._branch_id_provider):
            branch = str(self._branch_id_provider() or "main").strip()
            return branch or "main"
        return "main"

    def _emit_replace(self, envelope: BehaviorStateEnvelope | None) -> None:
        with self._lock:
            self._last_envelope = envelope
        if callable(self._emit_event):
            self._emit_event(
                {
                    "type": "behavior.state.replace",
                    "behavior": envelope.to_camel_dict() if envelope is not None else None,
                }
            )

    def _active_casting_map(self) -> CastingMap | None:
        behavior = self._behavior
        store = self._state_store
        if behavior is None or store is None:
            return None
        latest = store.get_latest_state(self._current_branch())
        if latest is None:
            return None
        return behavior.get_casting_map(latest.state)

    def _resolve_character_media_handler(self) -> Any | None:
        if self._character_media_handler is not None:
            return self._character_media_handler
        found = resolve_character_media_handler(
            self._runtime_components,
            self._app_runtime,
        )
        if found is not None:
            self._character_media_handler = found
            return found
        return None

    def _bind_ui_worker(self) -> None:
        ui_worker = resolve_ui_worker(self._runtime_components, self._app_runtime)
        if ui_worker is not None and hasattr(ui_worker, "set_on_playback_idle"):
            ui_worker.set_on_playback_idle(self.on_playback_idle)

    def _sync_media_policy(self, state: Mapping[str, Any] | None) -> None:
        self._last_state = copy.deepcopy(dict(state)) if state is not None else None
        behavior = self._behavior
        casting = (
            behavior.get_casting_map(state)
            if behavior is not None and state is not None
            else None
        )
        sync_casting_media_policy(
            self._llm_manager,
            casting,
            media_handler=self._resolve_character_media_handler(),
            opencc_provider=lambda: resolve_opencc(self._runtime_components, self._app_runtime),
            active_casting_provider=self._active_casting_map,
        )

    def _ensure_compact_hook(self) -> None:
        if self._compact_hook_registered or self._hook_dispatcher is None:
            return
        if hasattr(self._hook_dispatcher, "register_before_compact"):
            self._hook_dispatcher.register_before_compact(
                self.on_before_compact,
                label="session_behavior_before_compact",
            )
            self._compact_hook_registered = True

    def attach_behavior(
        self,
        behavior: SessionBehavior,
        *,
        state_store: BehaviorStateStore,
        initial_state: Mapping[str, Any],
        branch_id: str | None = None,
    ) -> BehaviorStateEnvelope:
        """Bind a SessionBehavior to this session, recover pending state, and publish."""
        with self._lock:
            self._behavior = behavior
            self._state_store = state_store
            self._initial_state = copy.deepcopy(dict(initial_state))
            self._idempotency.clear_branch()
            self._ensure_compact_hook()
            state_store.recover_pending()
            target_branch = branch_id or self._current_branch()
            snap = state_store.initialize_state(
                branch_id=target_branch,
                behavior_id=behavior.behavior_id,
                state=initial_state,
            )
            behavior.on_state_restored(snap)
            self._bind_ui_worker()
            self._sync_media_policy(snap.state)
            envelope = behavior.describe_state(snap.state, snap.state_version)
        self._emit_replace(envelope)
        return envelope

    def detach_behavior(self) -> None:
        with self._lock:
            self._behavior = None
            self._state_store = None
            self._idempotency.clear_branch()
            self._sync_media_policy(None)
        if self._prefetch is not None:
            self._prefetch.invalidate_all()
        self._emit_replace(None)

    def configure_session_runtime(self, context: SessionRuntimeCapabilityContext) -> None:
        from core.chat_history.storage import legacy_active_history_branch

        app_runtime = context.app_runtime
        startup = context.startup
        self._runtime_components = context.runtime
        self._app_runtime = app_runtime
        if self._emit_event is None:
            emit_fn = getattr(context.transport, "emit", None)
            if callable(emit_fn):
                self._emit_event = emit_fn
        history_arg = str(getattr(context.args, "history", "") or "").strip()
        if history_arg:
            self._history_argument = history_arg
            if self._branch_id_provider is None:
                self._branch_id_provider = lambda h=history_arg: legacy_active_history_branch(h)
        if self._llm_manager is None:
            self._llm_manager = getattr(startup, "llm_manager", None)
        self._resolve_character_media_handler()
        if self._hook_dispatcher is None and startup is not None:
            self._hook_dispatcher = getattr(
                getattr(startup, "llm_manager", None), "hook_dispatcher", None
            )
        self._bind_ui_worker()
        if self._behavior is None:
            auto_attach_bound_behavior(self, context)
        if self._behavior is not None:
            self._ensure_compact_hook()
            if self._state_store is not None:
                latest = self._state_store.get_latest_state(self._current_branch())
                if latest is not None:
                    self._sync_media_policy(latest.state)

    def bind_streaming_session(self, context: StreamingWiringCapabilityContext) -> None:
        app_runtime = context.app_runtime
        self._app_runtime = app_runtime
        dispatcher = getattr(context.bindings, "command_dispatcher", None)
        add_listener = getattr(dispatcher, "add_history_mutated_listener", None)
        if callable(add_listener):
            add_listener(self.on_history_mutated)
        add_guard = getattr(dispatcher, "add_free_text_guard", None)
        if callable(add_guard):
            add_guard(self.assert_free_text_allowed)
        self._bind_ui_worker()
        if self._behavior is not None and self._state_store is not None:
            latest = self._state_store.get_latest_state(self._current_branch())
            if latest is not None:
                self._sync_media_policy(latest.state)

    def on_session_ready(self) -> None:
        notify_behavior_session_ready(self)

    def is_free_text_allowed(self) -> bool:
        with self._lock:
            behavior = self._behavior
            store = self._state_store
            if behavior is None or store is None:
                return True
            latest = store.get_latest_state(self._current_branch())
            if latest is None:
                return True
            envelope = behavior.describe_state(latest.state, latest.state_version)
            return bool(envelope.stage_policy.allow_free_text_interject)

    def assert_free_text_allowed(self) -> None:
        if not self.is_free_text_allowed():
            raise AppError(
                "behavior.free_text_disabled",
                fallback_message="Free-text input is disabled by the active session behavior.",
                http_status=400,
            )

    def turn_context_providers(self) -> Sequence[TurnContextProvider]:
        return (self._turn_provider,)

    def command_handlers(self) -> dict[str, Callable[[object], None]]:
        return {"behavior-command": self._dispatch_runtime_command}

    def _dispatch_runtime_command(self, payload: object) -> None:
        resolution = self.handle_behavior_command(payload)
        if resolution.status == "stale_version":
            raise AppError(
                resolution.error_code or "behavior.stale_state_version",
                fallback_message=resolution.error_message or "Stale behavior state version.",
                http_status=409,
            )
        if resolution.status == "rejected":
            raise AppError(
                resolution.error_code or "behavior.command.rejected",
                fallback_message=resolution.error_message or "Behavior command rejected.",
                http_status=400,
            )

    def _commit_transition(
        self,
        *,
        behavior: SessionBehavior,
        store: BehaviorStateStore,
        branch_id: str,
        expected_state_version: int,
        transition: BehaviorTransition,
    ) -> tuple[BehaviorStateEnvelope, BehaviorCommitResult]:
        result = store.commit_behavior_turn(
            branch_id=branch_id,
            behavior_id=behavior.behavior_id,
            expected_state_version=expected_state_version,
            next_state=transition.next_state,
            messages=transition.messages_to_commit,
            reset_branch_turns=bool(transition.reset_history_context),
        )
        if transition.invalidate_prefetch and self._prefetch is not None:
            self._prefetch.invalidate_all()
        self._sync_media_policy(result.snapshot.state)
        envelope = transition.envelope or behavior.describe_state(
            result.snapshot.state, result.snapshot.state_version
        )
        return envelope, result

    def handle_behavior_command(self, raw_payload: object) -> CommandResolution:
        """Execute one behavior command with idempotency dedupe and OCC enforcement."""
        command: BehaviorCommand = parse_behavior_command(raw_payload)
        with self._lock:
            behavior = self._behavior
            store = self._state_store
            if behavior is None or store is None:
                raise AppError(
                    "behavior.not_active",
                    fallback_message="No SessionBehavior is active for this session.",
                    http_status=400,
                )
            branch_id = self._current_branch()
            cached = self._idempotency.get(branch_id, command.command_id)
            if cached is not None:
                return CommandResolution(
                    status="duplicate",
                    envelope=cached.envelope,
                    error_code=cached.error_code,
                    error_message=cached.error_message,
                )

            latest = store.get_latest_state(branch_id)
            if latest is None or latest.state_version != command.expected_state_version:
                auth_env = (
                    behavior.describe_state(latest.state, latest.state_version)
                    if latest is not None
                    else None
                )
                if auth_env is not None:
                    self._emit_replace(auth_env)
                return CommandResolution(
                    status="stale_version",
                    envelope=auth_env,
                    error_code="behavior.stale_state_version",
                    error_message=(
                        f"Expected stateVersion {latest.state_version if latest else None}, "
                        f"got {command.expected_state_version}"
                    ),
                )

            outcome = behavior.handle_command(
                command,
                state=latest.state,
                state_version=latest.state_version,
                branch_id=branch_id,
            )
            if isinstance(outcome, CommandResolution):
                if outcome.status == "accepted":
                    self._idempotency.record(branch_id, command.command_id, outcome)
                    if outcome.envelope is not None:
                        self._emit_replace(outcome.envelope)
                return outcome

            try:
                envelope, commit_result = self._commit_transition(
                    behavior=behavior,
                    store=store,
                    branch_id=branch_id,
                    expected_state_version=latest.state_version,
                    transition=outcome,
                )
            except BehaviorVersionConflictError as exc:
                refreshed = store.get_latest_state(branch_id)
                auth_env = (
                    behavior.describe_state(refreshed.state, refreshed.state_version)
                    if refreshed is not None
                    else None
                )
                if auth_env is not None:
                    self._emit_replace(auth_env)
                return CommandResolution(
                    status="stale_version",
                    envelope=auth_env,
                    error_code="behavior.stale_state_version",
                    error_message=str(exc),
                )

            accepted = CommandResolution(status="accepted", envelope=envelope)
            self._idempotency.record(branch_id, command.command_id, accepted)
        self._emit_replace(envelope)
        after_behavior_transition_committed(
            behavior,
            branch_id=branch_id,
            state_version=commit_result.snapshot.state_version,
            appended_turn_seqs=commit_result.appended_turn_seqs,
        )
        return accepted

    def on_playback_idle(self, turn: Any = None) -> BehaviorStateEnvelope | None:
        """Forward drained-playback signal to the active SessionBehavior."""
        del turn
        with self._lock:
            behavior = self._behavior
            store = self._state_store
            if behavior is None or store is None:
                return None
            branch_id = self._current_branch()
            latest = store.get_latest_state(branch_id)
            if latest is None:
                return None
            transition = behavior.on_playback_idle(
                state=latest.state,
                state_version=latest.state_version,
                branch_id=branch_id,
            )
            if transition is None:
                return None
            envelope, commit_result = self._commit_transition(
                behavior=behavior,
                store=store,
                branch_id=branch_id,
                expected_state_version=latest.state_version,
                transition=transition,
            )
        self._emit_replace(envelope)
        after_behavior_transition_committed(
            behavior,
            branch_id=branch_id,
            state_version=commit_result.snapshot.state_version,
            appended_turn_seqs=commit_result.appended_turn_seqs,
        )
        return envelope

    def on_before_compact(self, context: BeforeCompactContext) -> None:
        behavior = self._behavior
        store = self._state_store
        if behavior is None or store is None:
            return
        latest = store.get_latest_state(self._current_branch())
        if latest is None:
            return
        behavior.on_before_compact(context, state=latest.state)

    def on_history_mutated(
        self, reason: str, *, branch_id: str | None = None
    ) -> BehaviorStateEnvelope | None:
        """Invalidate prefetch and resync or reopen authoritative state after history mutation."""
        return handle_behavior_history_mutated(self, reason, branch_id=branch_id)

    def snapshot_payload(self) -> dict[str, Any] | None:
        with self._lock:
            behavior = self._behavior
            store = self._state_store
            if behavior is None or store is None:
                return (
                    self._last_envelope.to_camel_dict()
                    if self._last_envelope is not None
                    else None
                )
            latest = store.get_latest_state(self._current_branch())
            if latest is None:
                return None
            envelope = behavior.describe_state(latest.state, latest.state_version)
            self._last_envelope = envelope
            return envelope.to_camel_dict()

    def on_shutdown(self) -> None:
        shutdown = getattr(self._behavior, "shutdown", None)
        if callable(shutdown):
            shutdown()
        if self._prefetch is not None:
            self._prefetch.shutdown()


__all__ = ["SessionBehaviorCapability"]
