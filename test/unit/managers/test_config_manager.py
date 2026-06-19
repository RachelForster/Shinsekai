from __future__ import annotations

import os

import config.network_proxy as network_proxy
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


def _save_api_config_for_test(manager: ConfigManager, **overrides) -> str:
    params = {
        "llm_provider": "Deepseek",
        "llm_model": "deepseek-chat",
        "api_key": "sk-test",
        "base_url": "https://api.deepseek.com/v1",
        "is_streaming": "是",
        "tts_provider": "none",
        "sovits_url": "",
        "gpt_sovits_api_path": "",
        "t2i_provider": "comfyui",
        "t2i_url": "http://127.0.0.1:8188",
        "t2i_work_path": "",
        "t2i_default_workflow_path": "",
        "prompt_node_id": "6",
        "output_node_id": "9",
        "temperature": 0.7,
        "repetition_penalty": 1.0,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "max_context_tokens": 128000,
    }
    params.update(overrides)
    return manager.save_api_config_new(**params)


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


def test_save_api_config_new_rejects_local_tts_without_server_path():
    manager = _config_manager_with_api()
    saved = {}
    manager._save_single_config = lambda _path, data: saved.update(data)

    result = _save_api_config_for_test(
        manager,
        tts_provider="gpt-sovits",
        sovits_url="http://127.0.0.1:9880",
        gpt_sovits_api_path="",
    )

    assert "本地 TTS 引擎需要填写服务启动路径" in result
    assert saved == {}


def test_save_api_config_new_allows_remote_tts_without_server_path():
    manager = _config_manager_with_api()
    saved = {}
    manager._save_single_config = lambda _path, data: saved.update(data)

    result = _save_api_config_for_test(
        manager,
        tts_provider="gpt-sovits",
        sovits_url="https://example.trycloudflare.com",
        gpt_sovits_api_path="",
    )

    assert result == "API配置已保存！"
    assert saved["tts_provider"] == "gpt-sovits"
    assert saved["gpt_sovits_api_path"] == ""


def test_save_system_config_applies_network_proxy_environment(monkeypatch):
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
