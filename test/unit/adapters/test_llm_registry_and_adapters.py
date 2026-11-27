"""Unit tests for the split LLM adapters and LLM AdapterRegistry."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from ai.llm.adapter_factory import LLMAdapterFactory
from ai.llm.adapters import ClaudeAdapter, DeepSeekAdapter, OpenAIAdapter
from ai.llm.registry import (
    configure_registered_llm_adapters,
    create_llm_adapter,
    create_llm_adapter_registry,
    get_llm_adapter_registry,
)
from sdk.adapters.llm import LLMAdapter


def _install_fake_openai(monkeypatch) -> list[dict]:
    created_clients: list[dict] = []
    fake_openai = ModuleType("openai")

    class _FakeOpenAI:
        def __init__(self, api_key=None, base_url=None) -> None:
            self.api_key = api_key
            self.base_url = base_url
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kw: kw)
            )
            created_clients.append({"api_key": api_key, "base_url": base_url})

    fake_openai.OpenAI = _FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    return created_clients


def _install_fake_anthropic(monkeypatch) -> None:
    fake_anthropic = ModuleType("anthropic")

    class _FakeAnthropic:
        def __init__(self, api_key=None, base_url=None) -> None:
            self.api_key = api_key
            self.base_url = base_url
            self.messages = SimpleNamespace(
                create=lambda **kw: SimpleNamespace(content=[]),
                stream=lambda **kw: SimpleNamespace(close=lambda: None),
            )

    fake_anthropic.Anthropic = _FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)


def test_isolated_llm_registry_can_register_and_create_without_touching_global() -> None:
    class _CustomLLM(LLMAdapter):
        def __init__(self, api_key: str = "", llm_provider: str = "") -> None:
            super().__init__(llm_provider=llm_provider)
            self.api_key = api_key

        def chat(self, messages: list, stream: bool = False, **kwargs):
            return {"messages": messages, "stream": stream}

    isolated = create_llm_adapter_registry(include_builtins=False)
    assert isolated.keys() == ()

    isolated.register("MyLLM", _CustomLLM, label="My LLM")
    adapter = create_llm_adapter(
        "MyLLM",
        registry=isolated,
        api_key="sk-local",
        ignored_extra="drop",
    )
    assert isinstance(adapter, _CustomLLM)
    assert adapter.provider == "MyLLM"
    assert adapter.api_key == "sk-local"
    assert "MyLLM" not in get_llm_adapter_registry()


def test_builtin_llm_registry_binds_gemini_capabilities_and_preserves_provider_keys(
    monkeypatch,
) -> None:
    _install_fake_openai(monkeypatch)
    registry = create_llm_adapter_registry(include_builtins=True)

    assert registry.keys() == (
        "Deepseek",
        "ChatGPT",
        "Gemini",
        "Claude",
        "豆包",
        "通义千问",
        "Ollama",
    )

    gemini = create_llm_adapter(
        "Gemini",
        registry=registry,
        api_key="sk-gem",
        model="gemini-2.5-flash",
    )
    assert isinstance(gemini, OpenAIAdapter)
    assert gemini.supports_streaming_tools is False

    seen: list[dict] = []
    gemini.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: seen.append(kw) or kw)
        )
    )
    gemini.chat(
        [{"role": "user", "content": "hi"}],
        temperature=0.5,
        presence_penalty=0.9,
        frequency_penalty=0.8,
        max_tokens=256,
    )
    assert seen[0]["max_completion_tokens"] == 256
    assert "max_tokens" not in seen[0]
    assert "presence_penalty" not in seen[0]
    assert "frequency_penalty" not in seen[0]


def test_openai_deepseek_and_claude_cancel_closes_active_stream(monkeypatch) -> None:
    _install_fake_openai(monkeypatch)
    _install_fake_anthropic(monkeypatch)

    closed: list[str] = []

    class _FakeStream:
        def __init__(self, tag: str) -> None:
            self._tag = tag

        def close(self) -> None:
            closed.append(self._tag)

    openai_adapter = OpenAIAdapter(api_key="sk-oai", model="gpt-4o")
    openai_adapter._current_stream = _FakeStream("openai")
    openai_adapter.cancel()

    deepseek_adapter = DeepSeekAdapter(
        api_key="sk-ds", base_url="https://api.deepseek.com", thinking_enabled=True
    )
    deepseek_adapter._current_stream = _FakeStream("deepseek")
    deepseek_adapter.cancel()
    assert deepseek_adapter.assistant_message_metadata("step") == {
        "reasoning_content": "step"
    }

    claude_adapter = ClaudeAdapter(
        api_key="sk-ant", base_url="https://api.anthropic.com/v1"
    )
    claude_adapter._current_stream = _FakeStream("claude")
    claude_adapter.cancel()

    assert closed == ["openai", "deepseek", "claude"]
    assert openai_adapter._current_stream is None
    assert deepseek_adapter._current_stream is None
    assert claude_adapter._current_stream is None


def test_configure_registered_llm_adapters_and_legacy_factory_delegation(
    monkeypatch,
) -> None:
    _install_fake_openai(monkeypatch)

    class _PluginLLM(LLMAdapter):
        def chat(self, messages: list, stream: bool = False, **kwargs):
            return "plugin-ok"

    try:
        configure_registered_llm_adapters({"PluginLLM": _PluginLLM})
        assert "PluginLLM" in LLMAdapterFactory._adapters
        created = LLMAdapterFactory.create_adapter("PluginLLM")
        assert isinstance(created, _PluginLLM)
        assert created.provider == "PluginLLM"
    finally:
        configure_registered_llm_adapters({})

    assert "PluginLLM" not in LLMAdapterFactory._adapters
    with pytest.raises(ValueError, match="Unsupported LLM adapter"):
        LLMAdapterFactory.create_adapter("PluginLLM")
