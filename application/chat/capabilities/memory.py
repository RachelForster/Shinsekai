"""Session capability and turn context provider for automatic long-term memory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import inspect
import os
from typing import TYPE_CHECKING, Any

from application.chat.capabilities.contracts import (
    BaseSessionCapability,
    BaseTurnContextProvider,
    StartupCapabilityContext,
    TurnContextProvider,
)
from core.chat_history.sqlite_session_store import set_default_shared_memory_rollback
from core.chat_history.storage import session_id_for_history_path

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

    def init_chat_flags(self) -> Mapping[str, Any]:
        return {"memory_enabled": is_memory_auto_enabled()}

    def on_llm_ready(self, context: StartupCapabilityContext) -> None:
        from ai.memory.operations import memory_rollback_count

        history_arg = str(getattr(context.args, "history", "") or "")
        resolved_session_id = session_id_for_history_path(history_arg) if history_arg else ""

        if context.hook_dispatcher is None:
            set_default_shared_memory_rollback(memory_rollback_count)
            return
        installer = getattr(context.runtime_imports, "install_memory_hooks", None)
        if not callable(installer):
            from ai.memory.hooks import install_memory_hooks

            installer = install_memory_hooks

        extra_kwargs: dict[str, Any] = {}
        if resolved_session_id:
            try:
                params = inspect.signature(installer).parameters
            except (TypeError, ValueError):
                params = {}
            if "session_id" in params or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            ):
                extra_kwargs["session_id"] = resolved_session_id

        hooks = installer(
            context.hook_dispatcher,
            llm_adapter=context.llm_adapter,
            character_names=list(context.character_names),
            **extra_kwargs,
        )
        self._hooks = hooks
        if hooks is not None:
            self._provider = MemoryTurnContextProvider(hooks)

        def _cascade_rollback(sid: str, turn_seq: int) -> int:
            removed_pending = 0
            hook_rb = getattr(self._hooks, "rollback_after_turn", None)
            if callable(hook_rb):
                removed_pending = int(hook_rb(sid, turn_seq) or 0)
            return removed_pending + memory_rollback_count(sid, turn_seq)

        set_default_shared_memory_rollback(_cascade_rollback)

    def turn_context_providers(self) -> Sequence[TurnContextProvider]:
        return (self._provider,) if self._provider is not None else ()
