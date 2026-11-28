"""Vision provider resolution facade backed by :mod:`ai.vision.registry`."""

from __future__ import annotations

from typing import Any

from ai.vision.registry import (
    VisionAdapterFactory,
    get_vision_adapter_registry,
    register_vision_adapter,
)
from config.adapter_extra_kwargs import filter_kwargs_for_ctor
from config.vision_defaults import (
    resolve_vision_api_key,
    resolve_vision_base_url,
    resolve_vision_model,
)

_DEFAULT_VISION_REGISTRY = get_vision_adapter_registry()
_DEFAULT_VISION_ADAPTERS_VIEW = _DEFAULT_VISION_REGISTRY.as_mutable_mapping()


class VisionManager:
    """Resolve and invoke vision providers without leaking provider details to callers."""

    _builtin_adapters: dict[str, VisionAdapterFactory] = dict(
        _DEFAULT_VISION_REGISTRY.builtin_snapshot()
    )
    _adapters = _DEFAULT_VISION_ADAPTERS_VIEW

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
        if cls._adapters is _DEFAULT_VISION_ADAPTERS_VIEW:
            register_vision_adapter(key, factory)
        else:
            cls._adapters[key] = factory

    def describe(self, image_bytes: bytes, prompt: str) -> str:
        return self.adapter.describe(image_bytes, prompt)
