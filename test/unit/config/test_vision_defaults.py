from types import SimpleNamespace

from config.vision_defaults import (
    resolve_vision_api_key,
    resolve_vision_base_url,
    resolve_vision_provider,
    resolve_vision_model,
)


def test_vision_uses_corresponding_llm_provider_credentials():
    config = SimpleNamespace(
        llm_api_key={"Deepseek": "llm-key"},
        llm_base_urls={"Deepseek": "https://proxy.example.com/v1"},
        llm_provider="ChatGPT",
        llm_base_url="https://api.openai.com/v1",
    )

    assert resolve_vision_api_key(config, "deepseek") == "llm-key"
    assert resolve_vision_base_url(config, "deepseek") == "https://proxy.example.com/v1"


def test_vision_base_url_supports_legacy_active_provider_config():
    config = SimpleNamespace(
        llm_api_key={"Deepseek": "llm-key"},
        llm_base_urls={},
        llm_provider="Deepseek",
        llm_base_url="https://legacy-proxy.example.com/v1",
    )

    assert (
        resolve_vision_base_url(config, "deepseek")
        == "https://legacy-proxy.example.com/v1"
    )


def test_auto_vision_follows_llm_and_inherits_model_until_overridden():
    config = SimpleNamespace(
        vision_provider="auto",
        llm_provider="ChatGPT",
        llm_model={"ChatGPT": "current-image-model"},
        vision_model={},
    )
    assert resolve_vision_provider(config) == "chatgpt"
    assert resolve_vision_model(config, "chatgpt") == "current-image-model"
    config.llm_provider = "通义千问"
    assert resolve_vision_provider(config) == "qwen"
    config.vision_provider = "deepseek"
    config.vision_model = {"deepseek": "explicit-vision-model"}
    assert resolve_vision_provider(config) == "deepseek"
    assert resolve_vision_model(config, "deepseek") == "explicit-vision-model"


def test_unknown_llm_keeps_the_automatic_plugin_fallback():
    assert (
        resolve_vision_provider(
            SimpleNamespace(vision_provider="auto", llm_provider="custom-text-only")
        )
        == "auto"
    )
