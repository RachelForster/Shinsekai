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
from application.session_behavior.plugin_attachment import dispatch_behavior_user_input
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
from sdk.session_behavior import (
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
    BehaviorIdentityMismatchError,
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
        self._runtime_port: Any | None = None
        self._args: Any | None = None
        self._startup: Any | None = None
        self._turn_provider = BehaviorTurnContextProvider(self)

    def set_history_argument(self, history_arg: str) -> None:
        self._history_argument = str(history_arg or "").strip()

    @property
    def behavior(self) -> SessionBehavior | None:
        return self._behavior

    @property
    def state_store(self) -> BehaviorStateStore | None:
        return self._state_store

    @property
    def runtime_port(self) -> Any | None:
        return self._runtime_port

    def set_runtime_port(self, port: Any | None) -> None:
        with self._lock:
            self._runtime_port = port

    def read_active_snapshot(self) -> tuple[SessionBehavior, str, BehaviorStateSnapshot, Any | None] | None:
        with self._lock:
            behavior, store, port = self._behavior, self._state_store, self._runtime_port
            if behavior is None or store is None:
                return None
            branch_id = self._current_branch()
            latest = store.get_latest_state(branch_id)
            return (behavior, branch_id, latest, port) if latest is not None else None

    def emit_runtime_event(self, payload: Mapping[str, Any]) -> None:
        if callable(self._emit_event):
            self._emit_event(dict(payload))

    def _current_branch(self) -> str:
        if not callable(self._branch_id_provider):
            return "main"
        return str(self._branch_id_provider() or "main").strip() or "main"

    def _serialize_envelope(self, envelope: BehaviorStateEnvelope | None) -> dict[str, Any] | None:
        if envelope is None:
            return None
        payload = envelope.to_camel_dict()
        port = self._runtime_port
        plugin_id = str(getattr(port, "plugin_id", "") or getattr(port, "_plugin_id", "") or "").strip()
        if plugin_id:
            payload["pluginId"] = plugin_id
        return payload

    def _emit_replace(self, envelope: BehaviorStateEnvelope | None) -> None:
        with self._lock:
            self._last_envelope = envelope
            payload = self._serialize_envelope(envelope)
        if callable(self._emit_event):
            self._emit_event({"type": "behavior.state.replace", "behavior": payload})

    def _active_casting_map(self) -> CastingMap | None:
        snapshot = self.read_active_snapshot()
        return snapshot[0].get_casting_map(snapshot[2].state) if snapshot is not None else None

    def _resolve_character_media_handler(self) -> Any | None:
        if self._character_media_handler is None:
            self._character_media_handler = resolve_character_media_handler(
                self._runtime_components, self._app_runtime
            )
        return self._character_media_handler

    def _bind_ui_worker(self) -> None:
        ui_worker = resolve_ui_worker(self._runtime_components, self._app_runtime)
        if ui_worker is not None and hasattr(ui_worker, "set_on_playback_idle"):
            ui_worker.set_on_playback_idle(self.on_playback_idle)

    def _sync_media_policy(self, state: Mapping[str, Any] | None) -> None:
        self._last_state = copy.deepcopy(dict(state)) if state is not None else None
        casting = (
            self._behavior.get_casting_map(state)
            if self._behavior is not None and state is not None
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
            state_store.recover_pending()
            target_branch = branch_id or self._current_branch()
            try:
                snap = state_store.initialize_state(
                    branch_id=target_branch, behavior_id=behavior.behavior_id, state=initial_state
                )
            except BehaviorIdentityMismatchError as exc:
                params = {
                    "expectedBehaviorId": exc.expected_behavior_id,
                    "actualBehaviorId": exc.actual_behavior_id,
                    "branchId": exc.branch_id,
                }
                raise AppError("behavior.identity_mismatch", params=params, fallback_message=str(exc), http_status=409) from exc
            self._behavior, self._state_store = behavior, state_store
            self._initial_state = copy.deepcopy(dict(initial_state))
            self._idempotency.clear_branch()
            self._ensure_compact_hook()
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

    def _sync_latest_media_policy(self) -> None:
        if self._behavior is not None and self._state_store is not None:
            latest = self._state_store.get_latest_state(self._current_branch())
            if latest is not None:
                self._sync_media_policy(latest.state)

    def configure_session_runtime(self, context: SessionRuntimeCapabilityContext) -> None:
        from core.chat_history.storage import legacy_active_history_branch

        self._runtime_components, self._app_runtime = context.runtime, context.app_runtime
        self._args, self._startup = context.args, context.startup
        if self._emit_event is None and callable(getattr(context.transport, "emit", None)):
            self._emit_event = context.transport.emit
        history_arg = str(getattr(context.args, "history", "") or "").strip()
        if history_arg:
            self._history_argument = history_arg
            if self._branch_id_provider is None:
                self._branch_id_provider = lambda h=history_arg: legacy_active_history_branch(h)
        if self._llm_manager is None:
            self._llm_manager = getattr(context.startup, "llm_manager", None)
        self._resolve_character_media_handler()
        if self._hook_dispatcher is None and context.startup is not None:
            self._hook_dispatcher = getattr(self._llm_manager, "hook_dispatcher", None)
        self._bind_ui_worker()
        if self._behavior is None:
            auto_attach_bound_behavior(self, context)
        if self._behavior is not None:
            self._ensure_compact_hook()
            self._sync_latest_media_policy()

    def bind_streaming_session(self, context: StreamingWiringCapabilityContext) -> None:
        self._app_runtime = context.app_runtime
        dispatcher = getattr(context.bindings, "command_dispatcher", None)
        for reg_name, cb in (
            ("add_history_mutated_listener", self.on_history_mutated),
            ("add_free_text_guard", self.assert_free_text_allowed),
            ("add_user_input_interceptor", self.intercept_user_input),
        ):
            reg = getattr(dispatcher, reg_name, None)
            if callable(reg):
                reg(cb)
        self._bind_ui_worker()
        self._sync_latest_media_policy()

    def on_session_ready(self) -> None:
        notify_behavior_session_ready(self)

    def intercept_user_input(
        self, text: str, attachments: Sequence[Mapping[str, Any]] = ()
    ) -> tuple[bool, str | None]:
        return dispatch_behavior_user_input(self, text, attachments)

    def _publish_transition(
        self,
        behavior: SessionBehavior,
        branch_id: str,
        envelope: BehaviorStateEnvelope,
        commit_result: BehaviorCommitResult,
    ) -> BehaviorStateEnvelope:
        self._emit_replace(envelope)
        after_behavior_transition_committed(
            behavior,
            branch_id=branch_id,
            state_version=commit_result.snapshot.state_version,
            appended_turn_seqs=commit_result.appended_turn_seqs,
        )
        return envelope

    def commit_external_transition(
        self, *, expected_state_version: int, transition: BehaviorTransition, branch_id: str | None = None
    ) -> BehaviorStateEnvelope:
        with self._lock:
            behavior, store = self._behavior, self._state_store
            if behavior is None or store is None:
                raise AppError("behavior.not_active", fallback_message="No SessionBehavior is active for this session.", http_status=400)
            resolved_branch = branch_id or self._current_branch()
            envelope, commit_result = self._commit_transition(
                behavior=behavior, store=store, branch_id=resolved_branch,
                expected_state_version=expected_state_version, transition=transition,
            )
        return self._publish_transition(behavior, resolved_branch, envelope, commit_result)

    def is_free_text_allowed(self) -> bool:
        snapshot = self.read_active_snapshot()
        if snapshot is None:
            return True
        behavior, _branch_id, latest, _port = snapshot
        return bool(behavior.describe_state(latest.state, latest.state_version).stage_policy.allow_free_text_interject)

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
        res = self.handle_behavior_command(payload)
        if res.status == "stale_version":
            raise AppError(res.error_code or "behavior.stale_state_version", fallback_message=res.error_message or "Stale behavior state version.", http_status=409)
        if res.status == "rejected":
            raise AppError(res.error_code or "behavior.command.rejected", fallback_message=res.error_message or "Behavior command rejected.", http_status=400)

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

    def _stale_resolution(
        self,
        behavior: SessionBehavior,
        snapshot: BehaviorStateSnapshot | None,
        message: str,
    ) -> CommandResolution:
        auth_env = (
            behavior.describe_state(snapshot.state, snapshot.state_version)
            if snapshot is not None
            else None
        )
        if auth_env is not None:
            self._emit_replace(auth_env)
        return CommandResolution(
            status="stale_version",
            envelope=auth_env,
            error_code="behavior.stale_state_version",
            error_message=message,
        )

    def handle_behavior_command(self, raw_payload: object) -> CommandResolution:
        """Execute one behavior command with idempotency dedupe and OCC enforcement."""
        command: BehaviorCommand = parse_behavior_command(raw_payload)
        with self._lock:
            behavior, store = self._behavior, self._state_store
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
                return self._stale_resolution(
                    behavior,
                    latest,
                    f"Expected stateVersion {latest.state_version if latest else None}, got {command.expected_state_version}",
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
                    behavior=behavior, store=store, branch_id=branch_id,
                    expected_state_version=latest.state_version, transition=outcome,
                )
            except BehaviorVersionConflictError as exc:
                return self._stale_resolution(behavior, store.get_latest_state(branch_id), str(exc))
            accepted = CommandResolution(status="accepted", envelope=envelope)
            self._idempotency.record(branch_id, command.command_id, accepted)
        self._publish_transition(behavior, branch_id, envelope, commit_result)
        return accepted

    def on_playback_idle(self, turn: Any = None) -> BehaviorStateEnvelope | None:
        """Forward drained-playback signal to the active SessionBehavior."""
        del turn
        with self._lock:
            behavior, store = self._behavior, self._state_store
            if behavior is None or store is None:
                return None
            branch_id = self._current_branch()
            latest = store.get_latest_state(branch_id)
            if latest is None:
                return None
            transition = behavior.on_playback_idle(
                state=latest.state, state_version=latest.state_version, branch_id=branch_id
            )
            if transition is None:
                return None
            envelope, commit_result = self._commit_transition(
                behavior=behavior, store=store, branch_id=branch_id,
                expected_state_version=latest.state_version, transition=transition,
            )
        return self._publish_transition(behavior, branch_id, envelope, commit_result)

    def on_before_compact(self, context: BeforeCompactContext) -> None:
        snapshot = self.read_active_snapshot()
        if snapshot is not None:
            snapshot[0].on_before_compact(context, state=snapshot[2].state)

    def on_history_mutated(
        self, reason: str, *, branch_id: str | None = None
    ) -> BehaviorStateEnvelope | None:
        """Invalidate prefetch and resync or reopen authoritative state after history mutation."""
        return handle_behavior_history_mutated(self, reason, branch_id=branch_id)

    def snapshot_payload(self) -> dict[str, Any] | None:
        with self._lock:
            behavior, store = self._behavior, self._state_store
            if behavior is None or store is None:
                return self._serialize_envelope(self._last_envelope)
            latest = store.get_latest_state(self._current_branch())
            if latest is None:
                return None
            envelope = behavior.describe_state(latest.state, latest.state_version)
            self._last_envelope = envelope
            return self._serialize_envelope(envelope)

    def on_shutdown(self) -> None:
        behavior = self._behavior
        for attr in ("on_shutdown", "shutdown"):
            fn = getattr(behavior, attr, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    logger.exception("SessionBehavior.%s failed", attr)
        if self._prefetch is not None:
            self._prefetch.shutdown()


__all__ = ["SessionBehaviorCapability"]
