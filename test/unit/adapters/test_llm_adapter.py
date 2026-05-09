"""Unit tests for LLM adapters — parameter filtering, config schema, mocks."""

import pytest

from llm.llm_adapter import (
    DeepSeekAdapter,
    OpenAIAdapter,
    ClaudeAdapter,
    filter_supported_chat_params,
    SUPPORTED_CHAT_PARAMS,
)


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
