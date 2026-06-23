"""Unit tests for LLM adapters — parameter filtering, config schema, mocks."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

try:
    import openai as _openai  # noqa: F401
except ModuleNotFoundError:
    fake_openai = ModuleType("openai")

    class _OpenAI:
        def __init__(self, api_key=None, base_url=None):
            self.api_key = api_key
            self.base_url = base_url

    fake_openai.OpenAI = _OpenAI
    sys.modules["openai"] = fake_openai

from llm.llm_adapter import (
    _raise_if_http_client_error,
    SUPPORTED_CHAT_PARAMS,
    ClaudeAdapter,
    DeepSeekAdapter,
    OpenAIAdapter,
    filter_supported_chat_params,
)
from llm.claude_url import normalize_claude_base_url_for_sdk


class TestFilterSupportedChatParams:
    def test_passes_supported_params(self):
        result = filter_supported_chat_params("OpenAIAdapter", {"temperature": 0.5, "max_tokens": 100})
        assert result["temperature"] == 0.5
        assert result["max_tokens"] == 100

    def test_strips_unsupported_params(self):
        result = filter_supported_chat_params("OpenAIAdapter", {"temperature": 0.5, "unknown_param": 42})
        assert "unknown_param" not in result
        assert result["temperature"] == 0.5


class TestDeepSeekAdapter:
    def test_init_stores_model(self):
        adapter = DeepSeekAdapter(api_key="sk-test", base_url="https://api.deepseek.com", model="deepseek-chat")
        assert adapter.model == "deepseek-chat"
        assert adapter.client.base_url == "https://api.deepseek.com"

    def test_get_config_schema_returns_dict(self):
        schema = DeepSeekAdapter.get_config_schema()
        assert isinstance(schema, dict)
        assert "thinking_enabled" in schema

    def test_thinking_disabled_by_default(self):
        adapter = DeepSeekAdapter(api_key="sk-test", base_url="https://api.deepseek.com", model="deepseek-chat")
        assert adapter.thinking_enabled is False

    def test_rethrows_openai_http_client_errors(self):
        error_cls = type("APITimeoutError", (Exception,), {"__module__": "openai"})

        class _Completions:
            def create(self, **kwargs):
                raise error_cls("request timed out")

        adapter = DeepSeekAdapter(api_key="sk-test", base_url="https://api.deepseek.com", model="deepseek-chat")
        adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))

        with pytest.raises(error_cls):
            adapter.chat(messages=[{"role": "user", "content": "Hi"}], stream=False)

    def test_keeps_legacy_none_for_non_http_errors(self):
        class _Completions:
            def create(self, **kwargs):
                raise ValueError("bad payload")

        adapter = DeepSeekAdapter(api_key="sk-test", base_url="https://api.deepseek.com", model="deepseek-chat")
        adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))

        assert adapter.chat(messages=[{"role": "user", "content": "Hi"}], stream=False) is None


def test_raise_if_http_client_error_ignores_non_http_errors():
    assert _raise_if_http_client_error(ValueError("plain")) is None


class TestOpenAIAdapter:
    def test_init_stores_model(self):
        adapter = OpenAIAdapter(api_key="sk-test", base_url="https://api.openai.com", model="gpt-4")
        assert adapter.model == "gpt-4"
        assert adapter.client.base_url == "https://api.openai.com"

    def test_gemini_unsupported_params(self):
        unsupported = OpenAIAdapter.get_unsupported_chat_params("Gemini")
        assert "frequency_penalty" in unsupported
        assert "presence_penalty" in unsupported

    def test_user_template_set_get(self):
        adapter = OpenAIAdapter(api_key="sk-xxx", base_url="https://api.openai.com", model="gpt-4")
        adapter.set_user_template("You are helpful.")
        assert adapter.user_template == "You are helpful."


class TestClaudeAdapter:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://api.anthropic.com", "https://api.anthropic.com"),
            ("https://api.anthropic.com/v1", "https://api.anthropic.com"),
            ("https://api.anthropic.com/v1/", "https://api.anthropic.com"),
            ("https://proxy.example.com/anthropic/v1", "https://proxy.example.com/anthropic"),
            ("https://proxy.example.com/anthropic/v1/messages", "https://proxy.example.com/anthropic"),
        ],
    )
    def test_normalize_claude_base_url_for_sdk(self, raw, expected):
        assert normalize_claude_base_url_for_sdk(raw) == expected

    def test_init_strips_version_suffix_before_constructing_anthropic_client(self, monkeypatch):
        fake_anthropic = ModuleType("anthropic")

        class _Anthropic:
            def __init__(self, api_key=None, base_url=None):
                self.api_key = api_key
                self.base_url = base_url

        fake_anthropic.Anthropic = _Anthropic
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)

        adapter = ClaudeAdapter(
            api_key="sk-ant",
            base_url="https://api.anthropic.com/v1",
            model="claude-3-5-sonnet-20240620",
        )

        assert adapter.client.api_key == "sk-ant"
        assert adapter.client.base_url == "https://api.anthropic.com"


class TestMockLLMAdapter:
    def test_returns_configured_response(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["Hello, world!"]
        result = mock_llm_adapter.chat(messages=[{"role": "user", "content": "Hi"}], stream=False)
        assert result.choices[0].message.content == "Hello, world!"

    def test_records_call_history(self, mock_llm_adapter):
        messages = [{"role": "user", "content": "Hi"}]
        mock_llm_adapter.chat(messages=messages, stream=False, temperature=0.5)
        assert len(mock_llm_adapter.call_history) == 1
        assert mock_llm_adapter.call_history[0]["kwargs"]["temperature"] == 0.5

    def test_streaming_yields_chunks(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["AB"]
        gen = mock_llm_adapter.chat(messages=[], stream=True)
        chunks = list(gen)
        assert len(chunks) > 0

    def test_multiple_responses_cycle(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["First", "Second"]
        r1 = mock_llm_adapter.chat(messages=[], stream=False)
        r2 = mock_llm_adapter.chat(messages=[], stream=False)
        assert r1.choices[0].message.content == "First"
        assert r2.choices[0].message.content == "Second"

    def test_reset_clears_history(self, mock_llm_adapter):
        mock_llm_adapter.chat(messages=[], stream=False)
        mock_llm_adapter.reset()
        assert len(mock_llm_adapter.call_history) == 0
