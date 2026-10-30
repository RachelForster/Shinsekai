from types import SimpleNamespace

import pytest

from config.schema import ApiConfig
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


@pytest.mark.parametrize("provider", [None, "auto", " AUTO "])
def test_legacy_saved_default_does_not_pin_automatic_vision(provider):
    saved = {
        "llm_provider": "Deepseek",
        "llm_model": {"Deepseek": "current-vision-model"},
        "vision_model": {"deepseek": "deepseek-flash", "chatgpt": "custom-image-model"},
    }
    if provider is not None:
        saved["vision_provider"] = provider
    config = ApiConfig.model_validate(saved)
    assert resolve_vision_model(config, "deepseek") == "current-vision-model"
    assert config.vision_model == {"chatgpt": "custom-image-model"}
    assert config.vision_config_version == 1
    assert saved["vision_model"]["deepseek"] == "deepseek-flash"


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("deepseek", "deepseek-flash"),
        ("auto", "custom-vision-model"),
    ],
)
def test_legacy_explicit_provider_and_custom_models_are_preserved(provider, model):
    config = ApiConfig.model_validate(
        {
            "vision_provider": provider,
            "vision_model": {"deepseek": model},
            "llm_model": {"Deepseek": "current-vision-model"},
        }
    )
    assert resolve_vision_model(config, "deepseek") == model


def test_migration_stays_complete_after_save_and_preserves_a_new_explicit_default(
    tmp_path,
):
    import yaml

    config = ApiConfig.model_validate(
        {
            "vision_provider": "auto",
            "vision_model": {"deepseek": "deepseek-flash"},
            "llm_model": {"Deepseek": "current-vision-model"},
        }
    )
    path = tmp_path / "api.yaml"
    path.write_text(yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8")
    reloaded = ApiConfig.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )
    assert resolve_vision_model(reloaded, "deepseek") == "current-vision-model"
    reloaded.vision_model["deepseek"] = "deepseek-flash"
    path.write_text(yaml.safe_dump(reloaded.model_dump(mode="json")), encoding="utf-8")
    explicit = ApiConfig.model_validate(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )
    assert resolve_vision_model(explicit, "deepseek") == "deepseek-flash"


def test_legacy_default_is_migrated_even_when_another_llm_is_currently_selected():
    config = ApiConfig.model_validate(
        {
            "vision_provider": "auto",
            "vision_model": {"deepseek": "deepseek-flash"},
            "llm_provider": "ChatGPT",
            "llm_model": {"Deepseek": "new-deepseek-model", "ChatGPT": "image-model"},
        }
    )
    config.llm_provider = "Deepseek"
    assert resolve_vision_provider(config) == "deepseek"
    assert resolve_vision_model(config, "deepseek") == "new-deepseek-model"
