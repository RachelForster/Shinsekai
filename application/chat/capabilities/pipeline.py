"""Orchestrators for `TurnContextProvider` pipelines and `SessionCapability` sets."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import threading
from typing import Any

from application.chat.capabilities.contracts import (
    BaseTurnContextProvider,
    PluginLoadedCapabilityContext,
    SessionCapability,
    SessionRuntimeCapabilityContext,
    StartupCapabilityContext,
    StreamingWiringCapabilityContext,
    TurnAdmissionDecision,
    TurnAdmissionRequest,
    TurnContextProvider,
    TurnUserPromptEnvelope,
)


def _provider_observes_hook(provider: TurnContextProvider, method_name: str) -> bool:
    """Return whether `provider` needs pipeline forwarding for `method_name`."""
    if getattr(provider, "delegates_to_hook_dispatcher", False):
        return False
    base_method = getattr(BaseTurnContextProvider, method_name)
    instance_dict = getattr(provider, "__dict__", None)
    if isinstance(instance_dict, Mapping) and method_name in instance_dict:
        return callable(instance_dict[method_name])
    cls_method = getattr(type(provider), method_name, None)
    if cls_method is not None:
        return callable(cls_method) and cls_method is not base_method
    return callable(getattr(provider, method_name, None))


class TurnContextPipeline:
    """Execute registered `TurnContextProvider`s uniformly for each chat turn."""

    def __init__(
        self,
        providers: Iterable[TurnContextProvider] = (),
    ) -> None:
        self._lock = threading.RLock()
        self._providers: list[TurnContextProvider] = []
        self._dispatchers: list[Any] = []
        self._before_chat_dispatcher_ids: set[int] = set()
        self._message_added_dispatcher_ids: set[int] = set()
        for provider in providers:
            self.register(provider)

    def register(
        self,
        provider: TurnContextProvider,
        *,
        replace_existing: bool = True,
    ) -> None:
        capability_id = str(getattr(provider, "capability_id", "") or "").strip()
        if not capability_id:
            raise ValueError("TurnContextProvider.capability_id must not be empty")
        with self._lock:
            if replace_existing:
                self._providers = [
                    existing
                    for existing in self._providers
                    if existing.capability_id != capability_id
                ]
            elif any(
                existing.capability_id == capability_id
                for existing in self._providers
            ):
                return
            self._providers.append(provider)
            dispatchers = tuple(self._dispatchers)
        for dispatcher in dispatchers:
            self._sync_dispatcher_hooks(dispatcher)

    def unregister(self, capability_id: str) -> bool:
        target = str(capability_id or "").strip()
        with self._lock:
            before = len(self._providers)
            self._providers = [
                existing
                for existing in self._providers
                if existing.capability_id != target
            ]
            return len(self._providers) < before

    def providers(self) -> tuple[TurnContextProvider, ...]:
        with self._lock:
            return tuple(self._providers)

    def get(self, capability_id: str) -> TurnContextProvider | None:
        target = str(capability_id or "").strip()
        with self._lock:
            for provider in self._providers:
                if provider.capability_id == target:
                    return provider
        return None

    def admit_turn(self, request: TurnAdmissionRequest) -> TurnAdmissionDecision:
        source = str(request.source or "user").strip() or "user"
        record_user_message = source == "user"

        legacy_prepare = (
            getattr(request.runtime, "prepare_perception_turn", None)
            if request.runtime is not None
            else None
        )
        if callable(legacy_prepare):
            if not legacy_prepare(request.history_turn_id, source):
                return TurnAdmissionDecision(
                    admitted=False,
                    record_user_message=False,
                )

        for provider in self.providers():
            decision = provider.admit_turn(request)
            if decision is None:
                continue
            if not decision.admitted:
                return TurnAdmissionDecision(
                    admitted=False,
                    record_user_message=False,
                )
            record_user_message = record_user_message and bool(
                decision.record_user_message
            )

        return TurnAdmissionDecision(
            admitted=True,
            record_user_message=record_user_message,
        )

    def collect_user_prompt(
        self,
        request: TurnAdmissionRequest,
    ) -> TurnUserPromptEnvelope:
        background: Mapping[str, str | int] | None = None
        prefixes: list[str] = []
        suffixes: list[str] = []
        for provider in self.providers():
            contribution = provider.contribute_user_prompt(request)
            if contribution is None:
                continue
            if contribution.background is not None:
                background = contribution.background
            if contribution.prefix and contribution.prefix.strip():
                prefixes.append(contribution.prefix.strip())
            if contribution.suffix and contribution.suffix.strip():
                suffixes.append(contribution.suffix.strip())
        return TurnUserPromptEnvelope(
            background=background,
            prefix="\n\n".join(prefixes),
            suffix="\n\n".join(suffixes),
        )

    def register_dispatcher_hooks(self, dispatcher: Any) -> None:
        """Bind custom providers' `before_chat` / `message_added` callbacks onto `dispatcher`."""
        self._sync_dispatcher_hooks(dispatcher)

    def _sync_dispatcher_hooks(self, dispatcher: Any) -> None:
        if dispatcher is None:
            return
        with self._lock:
            dispatcher_id = id(dispatcher)
            if all(id(existing) != dispatcher_id for existing in self._dispatchers):
                self._dispatchers.append(dispatcher)
            need_before_chat = (
                dispatcher_id not in self._before_chat_dispatcher_ids
                and hasattr(dispatcher, "register_before_chat")
                and any(
                    _provider_observes_hook(provider, "before_chat")
                    for provider in self._providers
                )
            )
            need_message_added = (
                dispatcher_id not in self._message_added_dispatcher_ids
                and hasattr(dispatcher, "register_message_added")
                and any(
                    _provider_observes_hook(provider, "message_added")
                    for provider in self._providers
                )
            )
            if need_before_chat:
                self._before_chat_dispatcher_ids.add(dispatcher_id)
            if need_message_added:
                self._message_added_dispatcher_ids.add(dispatcher_id)
        if need_before_chat:
            dispatcher.register_before_chat(
                self._dispatch_before_chat_from_hook_dispatcher,
                label="turn_context_pipeline_before_chat",
            )
        if need_message_added:
            dispatcher.register_message_added(
                self._dispatch_message_added_from_hook_dispatcher,
                label="turn_context_pipeline_message_added",
            )

    def _dispatch_before_chat_from_hook_dispatcher(self, context: Any) -> None:
        for provider in self.providers():
            if not _provider_observes_hook(provider, "before_chat"):
                continue
            provider.before_chat(context)

    def _dispatch_message_added_from_hook_dispatcher(self, context: Any) -> None:
        for provider in self.providers():
            if not _provider_observes_hook(provider, "message_added"):
                continue
            provider.message_added(context)

    def dispatch_before_chat(self, context: Any) -> None:
        for provider in self.providers():
            provider.before_chat(context)

    def dispatch_message_added(self, context: Any) -> None:
        for provider in self.providers():
            provider.message_added(context)


class SessionCapabilitySet:
    """Coordinate ordered `SessionCapability` modules across a chat session's lifecycle."""

    def __init__(
        self,
        capabilities: Iterable[SessionCapability] = (),
        *,
        default_turn_providers: Iterable[TurnContextProvider] = (),
    ) -> None:
        self._capabilities: list[SessionCapability] = []
        self._default_turn_providers: tuple[TurnContextProvider, ...] = tuple(
            default_turn_providers
        )
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: SessionCapability) -> None:
        capability_id = str(getattr(capability, "capability_id", "") or "").strip()
        if not capability_id:
            raise ValueError("SessionCapability.capability_id must not be empty")
        self._capabilities = [
            existing
            for existing in self._capabilities
            if existing.capability_id != capability_id
        ]
        self._capabilities.append(capability)

    def capabilities(self) -> tuple[SessionCapability, ...]:
        return tuple(self._capabilities)

    def get(self, capability_id: str) -> SessionCapability | None:
        target = str(capability_id or "").strip()
        for capability in self._capabilities:
            if capability.capability_id == target:
                return capability
        return None

    def on_plugins_loaded(self, context: PluginLoadedCapabilityContext) -> None:
        for capability in self._capabilities:
            capability.on_plugins_loaded(context)

    def on_llm_ready(self, context: StartupCapabilityContext) -> None:
        for capability in self._capabilities:
            capability.on_llm_ready(context)

    def collect_init_chat_flags(self) -> dict[str, Any]:
        flags: dict[str, Any] = {}
        for capability in self._capabilities:
            flags.update(capability.init_chat_flags())
        return flags

    def build_turn_context_pipeline(self) -> TurnContextPipeline:
        pipeline = TurnContextPipeline(self._default_turn_providers)
        for capability in self._capabilities:
            for provider in capability.turn_context_providers():
                pipeline.register(provider)
        return pipeline

    def configure_session_runtime(
        self,
        context: SessionRuntimeCapabilityContext,
    ) -> None:
        pipeline = getattr(context.app_runtime, "turn_context_pipeline", None)
        for capability in self._capabilities:
            capability.configure_session_runtime(context)
            if isinstance(pipeline, TurnContextPipeline):
                for provider in capability.turn_context_providers():
                    pipeline.register(provider)
        if isinstance(pipeline, TurnContextPipeline):
            llm_manager = getattr(context.startup, "llm_manager", None)
            pipeline.register_dispatcher_hooks(
                getattr(llm_manager, "hook_dispatcher", None)
            )

    def bind_streaming_session(
        self,
        context: StreamingWiringCapabilityContext,
    ) -> None:
        for capability in self._capabilities:
            capability.bind_streaming_session(context)

    def on_session_ready(self) -> None:
        for capability in self._capabilities:
            capability.on_session_ready()

    def command_handlers(self) -> dict[str, Callable[[object], None]]:
        handlers: dict[str, Callable[[object], None]] = {}
        for capability in self._capabilities:
            handlers.update(capability.command_handlers())
        return handlers

    def compose_pre_shutdown(
        self,
        primary: Callable[[], None] | None = None,
    ) -> Callable[[], None] | None:
        actions = [
            action
            for capability in self._capabilities
            if (action := capability.pre_shutdown_action()) is not None
        ]
        if not actions:
            return primary

        def run_pre_shutdown() -> None:
            for action in actions:
                action()
            if primary is not None:
                primary()

        return run_pre_shutdown

    def on_shutdown(self) -> None:
        for capability in reversed(self._capabilities):
            capability.on_shutdown()
