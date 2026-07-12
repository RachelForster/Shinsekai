from __future__ import annotations

from collections.abc import Callable

from ai.vision.moondream_adapter import MoondreamVisionAdapter
from ai.vision.vision_adapter import VisionAdapter


VisionAdapterFactory = Callable[[], VisionAdapter]


class VisionManager:
    """Resolve and invoke vision providers without leaking provider details to callers."""

    _adapters: dict[str, VisionAdapterFactory] = {
        "moondream": MoondreamVisionAdapter,
    }

    def __init__(self, provider: str = "moondream") -> None:
        provider_key = provider.strip().lower()
        factory = self._adapters.get(provider_key)
        if factory is None:
            supported = ", ".join(sorted(self._adapters))
            raise ValueError(f"不支持的视觉模型：{provider}。可用模型：{supported}")
        self.provider = provider_key
        self.adapter = factory()

    @classmethod
    def register_adapter(cls, provider: str, factory: VisionAdapterFactory) -> None:
        key = provider.strip().lower()
        if not key:
            raise ValueError("视觉模型名称不能为空")
        cls._adapters[key] = factory

    def describe(self, image_bytes: bytes, prompt: str) -> str:
        return self.adapter.describe(image_bytes, prompt)

