"""Built-in LLM provider defaults used by configuration surfaces."""

from collections.abc import Mapping
from typing import Any

from sdk.adapters.storage import ReadableDocument

# Add a dictionary to map LLM providers to their default base URLs
LLM_BASE_URLS = {
    "Deepseek": "https://api.deepseek.com/v1",
    "ChatGPT": "https://api.openai.com/v1",
    "Gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "Claude": "https://api.anthropic.com/v1",
    "豆包": "https://ark.cn-beijing.volces.com/api/v3",
    "通义千问": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "Ollama": "http://127.0.0.1:11434/v1"
}

# Add a dictionary to map LLM providers to their available models
LLM_MODELS = {
    "Deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "ChatGPT": ["gpt-4o", "gpt-4", "gpt-3.5-turbo"],
    "Gemini": ["gemini-pro"],
    "Claude": ["claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"],
    "豆包": ["doubao-seed-1.6", "doubao-seed-1.6-flash", "doubao-seed-1.6-thinking"],
    "通义千问": ["qwen-max", "qwen-plus"],
    "Ollama": []
}

DASHSCOPE_PROVIDER_KEYWORDS = ("通义", "qwen", "dashscope")


def resolve_llm_base_url(api_config: Any, provider: str) -> str:
    """Resolve a provider URL from the per-provider map with legacy fallback."""

    provider_key = str(provider or "").strip()
    if not provider_key:
        return ""
    try:
        mapped = str(
            (getattr(api_config, "llm_base_urls", {}) or {}).get(provider_key, "")
            or ""
        ).strip()
        if mapped:
            return mapped
        active_provider = str(getattr(api_config, "llm_provider", "") or "").strip()
        if active_provider == provider_key:
            legacy = str(getattr(api_config, "llm_base_url", "") or "").strip()
            if legacy:
                return legacy
    except (AttributeError, TypeError):
        pass
    return str(LLM_BASE_URLS.get(provider_key, "") or "").strip()


def extract_llm_api_credentials(api_config: Any) -> tuple[str, str, str, str]:
    """Extract ``(provider, model, base_url, api_key)`` from an ``ApiConfig`` snapshot."""
    llm_provider = str(getattr(api_config, "llm_provider", "") or "")
    llm_api_keys = getattr(api_config, "llm_api_key", None) or {}
    llm_models = getattr(api_config, "llm_model", None) or {}
    api_key = str(llm_api_keys.get(llm_provider, "") or "")
    model = str(llm_models.get(llm_provider, "") or "")
    base_url = resolve_llm_base_url(api_config, llm_provider)
    return llm_provider, model, base_url, api_key


def merge_llm_factory_kwargs(
    api_config: Any,
    llm_provider: str,
    base_kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge adapter extra kwargs for ``llm_provider`` over ``base_kwargs``."""
    out = dict(base_kwargs)
    extra_map = getattr(api_config, "llm_extra_configs", None) or {}
    provider_key = str(llm_provider or "").strip()
    extra = extra_map.get(provider_key, {}) or {}
    if isinstance(extra, Mapping):
        out.update(extra)
    return out


def resolve_llm_api_credentials(source: Any) -> tuple[str, str, str, str]:
    """Read ``(provider, model, base_url, api_key)`` from a doc port, ApiConfig, or ConfigManager."""
    if isinstance(source, ReadableDocument):
        return extract_llm_api_credentials(source.get())
    getter = getattr(source, "get_llm_api_config", None)
    if callable(getter):
        return getter()
    return extract_llm_api_credentials(source)


def resolve_llm_factory_kwargs(
    source: Any,
    llm_provider: str,
    base_kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve merged LLM adapter kwargs from a doc port, ApiConfig, or ConfigManager."""
    if isinstance(source, ReadableDocument):
        return merge_llm_factory_kwargs(source.get(), llm_provider, base_kwargs)
    merger = getattr(source, "merged_llm_factory_kwargs", None)
    if callable(merger):
        return merger(llm_provider, dict(base_kwargs))
    return merge_llm_factory_kwargs(source, llm_provider, base_kwargs)
