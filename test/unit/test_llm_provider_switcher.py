import yaml

from llm import provider_switcher


def _write_api(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _read_api(path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_list_profiles_seeds_current_and_saved_llm_providers(tmp_path, monkeypatch):
    api_path = tmp_path / "api.yaml"
    _write_api(
        api_path,
        {
            "llm_provider": "Claude",
            "llm_base_url": "https://anthropic.example",
            "llm_model": {
                "Claude": "claude-test",
                "ChatGPT": "gpt-test",
            },
            "llm_api_key": {
                "Claude": "claude-key",
                "ChatGPT": "gpt-key",
            },
            "llm_extra_configs": {
                "Claude": {"thinking_enabled": True},
            },
            "temperature": 0.5,
        },
    )
    monkeypatch.setattr(provider_switcher, "API_CONFIG", api_path)

    profiles = provider_switcher.list_llm_api_profiles()

    assert profiles == ["Claude - claude-test", "ChatGPT - gpt-test"]
    data = _read_api(api_path)
    assert data["llm_active_api_profile"] == "Claude - claude-test"
    assert data["llm_api_profiles"]["Claude - claude-test"]["api_key"] == "claude-key"
    assert data["llm_api_profiles"]["Claude - claude-test"]["extra_config"] == {
        "thinking_enabled": True
    }


def test_switch_llm_api_profile_applies_provider_model_key_and_extra(
    tmp_path, monkeypatch
):
    api_path = tmp_path / "api.yaml"
    _write_api(
        api_path,
        {
            "llm_provider": "Claude",
            "llm_model": {"Claude": "old-model"},
            "llm_api_key": {"Claude": "old-key"},
            "llm_api_profiles": {
                "GPT": {
                    "provider": "ChatGPT",
                    "base_url": "https://openai.example/v1",
                    "model": "gpt-test",
                    "api_key": "gpt-key",
                    "is_streaming": False,
                    "temperature": 0.2,
                    "max_context_tokens": 64000,
                    "extra_config": {"custom": "value"},
                }
            },
        },
    )
    monkeypatch.setattr(provider_switcher, "API_CONFIG", api_path)

    active = provider_switcher.switch_llm_api_profile("GPT")

    data = _read_api(api_path)
    assert active == "GPT"
    assert data["llm_provider"] == "ChatGPT"
    assert data["llm_base_url"] == "https://openai.example/v1"
    assert data["llm_model"]["ChatGPT"] == "gpt-test"
    assert data["llm_api_key"]["ChatGPT"] == "gpt-key"
    assert data["llm_extra_configs"]["ChatGPT"] == {"custom": "value"}
    assert data["is_streaming"] is False
    assert data["temperature"] == 0.2
    assert data["max_context_tokens"] == 64000
