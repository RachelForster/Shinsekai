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


def test_save_api_config_new_persists_token_budget_settings():
    manager = _config_manager_with_api()
    saved = {}
    manager._save_single_config = lambda _path, data: saved.update(data)

    manager.save_api_config_new(
        "Deepseek",
        "deepseek-chat",
        "sk-test",
        "https://api.deepseek.com/v1",
        "是",
        "none",
        "",
        "",
        "comfyui",
        "http://127.0.0.1:8188",
        "",
        "",
        "6",
        "9",
        0.7,
        1.0,
        0.0,
        0.0,
        128000,
        compact_threshold=0.45,
        compact_target_ratio=0.25,
        history_recent_messages=12,
        max_tool_result_chars=4000,
        max_active_tool_groups=2,
    )

    assert manager.config.api_config.compact_threshold == 0.45
    assert manager.config.api_config.compact_target_ratio == 0.25
    assert manager.config.api_config.history_recent_messages == 12
    assert manager.config.api_config.max_tool_result_chars == 4000
    assert manager.config.api_config.max_active_tool_groups == 2
    assert saved["compact_threshold"] == 0.45
    assert saved["compact_target_ratio"] == 0.25
    assert saved["max_active_tool_groups"] == 2


def test_save_api_config_new_clamps_compact_target_below_threshold():
    manager = _config_manager_with_api()
    saved = {}
    manager._save_single_config = lambda _path, data: saved.update(data)

    manager.save_api_config_new(
        "Deepseek",
        "deepseek-chat",
        "sk-test",
        "https://api.deepseek.com/v1",
        "是",
        "none",
        "",
        "",
        "comfyui",
        "http://127.0.0.1:8188",
        "",
        "",
        "6",
        "9",
        0.7,
        1.0,
        0.0,
        0.0,
        128000,
        compact_threshold=0.4,
        compact_target_ratio=0.4,
    )

    assert manager.config.api_config.compact_threshold == 0.4
    assert manager.config.api_config.compact_target_ratio == 0.35
    assert saved["compact_target_ratio"] == 0.35
