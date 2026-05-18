from __future__ import annotations

from config.config_manager import ConfigManager
from config.schema import AppConfig, ApiConfig, Background, Character, SystemConfig


def _config_manager_with_api(**api_overrides) -> ConfigManager:
    manager = object.__new__(ConfigManager)
    api_config = ApiConfig(
        llm_provider=api_overrides.pop("llm_provider", "Deepseek"),
        llm_api_key=api_overrides.pop("llm_api_key", {"Deepseek": "sk-test"}),
        llm_model=api_overrides.pop("llm_model", {"Deepseek": "deepseek-chat"}),
        **api_overrides,
    )
    manager._config = AppConfig(
        api_config=api_config,
        system_config=SystemConfig(),
        characters=[Character(name="Test", color="#ffffff", sprite_prefix="test")],
        background_list=[Background(name="Default", sprite_prefix="default")],
    )
    return manager


def test_get_llm_api_config_defaults_known_provider_base_url_when_empty():
    manager = _config_manager_with_api(
        llm_provider="Deepseek",
        llm_base_url="   ",
    )

    provider, model, base_url, api_key = manager.get_llm_api_config()

    assert provider == "Deepseek"
    assert model == "deepseek-chat"
    assert base_url == "https://api.deepseek.com/v1"
    assert api_key == "sk-test"


def test_get_llm_api_config_keeps_saved_base_url():
    manager = _config_manager_with_api(
        llm_provider="Deepseek",
        llm_base_url="https://proxy.example.com/v1",
    )

    _, _, base_url, _ = manager.get_llm_api_config()

    assert base_url == "https://proxy.example.com/v1"
