"""Core domain models, two-tier caches, and gatekeeper for real-time perception."""

from core.perception.cache import PERCEPTION_CONTEXT_MARKER, RPInputCache
from core.perception.gatekeeper import GatekeeperVerdict, PerceptionGatekeeper
from core.perception.models import (
    CachedPerceptionEvent,
    PerceptionConfig,
    PerceptionDigestResult,
    PerceptionEvent,
    PerceptionFrame,
    RawPerceptionSnapshot,
    ReflexDecision,
)
from core.perception.raw_buffer import PerceptionRawBuffer

__all__ = [
    "CachedPerceptionEvent",
    "GatekeeperVerdict",
    "PERCEPTION_CONTEXT_MARKER",
    "PerceptionConfig",
    "PerceptionDigestResult",
    "PerceptionEvent",
    "PerceptionFrame",
    "PerceptionGatekeeper",
    "PerceptionRawBuffer",
    "RPInputCache",
    "RawPerceptionSnapshot",
    "ReflexDecision",
]
