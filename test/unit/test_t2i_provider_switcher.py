import yaml

from t2i import provider_switcher


def _write_api(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _read_api(path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_list_profiles_seeds_primary_and_fallback_configs(tmp_path, monkeypatch):
    api_path = tmp_path / "api.yaml"
    _write_api(
        api_path,
        {
            "t2i_extra_configs": {
                "openai-image": {
                    "api_url": "https://primary.example",
                    "api_key": "primary-key",
                    "model": "gpt-image-2",
                    "size": "auto",
                    "fallback_configs": [
                        {
                            "api_url": "https://fallback.example",
                            "api_key": "fallback-key",
                            "model": "grok-imagine-image",
                        }
                    ],
                }
            }
        },
    )
    monkeypatch.setattr(provider_switcher, "API_CONFIG", api_path)

    profiles = provider_switcher.list_t2i_api_profiles()

    assert profiles == ["GPT Image 2", "Grok Imagine"]
    data = _read_api(api_path)
    assert data["t2i_active_api_profile"] == "GPT Image 2"
    assert data["t2i_api_profiles"]["GPT Image 2"]["api_key"] == "primary-key"
    assert data["t2i_api_profiles"]["Grok Imagine"]["api_key"] == "fallback-key"


def test_switch_t2i_api_profile_applies_profile_to_openai_image(tmp_path, monkeypatch):
    api_path = tmp_path / "api.yaml"
    _write_api(
        api_path,
        {
            "t2i_api_profiles": {
                "GPT Image 2": {
                    "api_url": "https://primary.example",
                    "api_key": "primary-key",
                    "model": "gpt-image-2",
                    "response_format": "b64_json",
                    "moderation": "low",
                },
                "Grok Imagine": {
                    "api_url": "https://fallback.example",
                    "api_key": "fallback-key",
                    "model": "grok-imagine-image",
                    "response_format": "b64_json",
                    "moderation": "",
                },
            }
        },
    )
    monkeypatch.setattr(provider_switcher, "API_CONFIG", api_path)

    active = provider_switcher.switch_t2i_api_profile("Grok Imagine")

    data = _read_api(api_path)
    assert active == "Grok Imagine"
    assert data["t2i_provider"] == "openai-image"
    assert data["t2i_api_url"] == "https://fallback.example"
    assert data["t2i_active_api_profile"] == "Grok Imagine"
    openai = data["t2i_extra_configs"]["openai-image"]
    assert openai["api_key"] == "fallback-key"
    assert openai["model"] == "grok-imagine-image"
    assert "fallback_configs" not in openai
