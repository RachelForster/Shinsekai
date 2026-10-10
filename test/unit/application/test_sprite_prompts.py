import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from application.image_generation import prompts
from sdk.adapters.llm import LLMAdapter


def _config(provider="Custom LLM", api_key="configured-key"):
    return SimpleNamespace(
        get_llm_api_config=Mock(
            return_value=(
                provider,
                "configured-model",
                "http://configured-llm/v1",
                api_key,
            )
        ),
        merged_llm_factory_kwargs=Mock(
            side_effect=lambda provider, base: {**base, "custom_option": "existing"}
        ),
    )


def test_prompt_generation_uses_configured_adapter_with_a_fresh_text_request(
    monkeypatch,
):
    class Adapter(LLMAdapter):
        def __init__(self):
            super().__init__()
            self.requests = []

        def chat(self, messages, stream=False, **kwargs):
            self.requests.append((copy.deepcopy(messages), stream, kwargs))
            message = SimpleNamespace(content='{"prompts":["wave pose","calm pose"]}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    adapter = Adapter()
    factory = Mock(return_value=adapter)
    monkeypatch.setattr(prompts.LLMAdapterFactory, "create_adapter", factory)
    config = _config()
    result = prompts.generate_sprite_prompts(
        config, character_name="Rafal", character_setting="理性、冷静。", count=2
    )
    assert result == ["wave pose", "calm pose"]
    config.merged_llm_factory_kwargs.assert_called_once_with(
        "Custom LLM",
        {
            "llm_provider": "Custom LLM",
            "model": "configured-model",
            "base_url": "http://configured-llm/v1",
            "api_key": "configured-key",
        },
    )
    factory.assert_called_once_with(
        llm_provider="Custom LLM",
        model="configured-model",
        base_url="http://configured-llm/v1",
        api_key="configured-key",
        custom_option="existing",
    )
    assert len(adapter.requests) == 1
    messages, stream, options = adapter.requests[0]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert json.loads(messages[1]["content"]) == {
        "name": "Rafal",
        "setting": "理性、冷静。",
        "count": 2,
    }
    assert messages[0]["content"] == prompts.SPRITE_PROMPT_INSTRUCTION
    assert stream is False
    assert options["tools"] is None
    assert options["response_format"] == {"type": "text"}


@pytest.mark.parametrize("provider,key", [("Ollama", "ollama"), ("Local plugin", "")])
def test_local_llm_does_not_require_a_cloud_api_key(monkeypatch, provider, key):
    factory = Mock()
    manager = Mock()
    manager.return_value.chat.return_value = '["wave"]'
    monkeypatch.setattr(prompts.LLMAdapterFactory, "create_adapter", factory)
    monkeypatch.setattr(prompts, "LLMManager", manager)
    config = _config(provider, api_key="")
    assert prompts.generate_sprite_prompts(
        config, character_name="Rafal", character_setting="", count=1
    ) == ["wave"]
    assert factory.call_args.kwargs["api_key"] == key


@pytest.mark.parametrize(
    "raw", ['[" wave\\npose "]', '```json\n{"prompts":[" wave pose "]}\n```']
)
def test_prompt_results_accept_arrays_and_fenced_objects_and_keep_one_line(raw):
    assert prompts._parse_prompts(raw, 1) == ["wave pose"]


@pytest.mark.parametrize(
    "raw", [None, "", "explanation only", "{}", "[42]", '[""]', "[]", '["one", "two"]']
)
def test_empty_malformed_or_wrong_count_results_fail_instead_of_reporting_success(raw):
    with pytest.raises(ValueError, match="LLM"):
        prompts._parse_prompts(raw, 1)


def test_llm_errors_are_propagated_without_retry(monkeypatch):
    manager = Mock()
    manager.return_value.chat.side_effect = RuntimeError(
        "configured service unavailable"
    )
    factory = Mock()
    monkeypatch.setattr(prompts.LLMAdapterFactory, "create_adapter", factory)
    monkeypatch.setattr(prompts, "LLMManager", manager)
    with pytest.raises(RuntimeError, match="configured service unavailable"):
        prompts.generate_sprite_prompts(
            _config(), character_name="Rafal", character_setting="", count=1
        )
    manager.return_value.chat.assert_called_once()


@pytest.mark.parametrize("provider,model", [("", "model"), ("Custom", "")])
def test_incomplete_llm_configuration_fails_before_creating_an_adapter(
    monkeypatch, provider, model
):
    factory = Mock()
    monkeypatch.setattr(prompts.LLMAdapterFactory, "create_adapter", factory)
    config = _config()
    config.get_llm_api_config.return_value = (provider, model, "", "")
    with pytest.raises(ValueError, match="配置 LLM"):
        prompts.generate_sprite_prompts(
            config, character_name="Rafal", character_setting="", count=1
        )
    factory.assert_not_called()


@pytest.mark.parametrize("count", [0, 101, True])
def test_invalid_count_does_not_call_the_llm(count):
    config = _config()
    with pytest.raises(ValueError, match="count"):
        prompts.generate_sprite_prompts(
            config, character_name="Rafal", character_setting="", count=count
        )
    config.get_llm_api_config.assert_not_called()


def test_legacy_generator_can_write_prompts_without_constructing_a_gemini_client(
    monkeypatch,
):
    from tools import generate_sprites as legacy

    client = Mock(side_effect=AssertionError("Gemini client must not be created"))
    generate = Mock(return_value=["wave pose"])
    monkeypatch.setattr(legacy.genai, "Client", client)
    monkeypatch.setattr(prompts, "generate_sprite_prompts", generate)
    assert legacy.ImageGenerator().generate_prompts(1, "冷静") == ["wave pose"]
    generate.assert_called_once_with(
        legacy.config, character_name="", character_setting="冷静", count=1
    )
    client.assert_not_called()
