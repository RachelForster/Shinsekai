"""Pluggable `SessionCapability` and `TurnContextProvider` abstractions."""

from __future__ import annotations

from typing import Any

from application.chat.capabilities.background import BackgroundTurnContextProvider
from application.chat.capabilities.contracts import (
    BaseSessionCapability,
    BaseTurnContextProvider,
    PluginLoadedCapabilityContext,
    SessionCapability,
    SessionRuntimeCapabilityContext,
    StartupCapabilityContext,
    StreamingWiringCapabilityContext,
    TurnAdmissionDecision,
    TurnAdmissionRequest,
    TurnContextProvider,
    TurnUserPromptContribution,
    TurnUserPromptEnvelope,
)
from application.chat.capabilities.knowledge import (
    KnowledgeSessionCapability,
    KnowledgeTurnContextProvider,
)
from application.chat.capabilities.memory import (
    MemorySessionCapability,
    MemoryTurnContextProvider,
    is_memory_auto_enabled,
)
from application.chat.capabilities.perception import (
    PERCEPTION_CONFIG_KEYS,
    PerceptionSessionCapability,
    PerceptionTurnContextProvider,
)
from application.chat.capabilities.pipeline import (
    SessionCapabilitySet,
    TurnContextPipeline,
)
from application.chat.capabilities.relation import (
    RELATION_CONTEXT_MARKER,
    RelationSessionCapability,
    RelationTurnContextProvider,
)


def build_default_turn_context_pipeline() -> TurnContextPipeline:
    """Create the default worker-side `TurnContextPipeline`."""
    return TurnContextPipeline((BackgroundTurnContextProvider(),))


def build_default_session_capabilities() -> SessionCapabilitySet:
    """Compose the built-in session capabilities for a chat runtime."""
    return SessionCapabilitySet(
        (
            KnowledgeSessionCapability(),
            MemorySessionCapability(),
            RelationSessionCapability(),
            PerceptionSessionCapability(),
        ),
        default_turn_providers=(BackgroundTurnContextProvider(),),
    )


def get_turn_context_pipeline(runtime: Any) -> TurnContextPipeline:
    """Return `runtime.turn_context_pipeline`, lazily attaching a default pipeline if absent."""
    pipeline = getattr(runtime, "turn_context_pipeline", None)
    if isinstance(pipeline, TurnContextPipeline):
        return pipeline
    pipeline = build_default_turn_context_pipeline()
    if runtime is not None:
        try:
            runtime.turn_context_pipeline = pipeline
        except Exception:
            pass
    return pipeline


__all__ = [
    "BackgroundTurnContextProvider",
    "BaseSessionCapability",
    "BaseTurnContextProvider",
    "KnowledgeSessionCapability",
    "KnowledgeTurnContextProvider",
    "MemorySessionCapability",
    "MemoryTurnContextProvider",
    "PERCEPTION_CONFIG_KEYS",
    "PerceptionSessionCapability",
    "PerceptionTurnContextProvider",
    "PluginLoadedCapabilityContext",
    "RELATION_CONTEXT_MARKER",
    "RelationSessionCapability",
    "RelationTurnContextProvider",
    "SessionCapability",
    "SessionCapabilitySet",
    "SessionRuntimeCapabilityContext",
    "StartupCapabilityContext",
    "StreamingWiringCapabilityContext",
    "TurnAdmissionDecision",
    "TurnAdmissionRequest",
    "TurnContextPipeline",
    "TurnContextProvider",
    "TurnUserPromptContribution",
    "TurnUserPromptEnvelope",
    "build_default_session_capabilities",
    "build_default_turn_context_pipeline",
    "get_turn_context_pipeline",
    "is_memory_auto_enabled",
]
