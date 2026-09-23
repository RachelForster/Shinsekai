"""Built-in vision-provider defaults and LLM credential sharing helpers."""

from __future__ import annotations

from typing import Any


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
    "deepseek": "https://api.deepseek.com",
    "chatgpt": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "claude": "https://api.anthropic.com/v1",
    "doubao": "https://ark.cn-beijing.volces.com/api/v3",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "ollama": "http://127.0.0.1:11434/v1",
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


def vision_reuses_llm_api_key(api_config: Any, provider: str) -> bool:
    provider_key = str(provider or "").strip().lower()
    try:
        extra = (getattr(api_config, "vision_extra_configs", {}) or {}).get(
            provider_key, {}
        )
        return bool(extra.get("reuse_llm_api_key", False))
    except (AttributeError, TypeError):
        return False


def resolve_vision_api_key(api_config: Any, provider: str) -> str:
    """Return the dedicated key or the matching LLM provider key."""

    provider_key = str(provider or "").strip().lower()
    try:
        if vision_reuses_llm_api_key(api_config, provider_key):
            llm_provider = VISION_PROVIDER_LLM_PROVIDER.get(provider_key, "")
            return str(
                (getattr(api_config, "llm_api_key", {}) or {}).get(llm_provider, "")
                or ""
            ).strip()
        return str(
            (getattr(api_config, "vision_api_key", {}) or {}).get(provider_key, "")
            or ""
        ).strip()
    except (AttributeError, TypeError):
        return ""


def vision_provider_requires_api_key(provider: str) -> bool:
    provider_key = str(provider or "").strip().lower()
    return provider_key not in VISION_PROVIDERS_WITHOUT_API_KEY


__all__ = [
    "VISION_BASE_URLS",
    "VISION_DEFAULT_MODELS",
    "VISION_PROVIDER_LLM_PROVIDER",
    "VISION_PROVIDERS_WITHOUT_API_KEY",
    "resolve_vision_api_key",
    "vision_provider_requires_api_key",
    "vision_reuses_llm_api_key",
]
