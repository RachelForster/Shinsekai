"""Session capability and turn context provider for automatic long-term memory."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import inspect
import os
from typing import TYPE_CHECKING, Any

from application.chat.capabilities.contracts import (
    BaseSessionCapability,
    BaseTurnContextProvider,
    SessionRuntimeCapabilityContext,
    StartupCapabilityContext,
    TurnContextProvider,
)
from core.chat_history.models import (
    is_real_user_turn_message,
    normalize_memory_mode,
    rollback_memory_for_timeline,
)
from core.chat_history.sqlite_session_store import set_default_shared_memory_rollback
from core.chat_history.storage import (
    legacy_active_history_branch,
    open_session_store,
    peek_open_session_store,
    session_id_for_history_path,
)

if TYPE_CHECKING:
    from sdk.hooks import BeforeChatContext, MessageAddedContext


def is_memory_auto_enabled() -> bool:
    """Return whether automatic long-term memory is enabled via environment."""
    return str(
        os.environ.get("SHINSEKAI_MEMORY_AUTO_ENABLED") or "1"
    ).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _last_dialogue_turn_at(history_path: str) -> float:
    store = peek_open_session_store(history_path)
    if store is None:
        return 0.0
    branch = legacy_active_history_branch(history_path)
    for turn in reversed(store.list_turns(branch_id=branch)):
        raw = turn.raw_message
        if not turn.created_at_ms or turn.source == "perception" or not raw.get("content"):
            continue
        if is_real_user_turn_message(raw) or (turn.role == "assistant" and not raw.get("tool_calls")):
            return turn.created_at_ms / 1000.0
    return 0.0


class MemoryTurnContextProvider(BaseTurnContextProvider):
    """Adapt `MemoryAutoHooks` to the `TurnContextProvider` contract."""

    capability_id = "memory"
    delegates_to_hook_dispatcher = True

    def __init__(self, hooks: Any) -> None:
        self.hooks = hooks

    def before_chat(self, context: BeforeChatContext) -> None:
        before_fn = getattr(self.hooks, "before_chat", None)
        if callable(before_fn):
            before_fn(context)

    def message_added(self, context: MessageAddedContext) -> None:
        added_fn = getattr(self.hooks, "message_added", None)
        if callable(added_fn):
            added_fn(context)


class MemorySessionCapability(BaseSessionCapability):
    """Wire long-term memory hooks during session startup without coupling `startup.py`."""

    capability_id = "memory"

    def __init__(self) -> None:
        self._provider: MemoryTurnContextProvider | None = None
        self._hooks: Any | None = None
        self._tool_ctx_token: Any | None = None
        self._history_arg: str = ""
        self._session_id: str = ""
        self._memory_mode: str = "shared"
        self._transport: Any | None = None

    def init_chat_flags(self) -> Mapping[str, Any]:
        return {"memory_enabled": is_memory_auto_enabled()}

    def on_llm_ready(self, context: StartupCapabilityContext) -> None:
        from ai.memory.operations import (
            bind_memory_tool_context,
            memory_rollback_count,
        )

        history_arg = str(getattr(context.args, "history", "") or "")
        resolved_session_id = session_id_for_history_path(history_arg) if history_arg else ""
        player_character = str(getattr(context.args, "player_character", "") or "").strip()
        raw_arg_mode = str(getattr(context.args, "memory_mode", "") or "").strip()
        open_store = peek_open_session_store(history_arg) if history_arg else None
        if raw_arg_mode:
            resolved_memory_mode = normalize_memory_mode(raw_arg_mode)
            if history_arg:
                open_store = open_session_store(history_arg)
                open_store.set_memory_mode(resolved_memory_mode)
        elif open_store is not None:
            resolved_memory_mode = open_store.get_memory_mode()
        else:
            resolved_memory_mode = ""

        self._history_arg = history_arg
        self._session_id = resolved_session_id
        self._memory_mode = resolved_memory_mode or "shared"

        self._tool_ctx_token = bind_memory_tool_context(
            session_id=resolved_session_id,
            memory_mode=resolved_memory_mode,
            player_character=player_character,
        )

        if context.hook_dispatcher is None:
            set_default_shared_memory_rollback(memory_rollback_count)
            return
        installer = getattr(context.runtime_imports, "install_memory_hooks", None)
        if not callable(installer):
            from ai.memory.hooks import install_memory_hooks

            installer = install_memory_hooks

        try:
            params = inspect.signature(installer).parameters
        except (TypeError, ValueError):
            params = {}
        has_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        candidate_kwargs: dict[str, Any] = {}
        if resolved_session_id:
            candidate_kwargs["session_id"] = resolved_session_id
            candidate_kwargs["last_turn_at"] = lambda: _last_dialogue_turn_at(history_arg)
        if resolved_memory_mode:
            candidate_kwargs["memory_mode"] = resolved_memory_mode
        read_mode_boundary = getattr(open_store, "get_memory_mode_start_seq", None)
        if callable(read_mode_boundary) and (boundary := read_mode_boundary()) is not None:
            candidate_kwargs["memory_mode_start_seq"] = boundary
        if player_character:
            candidate_kwargs["player_character"] = player_character
        extra_kwargs = {
            k: v for k, v in candidate_kwargs.items() if has_var_kw or k in params
        }

        hooks = installer(
            context.hook_dispatcher,
            llm_adapter=context.llm_adapter,
            character_names=list(context.character_names),
            **extra_kwargs,
        )
        self._hooks = hooks
        if hooks is not None:
            self._provider = MemoryTurnContextProvider(hooks)

        def _cascade_rollback(
            sid: str, turn_seq: int, *, protected_turn_seqs: Sequence[int] = (),
        ) -> int:
            removed_pending = 0
            hook_rb = getattr(self._hooks, "rollback_after_turn", None)
            if callable(hook_rb):
                removed_pending = rollback_memory_for_timeline(hook_rb, sid, turn_seq, protected_turn_seqs)
            return removed_pending + rollback_memory_for_timeline(
                memory_rollback_count, sid, turn_seq, protected_turn_seqs
            )

        set_default_shared_memory_rollback(_cascade_rollback)

    def configure_session_runtime(
        self,
        context: SessionRuntimeCapabilityContext,
    ) -> None:
        self._transport = context.transport
        if context.mode == "stream" and hasattr(context.transport, "emit"):
            context.transport.emit(
                {"type": "memory.mode", "memoryMode": self._memory_mode}
            )

    def command_handlers(self) -> Mapping[str, Callable[[object], None]]:
        return {"set-memory-mode": self._handle_set_memory_mode}

    def _handle_set_memory_mode(self, payload: object) -> None:
        from ai.memory.operations import update_memory_tool_context_mode

        raw = (
            payload.get("memoryMode")
            if isinstance(payload, Mapping)
            else payload
        )
        mode_text = str(raw or "").strip().lower()
        if mode_text not in {"isolated", "shared", "inherit_readonly"}:
            raise ValueError(
                "memoryMode must be 'isolated', 'shared', or 'inherit_readonly'"
            )
        mode = normalize_memory_mode(mode_text)
        last_seq = 0
        if self._history_arg:
            store = open_session_store(self._history_arg)
            store.set_memory_mode(mode)
            read_mode_boundary = getattr(store, "get_memory_mode_start_seq", None)
            if callable(read_mode_boundary):
                last_seq = read_mode_boundary() or 0
        self._memory_mode = mode
        set_hook_mode = getattr(self._hooks, "set_memory_mode", None)
        if callable(set_hook_mode):
            set_hook_mode(mode, up_to_seq=last_seq)
        elif self._hooks is not None:
            self._hooks.memory_mode = mode
        update_memory_tool_context_mode(self._session_id, mode)
        if self._transport is not None and hasattr(self._transport, "emit"):
            self._transport.emit({"type": "memory.mode", "memoryMode": mode})

    def on_shutdown(self) -> None:
        from ai.memory.operations import reset_memory_tool_context

        reset_memory_tool_context(self._tool_ctx_token)
        self._tool_ctx_token = None
        self._transport = None

    def turn_context_providers(self) -> Sequence[TurnContextProvider]:
        return (self._provider,) if self._provider is not None else ()
