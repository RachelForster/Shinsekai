"""Abstract adapter bases and provider contributions for plugin subsystems."""

from sdk.adapters.asr import ASRAdapter, TranscriptionCallback
from sdk.adapters.avatar import (
    AvatarFormatContribution,
    ModelAssetAdapter,
    ModelCapabilities,
    ModelFiles,
    ModelRuntimeInstaller,
)
from sdk.adapters.llm import LLMAdapter
from sdk.adapters.memory import (
    EmbeddingProvider,
    EmbeddingProviderContribution,
    MemoryExtractorPort,
    MemoryRepository,
    MemoryRepositoryContribution,
    RecallPlanner,
    RetentionPolicy,
    StaticVectorStorePort,
)
from sdk.llm_response import ChatResponse, ResponseCodec, ResponseDelta
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
    "AvatarFormatContribution",
    "LLMAdapter",
    "EmbeddingProvider",
    "EmbeddingProviderContribution",
    "MemoryExtractorPort",
    "MemoryRepository",
    "MemoryRepositoryContribution",
    "RecallPlanner",
    "RetentionPolicy",
    "StaticVectorStorePort",
    "ChatResponse",
    "ResponseCodec",
    "ResponseDelta",
    "ModelAssetAdapter",
    "ModelCapabilities",
    "ModelFiles",
    "ModelRuntimeInstaller",
    "T2IAdapter",
    "TTSAdapter",
    "TranscriptionCallback",
    "VisionAdapter",
    "VisionAdapterFactory",
    "VisionAvailabilityProbe",
    "VisionFallbackContribution",
]
