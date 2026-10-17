"""Built-in vision-provider defaults and shared provider credentials."""

from __future__ import annotations

from typing import Any

from config.llm_defaults import LLM_BASE_URLS, resolve_llm_base_url


VISION_PROVIDER_LLM_PROVIDER = {
    "deepseek": "Deepseek",
    "chatgpt": "ChatGPT",
    "gemini": "Gemini",
    "claude": "Claude",
    "doubao": "豆包",
    "qwen": "通义千问",
    "ollama": "Ollama",
}

VISION_BASE_URLS = {
    provider: LLM_BASE_URLS.get(llm_provider, "")
    for provider, llm_provider in VISION_PROVIDER_LLM_PROVIDER.items()
}

VISION_DEFAULT_MODELS = {
    "deepseek": "deepseek-flash",
    "chatgpt": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
    "claude": "claude-3-5-sonnet-latest",
    "doubao": "",
    "qwen": "qwen-vl-max",
    "ollama": "llava",
}

VISION_PROVIDERS_WITHOUT_API_KEY = frozenset({"ollama"})


def vision_llm_provider(provider: str) -> str:
    return VISION_PROVIDER_LLM_PROVIDER.get(str(provider or "").strip().lower(), "")


def resolve_vision_api_key(api_config: Any, provider: str) -> str:
    """Return the key owned by the corresponding LLM provider."""

    llm_provider = vision_llm_provider(provider)
    if not llm_provider:
        return ""
    try:
        return str(
            (getattr(api_config, "llm_api_key", {}) or {}).get(llm_provider, "")
            or ""
        ).strip()
    except (AttributeError, TypeError):
        return ""


def resolve_vision_base_url(api_config: Any, provider: str) -> str:
    """Return the URL owned by the corresponding LLM provider."""

    return resolve_llm_base_url(api_config, vision_llm_provider(provider))


def vision_provider_requires_api_key(provider: str) -> bool:
    provider_key = str(provider or "").strip().lower()
    return provider_key not in VISION_PROVIDERS_WITHOUT_API_KEY


__all__ = [
    "VISION_BASE_URLS",
    "VISION_DEFAULT_MODELS",
    "VISION_PROVIDER_LLM_PROVIDER",
    "VISION_PROVIDERS_WITHOUT_API_KEY",
    "resolve_vision_api_key",
    "resolve_vision_base_url",
    "vision_llm_provider",
    "vision_provider_requires_api_key",
]
