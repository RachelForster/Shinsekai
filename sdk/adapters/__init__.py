"""Abstract adapter bases and provider contributions for plugin subsystems."""

from sdk.adapters.asr import ASRAdapter, TranscriptionCallback
from sdk.adapters.llm import LLMAdapter
from sdk.adapters.t2i import T2IAdapter
from sdk.adapters.tts import TTSAdapter
from sdk.adapters.vision import (
    VisionAdapter,
    VisionAdapterFactory,
    VisionAvailabilityProbe,
    VisionFallbackContribution,
)

__all__ = [
    "ASRAdapter",
    "LLMAdapter",
    "T2IAdapter",
    "TTSAdapter",
    "TranscriptionCallback",
    "VisionAdapter",
    "VisionAdapterFactory",
    "VisionAvailabilityProbe",
    "VisionFallbackContribution",
]
