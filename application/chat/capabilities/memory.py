"""Session capability and turn context provider for automatic long-term memory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from typing import TYPE_CHECKING, Any

from application.chat.capabilities.contracts import (
    BaseSessionCapability,
    BaseTurnContextProvider,
    StartupCapabilityContext,
    TurnContextProvider,
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

    def init_chat_flags(self) -> Mapping[str, Any]:
        return {"memory_enabled": is_memory_auto_enabled()}

    def on_llm_ready(self, context: StartupCapabilityContext) -> None:
        if context.hook_dispatcher is None:
            return
        installer = getattr(context.runtime_imports, "install_memory_hooks", None)
        if not callable(installer):
            from ai.memory.hooks import install_memory_hooks

            installer = install_memory_hooks
        hooks = installer(
            context.hook_dispatcher,
            llm_adapter=context.llm_adapter,
            character_names=list(context.character_names),
        )
        if hooks is not None:
            self._provider = MemoryTurnContextProvider(hooks)

    def turn_context_providers(self) -> Sequence[TurnContextProvider]:
        return (self._provider,) if self._provider is not None else ()
