"""Plugin SessionBehavior resolution, attachment, and hook dispatch helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import logging
from typing import Any

from application.session_behavior.runtime_port import HostSessionRuntimePort
from core.chat_history.behavior_state_store import BehaviorStateStore
from core.chat_history.sqlite_session_store import SqliteSessionStore
from core.chat_history.storage import chat_history_session_dir, open_session_store
from plugin_system.host import get_plugin_manager
from sdk.session_behavior import (
    BehaviorStateEnvelope,
    BehaviorTransition,
    SessionBehaviorInitContext,
    UserInputInterceptResult,
)

logger = logging.getLogger(__name__)


def parse_behavior_config_arg(raw: object) -> dict[str, Any]:
    """Parse ``--behavior-config`` JSON string or mapping into a plain dict."""
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    text = str(raw or "").strip()
    if not text:
        return {}
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("behavior_config must decode to a JSON object.")
    return parsed


def _build_state_store(history_arg: str, capability: Any) -> BehaviorStateStore:
    existing = getattr(capability, "state_store", None)
    if existing is not None:
        return existing
    clean_history = str(history_arg or "").strip()
    if clean_history:
        session_store = open_session_store(clean_history)
        return BehaviorStateStore(
            session_store,  # type: ignore[arg-type]
            chat_history_session_dir(clean_history),
        )
    return BehaviorStateStore(SqliteSessionStore(":memory:"), None)


def try_attach_plugin_behavior(
    capability: Any,
    *,
    args: Any,
    config: Any,
    startup: Any,
    runtime_components: Any,
    app_runtime: Any,
) -> bool:
    """Instantiate and attach the plugin-registered SessionBehavior for ``--behavior-id``."""
    if getattr(capability, "behavior", None) is not None or args is None:
        return False
    behavior_id = str(getattr(args, "behavior_id", "") or "").strip()
    if not behavior_id:
        return False

    manager = getattr(startup, "plugin_manager", None) if startup is not None else None
    if manager is None:
        manager = get_plugin_manager()
    if manager is None:
        logger.warning("Cannot attach SessionBehavior %r: plugin manager unavailable", behavior_id)
        return False

    finder = getattr(manager, "find_session_behavior", None)
    contribution = finder(behavior_id) if callable(finder) else None
    if contribution is None:
        logger.warning("SessionBehavior %r is not registered by any active plugin", behavior_id)
        return False

    overrides = parse_behavior_config_arg(getattr(args, "behavior_config", ""))
    merged_config = {**dict(getattr(contribution, "default_config", None) or {}), **overrides}
    plugin_id = str(getattr(contribution, "plugin_id", "") or "").strip()
    port = HostSessionRuntimePort(
        plugin_id=plugin_id,
        config=config,
        runtime_components=runtime_components,
        app_runtime=app_runtime,
        capability=capability,
    )
    character_names = tuple(getattr(startup, "character_names", ()) or ())
    init_ctx = SessionBehaviorInitContext(
        behavior_id=behavior_id,
        plugin_id=plugin_id,
        config=merged_config,
        character_names=character_names,
        runtime=port,
    )
    behavior = contribution.factory(init_ctx)
    bind_fn = getattr(behavior, "on_runtime_bound", None)
    if callable(bind_fn):
        bind_fn(port)

    initial_state: dict[str, Any] = {}
    init_state_fn = getattr(behavior, "build_initial_state", None)
    if callable(init_state_fn):
        built = init_state_fn(init_ctx)
        if isinstance(built, Mapping):
            initial_state = dict(built)

    state_store = _build_state_store(str(getattr(args, "history", "") or ""), capability)
    capability.set_runtime_port(port)
    capability.attach_behavior(
        behavior,
        state_store=state_store,
        initial_state=initial_state,
    )
    return True


def _commit_if_transition(
    capability: Any,
    *,
    expected_state_version: int,
    branch_id: str,
    transition: BehaviorTransition | None,
) -> BehaviorStateEnvelope | None:
    if transition is None:
        return None
    return capability.commit_external_transition(
        expected_state_version=expected_state_version,
        transition=transition,
        branch_id=branch_id,
    )


def dispatch_behavior_session_ready(capability: Any) -> BehaviorStateEnvelope | None:
    """Invoke optional ``behavior.on_session_ready`` without holding ``_lock`` during I/O."""
    snapshot = capability.read_active_snapshot()
    if snapshot is None:
        return None
    behavior, branch_id, latest, port = snapshot
    ready_fn = getattr(behavior, "on_session_ready", None)
    if not callable(ready_fn):
        return None
    transition = ready_fn(
        state=latest.state,
        state_version=latest.state_version,
        branch_id=branch_id,
        runtime=port,
    )
    return _commit_if_transition(
        capability,
        expected_state_version=latest.state_version,
        branch_id=branch_id,
        transition=transition,
    )


def dispatch_behavior_user_input(
    capability: Any,
    text: str,
    attachments: Sequence[Mapping[str, Any]],
) -> tuple[bool, str | None]:
    """Invoke optional ``behavior.on_user_input`` before default LLM forwarding."""
    snapshot = capability.read_active_snapshot()
    if snapshot is None:
        return (False, None)
    behavior, branch_id, latest, port = snapshot
    hook_fn = getattr(behavior, "on_user_input", None)
    if not callable(hook_fn):
        return (False, None)
    outcome = hook_fn(
        text,
        attachments=tuple(attachments),
        state=latest.state,
        state_version=latest.state_version,
        branch_id=branch_id,
        runtime=port,
    )
    if outcome is None:
        return (False, None)
    if isinstance(outcome, UserInputInterceptResult):
        _commit_if_transition(
            capability,
            expected_state_version=latest.state_version,
            branch_id=branch_id,
            transition=outcome.transition,
        )
        return (bool(outcome.handled), outcome.passthrough_text)
    return (False, None)


__all__ = [
    "dispatch_behavior_session_ready",
    "dispatch_behavior_user_input",
    "parse_behavior_config_arg",
    "try_attach_plugin_behavior",
]
