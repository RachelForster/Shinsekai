"""Core domain models, two-tier caches, policy, and gatekeeper for real-time perception."""

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
    SceneType,
    normalize_scene_type,
)
from core.perception.pacing import (
    AdaptivePacingProfile,
    SceneActivitySignals,
    compute_adaptive_pacing,
    resolve_effective_scene,
)
from core.perception.policy import PerceptionMemoryPolicy, VisionMemoryPolicy
from core.perception.raw_buffer import PerceptionRawBuffer

__all__ = [
    "AdaptivePacingProfile",
    "CachedPerceptionEvent",
    "GatekeeperVerdict",
    "PERCEPTION_CONTEXT_MARKER",
    "PerceptionConfig",
    "PerceptionDigestResult",
    "PerceptionEvent",
    "PerceptionFrame",
    "PerceptionGatekeeper",
    "PerceptionMemoryPolicy",
    "PerceptionRawBuffer",
    "RPInputCache",
    "RawPerceptionSnapshot",
    "ReflexDecision",
    "SceneActivitySignals",
    "SceneType",
    "VisionMemoryPolicy",
    "compute_adaptive_pacing",
    "normalize_scene_type",
    "resolve_effective_scene",
]
