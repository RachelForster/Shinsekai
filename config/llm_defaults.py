"""Built-in LLM provider defaults used by configuration surfaces."""

from typing import Any

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
