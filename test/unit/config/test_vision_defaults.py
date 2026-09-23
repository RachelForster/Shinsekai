from types import SimpleNamespace

from config.vision_defaults import resolve_vision_api_key


def test_resolve_vision_api_key_uses_dedicated_key_by_default():
    config = SimpleNamespace(
        llm_api_key={"Deepseek": "llm-key"},
        vision_api_key={"deepseek": "vision-key"},
        vision_extra_configs={},
    )

    assert resolve_vision_api_key(config, "deepseek") == "vision-key"


def test_resolve_vision_api_key_can_reuse_corresponding_llm_key():
    config = SimpleNamespace(
        llm_api_key={"Deepseek": "llm-key"},
        vision_api_key={"deepseek": "vision-key"},
        vision_extra_configs={"deepseek": {"reuse_llm_api_key": True}},
    )

    assert resolve_vision_api_key(config, "deepseek") == "llm-key"
