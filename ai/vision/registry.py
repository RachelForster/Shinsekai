"""Vision adapter registry and provider registration helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ai.vision.vision_adapter import VisionAdapter
from core.adapters import AdapterRegistration, AdapterRegistry

VisionAdapterFactory = Callable[..., VisionAdapter]


def _normalize_vision_key(key: str) -> str:
    return str(key or "").strip().lower()


def _load_chatgpt_vision() -> VisionAdapterFactory:
    from ai.vision.provider_vision_adapters import ChatGPTVisionAdapter

    return ChatGPTVisionAdapter


def _load_claude_vision() -> VisionAdapterFactory:
    from ai.vision.provider_vision_adapters import ClaudeVisionAdapter

    return ClaudeVisionAdapter


def _load_deepseek_vision() -> VisionAdapterFactory:
    from ai.vision.deepseek_vision_adapter import DeepseekVisionAdapter

    return DeepseekVisionAdapter


def _load_doubao_vision() -> VisionAdapterFactory:
    from ai.vision.provider_vision_adapters import DoubaoVisionAdapter

    return DoubaoVisionAdapter


def _load_gemini_vision() -> VisionAdapterFactory:
    from ai.vision.provider_vision_adapters import GeminiVisionAdapter

    return GeminiVisionAdapter


def _load_moondream_vision() -> VisionAdapterFactory:
    from ai.vision.moondream_adapter import MoondreamVisionAdapter

    return MoondreamVisionAdapter


def _load_ollama_vision() -> VisionAdapterFactory:
    from ai.vision.provider_vision_adapters import OllamaVisionAdapter

    return OllamaVisionAdapter


def _load_qwen_vision() -> VisionAdapterFactory:
    from ai.vision.provider_vision_adapters import QwenVisionAdapter

    return QwenVisionAdapter


_BUILTIN_VISION_SPECS: tuple[tuple[str, Callable[[], VisionAdapterFactory], str, int], ...] = (
    ("chatgpt", _load_chatgpt_vision, "OpenAI Vision", 10),
    ("claude", _load_claude_vision, "Claude Vision", 20),
    ("deepseek", _load_deepseek_vision, "DeepSeek Vision", 30),
    ("doubao", _load_doubao_vision, "豆包视觉", 40),
    ("gemini", _load_gemini_vision, "Gemini Vision", 50),
    ("moondream", _load_moondream_vision, "Moondream（本地）", 60),
    ("ollama", _load_ollama_vision, "Ollama Vision（本地）", 70),
    ("qwen", _load_qwen_vision, "通义千问视觉", 80),
)


def configure_builtin_vision_adapters(
    registry: AdapterRegistry[VisionAdapter] | None = None,
) -> None:
    """Idempotently register all built-in vision backend factories."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    for key, loader, label, order in _BUILTIN_VISION_SPECS:
        target.register_builtin(key, loader=loader, label=label, order=order)


def create_vision_adapter_registry(
    *,
    include_builtins: bool = True,
) -> AdapterRegistry[VisionAdapter]:
    """Create a standalone Vision adapter registry."""
    registry: AdapterRegistry[VisionAdapter] = AdapterRegistry(
        "Vision",
        key_normalizer=_normalize_vision_key,
        builtin_registrar=configure_builtin_vision_adapters if include_builtins else None,
    )
    if include_builtins:
        registry.configure_builtins()
    return registry


_DEFAULT_REGISTRY: AdapterRegistry[VisionAdapter] = AdapterRegistry(
    "Vision",
    key_normalizer=_normalize_vision_key,
    builtin_registrar=configure_builtin_vision_adapters,
)


def get_vision_adapter_registry() -> AdapterRegistry[VisionAdapter]:
    """Return the process-wide default Vision adapter registry."""
    return _DEFAULT_REGISTRY


def register_vision_adapter(
    provider: str,
    factory: VisionAdapterFactory,
    *,
    label: str = "",
    order: int = 100,
    default_kwargs: Mapping[str, Any] | None = None,
    registry: AdapterRegistry[VisionAdapter] | None = None,
) -> AdapterRegistration[VisionAdapter]:
    """Register a vision adapter class/factory onto ``registry`` (or the default)."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    return target.register(
        provider,
        factory,
        label=label,
        order=order,
        default_kwargs=default_kwargs,
    )


def list_vision_adapters(
    registry: AdapterRegistry[VisionAdapter] | None = None,
) -> tuple[AdapterRegistration[VisionAdapter], ...]:
    """Return all registered Vision entries in deterministic order."""
    target = registry if registry is not None else _DEFAULT_REGISTRY
    return target.entries()
