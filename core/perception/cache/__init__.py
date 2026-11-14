"""Tier-1 Vision Memory (`core.perception.cache`) package."""

from core.perception.cache.episodes import (
    EpisodeArchive,
    build_fallback_episode_summary,
    merge_fallback_overall_summary,
)
from core.perception.cache.formatter import (
    PERCEPTION_CONTEXT_MARKER,
    PROACTIVE_EVENT_MAX_AGE_SEC,
    PROACTIVE_TURN_INSTRUCTION,
)
from core.perception.cache.memory import RPInputCache
from core.perception.cache.tracks import (
    SubtitleTrack,
    VisualTrack,
    is_ambient_reaction_bark,
)
from core.perception.policy import PerceptionMemoryPolicy, VisionMemoryPolicy

__all__ = [
    "EpisodeArchive",
    "PERCEPTION_CONTEXT_MARKER",
    "PROACTIVE_EVENT_MAX_AGE_SEC",
    "PROACTIVE_TURN_INSTRUCTION",
    "PerceptionMemoryPolicy",
    "RPInputCache",
    "SubtitleTrack",
    "VisionMemoryPolicy",
    "VisualTrack",
    "build_fallback_episode_summary",
    "is_ambient_reaction_bark",
    "merge_fallback_overall_summary",
]
