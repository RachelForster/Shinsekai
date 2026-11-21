from __future__ import annotations

import os
from unittest.mock import MagicMock

import config.network_proxy as network_proxy
from config.config_manager import ConfigManager
from config.feature_flags import FeatureFlag
from config.schema import ApiConfig, AppConfig, Background, Character, SystemConfig
from config.sprite_voice import normalize_sprite_voice_types


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


def test_config_manager_exposes_centralized_feature_flags():
    manager = _config_manager_with_api()
    manager.config.system_config.story_system_enabled = True

    assert manager.feature_flags.is_enabled(FeatureFlag.STORY_SYSTEM)


def test_invalid_persisted_story_flag_does_not_abort_config_load():
    manager = _config_manager_with_api()
    manager.config.system_config = SystemConfig.model_validate(
        {"story_system_enabled": "maybe"}
    )

    resolution = manager.feature_flags.resolve(FeatureFlag.STORY_SYSTEM)

    assert manager.config.system_config.story_system_enabled is False
    assert resolution.enabled is False
    assert resolution.diagnostic == "invalid boolean value 'maybe'; failed closed"


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


def test_normalize_sprite_voice_types_preserves_explicit_voice_type():
    data = {
        "name": "Mika",
        "sprites": [
            {"path": "sprite.png", "voice_path": "voice.wav", "voice_type": "preset"},
            {"path": "ref.png", "voice_path": "ref.wav", "voice_text": "hello", "voice_type": "reference"},
        ],
    }

    normalized = normalize_sprite_voice_types(data)

    assert normalized["sprites"][0]["voice_type"] == "preset"
    assert normalized["sprites"][1]["voice_type"] == "reference"


def test_normalize_sprite_voice_types_infers_legacy_voice_type_when_missing():
    data = {
        "name": "Mika",
        "sprites": [
            {"path": "sprite.png", "voice_path": "voice.wav"},
            {"path": "ref.png", "voice_path": "ref.wav", "voice_text": "hello"},
        ],
    }

    normalized = normalize_sprite_voice_types(data)

    assert normalized["sprites"][0]["voice_type"] == "fallback"
    assert normalized["sprites"][1]["voice_type"] == "reference"


def test_get_llm_api_config_keeps_saved_base_url():
    manager = _config_manager_with_api(
        llm_provider="Deepseek",
        llm_base_url="https://proxy.example.com/v1",
    )

    _, _, base_url, _ = manager.get_llm_api_config()

    assert base_url == "https://proxy.example.com/v1"


def test_save_api_config_persists_clamped_token_budget_settings(tmp_path):
    manager = _config_manager_with_api(
        compact_threshold=0.4,
        compact_target_ratio=0.4,
        history_recent_messages=12,
        max_tool_result_chars=4000,
        max_active_tool_groups=2,
    )
    saved = {}
    manager._API_CONFIG_PATH = tmp_path / "api.yaml"
    manager._save_single_config = lambda _path, data: saved.update(data)

    manager.save_api_config()

    assert manager.config.api_config.compact_threshold == 0.4
    assert manager.config.api_config.compact_target_ratio == 0.35
    assert saved["compact_threshold"] == 0.4
    assert saved["compact_target_ratio"] == 0.35
    assert saved["history_recent_messages"] == 12
    assert saved["max_tool_result_chars"] == 4000
    assert saved["max_active_tool_groups"] == 2


def test_config_manager_delegates_to_injected_backend():
    backend = MagicMock()
    backend.characters_revision = "rev-1"
    backend.load_api_config.return_value = ApiConfig(llm_provider="ChatGPT")
    backend.load_system_config.return_value = SystemConfig(ui_language="ja")
    char = Character(name="Mika", color="#ffffff", sprite_prefix="mika")
    backend.list_characters.return_value = [char]
    backend.list_backgrounds.return_value = []
    backend.list_effects.return_value = []
    backend.save_characters.return_value = "rev-2"

    manager = object.__new__(ConfigManager)
    manager._backend = backend
    manager._config = None
    manager.reload()

    assert manager.config.api_config.llm_provider == "ChatGPT"
    assert manager.config.system_config.ui_language == "ja"
    assert manager.characters_revision == "rev-1"

    manager.save_characters_config()
    backend.save_characters.assert_called_once()
    backend.characters_revision = "rev-2"
    assert manager.characters_revision == "rev-2"


def test_save_system_config_applies_network_proxy_environment(monkeypatch, tmp_path):
    for name in (
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "SOCKS_PROXY",
        "socks_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.setitem(network_proxy._ORIGINAL_PROXY_ENV, name, None)
    monkeypatch.setattr("config.config_manager.apply_mirror_environment", lambda _config: None)
    manager = _config_manager_with_api()
    saved = {}
    manager._SYSTEM_CONFIG_PATH = tmp_path / "system_config.yaml"
    manager._save_single_config = lambda _path, data: saved.update(data)
    manager.config.system_config = SystemConfig(
        http_proxy_url="http://127.0.0.1:7890",
        https_proxy_url="http://127.0.0.1:7890",
        mirror_auto_detect_china=False,
        network_proxy_enabled=True,
        socks5_proxy_url="socks5://127.0.0.1:7891",
    )

    manager.save_system_config()

    assert saved["network_proxy_enabled"] is True
    assert saved["http_proxy_url"] == "http://127.0.0.1:7890"
    assert saved["https_proxy_url"] == "http://127.0.0.1:7890"
    assert saved["socks5_proxy_url"] == "socks5://127.0.0.1:7891"
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7890"
    assert os.environ["ALL_PROXY"] == "socks5://127.0.0.1:7891"
