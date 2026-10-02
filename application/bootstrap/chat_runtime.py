"""Compose bridge-side chat capabilities, once per application state.

Only this root binds broad application state to feature-owned operations.
No import-side registrations or shared mutable registries across processes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from application.chat import build_snapshot, read_history, session_metadata
from application.chat.command_handlers import (
    ChatCommandBindings,
    TurnOptionsStore,
    register_chat_commands,
)
from application.chat.dispatch_commands import CommandContext, CommandRegistry, RuntimeCommandPorts
from application.chat.history_commands import (
    HistoryCommandBindings,
    HistoryParticipant,
    register_history_commands,
)
from application.chat.lifecycle import ChatLifecycle
from application.chat.mobile_access import mobile_access_snapshot
from application.chat.snapshot_contributions import SnapshotContext, SnapshotContributors
from application.story import chat_runtime as story_runtime
from application.story.coordinator import story_snapshot_patch

_assembly_lock = threading.RLock()


@dataclass(frozen=True)
class ChatRuntime:
    commands: CommandRegistry
    snapshots: SnapshotContributors
    lifecycle: ChatLifecycle
    command_context: Callable[[dict[str, Any]], CommandContext]


def compose_chat_runtime(state: Any) -> ChatRuntime:
    commands = CommandRegistry()
    snapshots = SnapshotContributors()

    def snapshot(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return build_snapshot.build_chat_snapshot(state, *args, **kwargs)

    def update_session(patch: dict[str, Any]) -> None:
        state.chat_session = {**state.chat_session, **patch}

    def command_context(body: dict[str, Any]) -> CommandContext:
        return CommandContext(body, RuntimeCommandPorts(
            session_id=str(state.chat_session.get("sessionId") or "").strip(),
            stream=getattr(state, "chat_stream", None),
            snapshot=snapshot,
            update_session=update_session,
        ))

    register_chat_commands(commands, ChatCommandBindings(
        turn_options=lambda: session_metadata.chat_turn_options(state),
        user_display_name=lambda: session_metadata.chat_user_display_name_from_snapshot(state),
        turn_options_store=TurnOptionsStore(
            read=lambda: state.config_manager.config.api_config,
            replace=lambda config: setattr(state.config_manager.config, "api_config", config),
            save=lambda: state.config_manager.save_api_config(),
        ),
    ))
    register_history_commands(commands, HistoryCommandBindings(
        copy_payload=lambda: read_history.copy_history_payload(state),
        open_payload=lambda: read_history.open_history_payload(state),
        clear_storage=lambda: read_history.clear_chat_history(state),
        features=lambda: session_metadata.chat_experimental_features(state),
    ), HistoryParticipant(
        discard=lambda: story_runtime.discard_bound_story_session(state),
        before_branch=lambda command, body: story_runtime.sync_story_session_branch_command(state, command, body),
        after_branch=lambda: story_runtime.publish_bound_story_transition(state),
    ))
    story_runtime.register_story_choice(commands, state)

    def mobile_snapshot(context: SnapshotContext) -> dict[str, Any]:
        return mobile_access_snapshot(state, streaming=context.streaming)

    snapshots.register("mobile-access", {"mobileAccess", "wsUrl"}, mobile_snapshot,
                       allow_core_override=frozenset({"wsUrl"}))
    snapshots.register("story", {"story"}, lambda _context: story_snapshot_patch(state),
                       after_extra_on_stream=True)
    return ChatRuntime(commands, snapshots, ChatLifecycle(), command_context)


def get_chat_runtime(state: Any) -> ChatRuntime:
    # Assembly is brief and does not call any feature callbacks. Observers and
    # handlers run only after this lock (and all process locks) are released.
    with _assembly_lock:
        runtime = getattr(state, "chat_runtime_services", None)
        if runtime is None:
            runtime = compose_chat_runtime(state)
            state.chat_runtime_services = runtime
        return runtime
