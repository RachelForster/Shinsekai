from types import SimpleNamespace

from config.vision_defaults import resolve_vision_api_key, resolve_vision_base_url


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

    assert resolve_vision_base_url(config, "deepseek") == "https://legacy-proxy.example.com/v1"
