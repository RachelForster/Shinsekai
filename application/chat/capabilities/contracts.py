"""Contracts for pluggable chat session capabilities and per-turn context providers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sdk.hooks import BeforeChatContext, MessageAddedContext, PluginHookDispatcher


@dataclass(frozen=True, slots=True)
class TurnAdmissionRequest:
    """Metadata describing one dequeued user/proactive turn before LLM execution."""

    history_turn_id: str
    source: str = "user"
    text: str = ""
    attachment_count: int = 0
    runtime: Any = None


@dataclass(frozen=True, slots=True)
class TurnAdmissionDecision:
    """Outcome of capability turn admission before `LLMWorker` enters `LLMManager.chat`."""

    admitted: bool = True
    record_user_message: bool = True


@dataclass(frozen=True, slots=True)
class TurnUserPromptContribution:
    """Optional per-turn user-prompt additions contributed by a `TurnContextProvider`."""

    background: Mapping[str, str | int] | None = None
    prefix: str = ""
    suffix: str = ""


@dataclass(frozen=True, slots=True)
class TurnUserPromptEnvelope:
    """Aggregated per-turn user-prompt enrichments collected across providers."""

    background: Mapping[str, str | int] | None = None
    prefix: str = ""
    suffix: str = ""

    @property
    def has_enrichment(self) -> bool:
        return bool(self.background or self.prefix or self.suffix)


@dataclass(frozen=True, slots=True)
class PluginLoadedCapabilityContext:
    """Context passed to capabilities right after the plugin host is loaded."""

    args: Any
    config: Any
    plugin_manager: Any | None
    hook_dispatcher: PluginHookDispatcher | None
    transport: Any | None = None


@dataclass(frozen=True, slots=True)
class StartupCapabilityContext:
    """Context passed to capabilities after `LLMManager` is constructed during startup."""

    args: Any
    config: Any
    llm_adapter: Any
    llm_manager: Any
    plugin_manager: Any | None
    hook_dispatcher: PluginHookDispatcher | None
    character_names: tuple[str, ...]
    primary_character_names: tuple[str, ...] | None = None
    runtime_imports: Any = None


@dataclass(frozen=True, slots=True)
class SessionRuntimeCapabilityContext:
    """Context passed to capabilities when `ChatSession` assembles its live runtime."""

    mode: str
    args: Any
    config: Any
    startup: Any
    transport: Any
    runtime: Any
    ui_updates: Any
    chat_turn_service: Any
    app_runtime: Any


@dataclass(frozen=True, slots=True)
class StreamingWiringCapabilityContext:
    """Context passed to capabilities after realtime streaming bindings are wired."""

    bindings: Any
    app_runtime: Any


@runtime_checkable
class TurnContextProvider(Protocol):
    """Per-turn admission, prompt enrichment, and message observation contract."""

    @property
    def capability_id(self) -> str: ...

    def admit_turn(
        self,
        request: TurnAdmissionRequest,
    ) -> TurnAdmissionDecision | None: ...

    def contribute_user_prompt(
        self,
        request: TurnAdmissionRequest,
    ) -> TurnUserPromptContribution | None: ...

    def before_chat(self, context: BeforeChatContext) -> None: ...

    def message_added(self, context: MessageAddedContext) -> None: ...


class BaseTurnContextProvider:
    """Default no-op implementation of `TurnContextProvider`."""

    capability_id: str = "unnamed_provider"
    delegates_to_hook_dispatcher: bool = False

    def admit_turn(
        self,
        request: TurnAdmissionRequest,
    ) -> TurnAdmissionDecision | None:
        del request
        return None

    def contribute_user_prompt(
        self,
        request: TurnAdmissionRequest,
    ) -> TurnUserPromptContribution | None:
        del request
        return None

    def before_chat(self, context: BeforeChatContext) -> None:
        del context

    def message_added(self, context: MessageAddedContext) -> None:
        del context


@runtime_checkable
class SessionCapability(Protocol):
    """Session-scoped feature module decoupled from `ChatSession` and `LLMWorker`."""

    @property
    def capability_id(self) -> str: ...

    def on_plugins_loaded(self, context: PluginLoadedCapabilityContext) -> None: ...

    def on_llm_ready(self, context: StartupCapabilityContext) -> None: ...

    def init_chat_flags(self) -> Mapping[str, Any]: ...

    def configure_session_runtime(
        self,
        context: SessionRuntimeCapabilityContext,
    ) -> None: ...

    def bind_streaming_session(
        self,
        context: StreamingWiringCapabilityContext,
    ) -> None: ...

    def on_session_ready(self) -> None: ...

    def turn_context_providers(self) -> Sequence[TurnContextProvider]: ...

    def command_handlers(self) -> Mapping[str, Callable[[object], None]]: ...

    def pre_shutdown_action(self) -> Callable[[], None] | None: ...

    def on_shutdown(self) -> None: ...


class BaseSessionCapability:
    """Default no-op implementation of `SessionCapability`."""

    capability_id: str = "unnamed_capability"

    def on_plugins_loaded(self, context: PluginLoadedCapabilityContext) -> None:
        del context

    def on_llm_ready(self, context: StartupCapabilityContext) -> None:
        del context

    def init_chat_flags(self) -> Mapping[str, Any]:
        return {}

    def configure_session_runtime(
        self,
        context: SessionRuntimeCapabilityContext,
    ) -> None:
        del context

    def bind_streaming_session(
        self,
        context: StreamingWiringCapabilityContext,
    ) -> None:
        del context

    def on_session_ready(self) -> None:
        return None

    def turn_context_providers(self) -> Sequence[TurnContextProvider]:
        return ()

    def command_handlers(self) -> Mapping[str, Callable[[object], None]]:
        return {}

    def pre_shutdown_action(self) -> Callable[[], None] | None:
        return None

    def on_shutdown(self) -> None:
        return None
