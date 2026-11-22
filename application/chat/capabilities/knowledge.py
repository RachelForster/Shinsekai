"""Session capability and turn context provider for character knowledge retrieval."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from application.chat.capabilities.contracts import (
    BaseSessionCapability,
    BaseTurnContextProvider,
    PluginLoadedCapabilityContext,
    TurnContextProvider,
)

if TYPE_CHECKING:
    from sdk.hooks import BeforeChatContext


class KnowledgeTurnContextProvider(BaseTurnContextProvider):
    """Adapt `KnowledgeHooks` to the `TurnContextProvider` contract."""

    capability_id = "knowledge"
    delegates_to_hook_dispatcher = True

    def __init__(self, hooks: Any) -> None:
        self.hooks = hooks

    def before_chat(self, context: BeforeChatContext) -> None:
        before_fn = getattr(self.hooks, "before_chat", None)
        if callable(before_fn):
            before_fn(context)


class KnowledgeSessionCapability(BaseSessionCapability):
    """Register remote character knowledge hooks when enabled and transport-supported."""

    capability_id = "knowledge"

    def __init__(self) -> None:
        self._provider: KnowledgeTurnContextProvider | None = None

    def on_plugins_loaded(self, context: PluginLoadedCapabilityContext) -> None:
        api_config = getattr(getattr(context.config, "config", None), "api_config", None)
        knowledge_enabled = bool(getattr(api_config, "knowledge_enabled", False))
        search = getattr(context.transport, "knowledge_search", None)
        status = getattr(context.transport, "knowledge_status", None)
        if (
            not knowledge_enabled
            or context.hook_dispatcher is None
            or search is None
            or status is None
        ):
            return
        from application.knowledge.hooks import install_knowledge_hooks

        hooks = install_knowledge_hooks(
            context.hook_dispatcher,
            search_func=search,
            status_func=status,
        )
        if hooks is not None:
            self._provider = KnowledgeTurnContextProvider(hooks)

    def turn_context_providers(self) -> Sequence[TurnContextProvider]:
        return (self._provider,) if self._provider is not None else ()
