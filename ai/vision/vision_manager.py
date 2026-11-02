from __future__ import annotations

from collections.abc import Callable
from typing import Any

from config.adapter_extra_kwargs import filter_kwargs_for_ctor
from config.vision_defaults import (
    resolve_vision_api_key,
    resolve_vision_base_url,
    resolve_vision_model,
)

from ai.vision.deepseek_vision_adapter import DeepseekVisionAdapter
from ai.vision.moondream_adapter import MoondreamVisionAdapter
from ai.vision.provider_vision_adapters import (
    ChatGPTVisionAdapter,
    ClaudeVisionAdapter,
    DoubaoVisionAdapter,
    GeminiVisionAdapter,
    OllamaVisionAdapter,
    QwenVisionAdapter,
)
from ai.vision.vision_adapter import VisionAdapter


VisionAdapterFactory = Callable[[], VisionAdapter]


class VisionManager:
    """Resolve and invoke vision providers without leaking provider details to callers."""

    _builtin_adapters: dict[str, VisionAdapterFactory] = {
        "chatgpt": ChatGPTVisionAdapter,
        "claude": ClaudeVisionAdapter,
        "deepseek": DeepseekVisionAdapter,
        "doubao": DoubaoVisionAdapter,
        "gemini": GeminiVisionAdapter,
        "moondream": MoondreamVisionAdapter,
        "ollama": OllamaVisionAdapter,
        "qwen": QwenVisionAdapter,
    }
    _adapters = dict(_builtin_adapters)

    def __init__(
        self, provider: str = "moondream", *, api_config: Any | None = None
    ) -> None:
        provider_key = provider.strip().lower()
        factory = self._adapters.get(provider_key)
        if factory is None:
            supported = ", ".join(sorted(self._adapters))
            raise ValueError(f"不支持的视觉模型：{provider}。可用模型：{supported}")
        self.provider = provider_key
        if (
            api_config is not None
            and provider_key != "moondream"
            and factory is self._builtin_adapters.get(provider_key)
        ):
            schema = getattr(factory, "get_config_schema", lambda: {})()
            options = {
                key: field["default"]
                for key, field in schema.items()
                if "default" in field
            }
            options.update(
                (getattr(api_config, "vision_extra_configs", {}) or {}).get(
                    provider_key, {}
                )
                or {}
            )
            options.update(
                api_key=resolve_vision_api_key(api_config, provider_key),
                base_url=resolve_vision_base_url(api_config, provider_key),
                model=resolve_vision_model(api_config, provider_key),
            )
            self.adapter = factory(**filter_kwargs_for_ctor(factory, options))
        else:
            self.adapter = factory()

    @classmethod
    def register_adapter(cls, provider: str, factory: VisionAdapterFactory) -> None:
        key = provider.strip().lower()
        if not key:
            raise ValueError("视觉模型名称不能为空")
        cls._adapters[key] = factory

    def describe(self, image_bytes: bytes, prompt: str) -> str:
        return self.adapter.describe(image_bytes, prompt)
