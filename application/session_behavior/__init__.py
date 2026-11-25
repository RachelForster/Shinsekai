"""Internal application-layer contracts and runtime collaborators for SessionBehavior."""

from application.session_behavior.casting import CastBinding, CastingMap
from application.session_behavior.prefetch import (
    PrefetchHandle,
    SpeculativePrefetchCoordinator,
)
from application.session_behavior.protocol import (
    BehaviorCommand,
    BehaviorOption,
    BehaviorStateEnvelope,
    BehaviorTransition,
    CommandIdempotencyCache,
    CommandResolution,
    InteractionPolicy,
    PlaybackEndAction,
    SessionBehavior,
    parse_behavior_command,
)


def __getattr__(name: str):
    if name == "SessionBehaviorCapability":
        from application.session_behavior.capability import SessionBehaviorCapability

        return SessionBehaviorCapability
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BehaviorCommand",
    "BehaviorOption",
    "BehaviorStateEnvelope",
    "BehaviorTransition",
    "CastBinding",
    "CastingMap",
    "CommandIdempotencyCache",
    "CommandResolution",
    "InteractionPolicy",
    "PlaybackEndAction",
    "PrefetchHandle",
    "SessionBehavior",
    "SessionBehaviorCapability",
    "SpeculativePrefetchCoordinator",
    "parse_behavior_command",
]
