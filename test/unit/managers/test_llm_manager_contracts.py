"""Dependency isolation and substitutability guarantees for the conversation facade."""

import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai.llm.llm_adapter import OpenAIAdapter
from ai.llm.llm_manager import LLMAdapterFactory, LLMManager
from ai.llm.compact_manager import CompactManager
from sdk.hooks import PluginHookDispatcher
from sdk.llm_response import ChatResponse, ResponseDelta
from test.unit.managers.test_llm_manager_regression import (
    ClaudeStream, ScriptedAdapter, ScriptedClaudeAdapter, chunk, response,
)


class Catalog:
    def get_definitions(self, groups=None):
        return [{"type": "function", "function": {"name": "probe", "parameters": {"type": "object"}}}]

    def get_tool_group(self, name):
        return "default"

    def get_groups(self):
        return ["default"]


class Runner:
    def __init__(self):
        self.calls = []

    def is_in_cooldown(self, group):
        return False

    def cooldown_message_for_tool(self, name):
        return None

    def execute(self, name, arguments_json, *, risk_confirm=None):
        self.calls.append((name, arguments_json))
        return '{"ok":true}'


class Compactor:
    compact_threshold = 0.4
    hook_dispatcher = None

    def count_tokens(self, messages):
        return len(messages)

    def count_text_tokens(self, text):
        return len(text)

    def auto_compact_if_needed(self, messages):
        return messages

    def trim_messages_to_budget(self, messages, **kwargs):
        return messages

    def set_token_count(self, count):
        pass


class Journal:
    def __init__(self):
        self.messages = []

    def append(self, message):
        self.messages.append(copy.deepcopy(message))


def manager_for(adapter, **kwargs):
    host = SimpleNamespace(
        notify_tool_call=Mock(), confirm_risky_tool=Mock(return_value=True),
        post_context_token_estimate=Mock(),
    )
    defaults = dict(tools=Catalog(), executor=Runner(), host=host, journal=Journal(), compactor=Compactor())
    defaults.update(kwargs)
    return LLMManager(adapter, **defaults)


@pytest.mark.parametrize("stream", [False, True])
def test_explicit_dependencies_do_not_consult_process_global_tools_host_or_config(stream, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("global dependency used")
    monkeypatch.setattr("ai.llm.llm_manager.tool_manager.get_definitions", forbidden)
    monkeypatch.setattr("ai.llm.llm_manager.tool_executor.execute", forbidden)
    monkeypatch.setattr("ai.llm.llm_manager.get_llm_host_runtime", forbidden)
    monkeypatch.setattr("config.config_manager.ConfigManager", forbidden)
    first = ChatResponse(tool_calls=[{"id": "c", "type": "function", "function": {"name": "probe", "arguments": "{}"}}])
    replies = (iter([ResponseDelta(tool_calls=first.tool_calls)]), iter([ResponseDelta(content="done")])) if stream else (first, ChatResponse(content="done"))
    manager = manager_for(ScriptedAdapter(*replies))
    result = manager.chat("hello", stream=stream, include_local_time=False)
    assert (list(result) if stream else result) == (["done"] if stream else "done")
    assert manager.tool_executor.calls == [("probe", "{}")]


def test_two_managers_keep_tool_policy_and_persistence_independent():
    one = manager_for(ScriptedAdapter(ChatResponse(content="one")))
    two = manager_for(ScriptedAdapter(ChatResponse(content="two")))
    one._activate_tool_group("memory")
    assert two._active_tool_groups == ["default"]
    one.chat("first", stream=False, include_local_time=False)
    two.chat("second", stream=False, include_local_time=False)
    assert one.messages[-1]["content"] == "one"
    assert two.messages[-1]["content"] == "two"
    assert one._history.journal.messages != two._history.journal.messages
    assert one.tool_executor is not two.tool_executor


@pytest.mark.parametrize("stream", [False, True])
def test_custom_provider_codec_works_without_registering_adapter_type(stream):
    class CustomCodec:
        def decode(self, value):
            return ChatResponse(content=value["answer"])
        def iter_stream(self, value, *, cancelled):
            return iter([ResponseDelta(content=part) for part in value["parts"]])
    class CustomAdapter(ScriptedAdapter):
        @property
        def response_codec(self):
            return CustomCodec()
    adapter = CustomAdapter({"parts": ["custom ", "answer"]} if stream else {"answer": "custom answer"})
    manager = manager_for(adapter)
    result = manager.chat("hello", stream=stream, include_local_time=False)
    assert (list(result) if stream else result) == (["custom ", "answer"] if stream else "custom answer")
    assert manager.messages[-1]["content"] == "custom answer"


def test_tool_loop_handles_more_rounds_than_python_recursion_limit():
    class ManyRoundsAdapter(ScriptedAdapter):
        def __init__(self):
            super().__init__()
            self.rounds = 0
        def chat(self, messages, stream=False, **kwargs):
            self.rounds += 1
            if self.rounds > 1050:
                return ChatResponse(content="finished")
            return ChatResponse(tool_calls=[{
                "id": f"call_{self.rounds}", "type": "function",
                "function": {"name": "probe", "arguments": "{}"},
            }])
    adapter = ManyRoundsAdapter()
    manager = manager_for(adapter, first_turn_tool_call_limit=1100)
    assert manager.chat("hello", stream=False, include_local_time=False) == "finished"
    assert len(manager.tool_executor.calls) == 1050
    assert manager._chat_depth == 0


def test_late_hook_installation_is_visible_to_request_and_compaction():
    adapter = ScriptedAdapter(ChatResponse(content="done"))
    manager = manager_for(adapter)
    dispatcher = PluginHookDispatcher()
    dispatcher.register_before_chat(lambda context: context.messages.append({"role": "system", "content": "late rules"}))
    manager.hook_dispatcher = dispatcher
    manager.chat("hello", stream=False, include_local_time=False)
    assert adapter.requests[0]["messages"][-1]["content"] == "late rules"
    assert manager.compact_manager.hook_dispatcher is dispatcher
    assert not any(message["content"] == "late rules" for message in manager.messages)


@pytest.mark.parametrize("stream", [False, True])
def test_pre_request_hook_failure_releases_turn_scope(stream):
    manager = manager_for(ScriptedAdapter())
    manager.add_message = Mock(side_effect=RuntimeError("message sink failed"))
    with pytest.raises(RuntimeError, match="message sink failed"):
        manager.chat("hello", stream=stream, include_local_time=False)
    assert manager._chat_depth == 0 and manager._turn_state is None


@pytest.mark.parametrize("stream", [False, True])
def test_switch_adapter_updates_response_codec_and_request_owner(stream):
    manager = manager_for(ScriptedAdapter())
    new = ScriptedClaudeAdapter(
        ClaudeStream(SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="new")))
        if stream else SimpleNamespace(content=[SimpleNamespace(type="text", text="new")]),
    )
    manager.set_adapter(new)
    result = manager.chat("hello", stream=stream, include_local_time=False)
    assert (list(result) if stream else result) == (["new"] if stream else "new")
    assert len(new.requests) == 1


def test_injected_tool_catalog_requires_matching_execution_dependency():
    with pytest.raises(ValueError, match="matching executor"):
        LLMManager(ScriptedAdapter(), tools=Catalog())


def test_closing_stream_before_first_consumption_releases_scope_without_request():
    adapter = ScriptedAdapter()
    manager = manager_for(adapter)
    stream = manager.chat("hello", include_local_time=False, tool_groups=["memory"])
    stream.close()
    assert not adapter.requests
    assert manager._chat_depth == 0 and manager._turn_state is None
    assert manager._active_tool_groups == ["default"]


def test_gemini_factory_binds_provider_capability_to_actual_adapter():
    adapter = LLMAdapterFactory.create_adapter("Gemini", api_key="sk-test", model="test")
    assert adapter.provider == "Gemini"
    assert adapter.supports_streaming_tools is False


def test_subclass_inherits_and_can_extend_parameter_policy(monkeypatch):
    class RenamedAdapter(OpenAIAdapter):
        supported_chat_params = OpenAIAdapter.supported_chat_params | {"top_p"}
    adapter = RenamedAdapter(api_key="sk-test", llm_provider="Gemini")
    create = Mock(return_value=response("done"))
    adapter.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr("config.config_manager.ConfigManager", Mock(side_effect=AssertionError("global config read")))
    adapter.chat([], tools=[{"type": "function"}], temperature=0.4, top_p=0.8, presence_penalty=1.0)
    sent = create.call_args.kwargs
    assert sent["tools"] and sent["temperature"] == 0.4 and sent["top_p"] == 0.8
    assert "presence_penalty" not in sent


def test_normalized_response_is_supported_by_dialog_repair():
    valid = '{"dialog":[{"character_name":"Alice","sprite":"0","speech":"hi"}]}'
    manager = manager_for(ScriptedAdapter(ChatResponse(content="invalid"), ChatResponse(content=valid)))
    assert manager.chat("hello", stream=False, include_local_time=False, dialog_output_required=True) == valid


@pytest.mark.parametrize("stream", [False, True])
def test_facade_message_override_observes_user_tool_and_final_messages(stream):
    calls = [{"id": "c", "type": "function", "function": {"name": "probe", "arguments": "{}"}}]
    replies = (iter([ResponseDelta(tool_calls=calls)]), iter([ResponseDelta(content="done")])) if stream else (ChatResponse(tool_calls=calls), ChatResponse(content="done"))
    manager = manager_for(ScriptedAdapter(*replies))
    manager.add_message = Mock(wraps=manager.add_message)
    result = manager.chat("hello", stream=stream, include_local_time=False)
    if stream:
        list(result)
    assert [call.args[0] for call in manager.add_message.call_args_list] == ["user", "assistant", "tool", "assistant"]


class OpaqueCodec:
    def decode(self, response):
        return ChatResponse(content=response["answer"])


class OpaqueAdapter(ScriptedAdapter):
    @property
    def response_codec(self):
        return OpaqueCodec()


def test_custom_codec_is_used_for_compaction():
    adapter = OpaqueAdapter({"answer": "custom summary"})
    compactor = CompactManager(adapter, max_tokens=1000, recent_message_limit=1)
    history = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
        {"role": "user", "content": "latest question"},
    ]
    result = compactor.compact_messages(history)
    assert "custom summary" in result[1]["content"]
    assert result[-1] == history[-1]


def test_custom_codec_is_used_for_dialog_repair():
    valid = '{"dialog":[{"character_name":"Alice","sprite":"0","speech":"hi"}]}'
    manager = manager_for(OpaqueAdapter({"answer": "invalid"}, {"answer": valid}))
    assert manager.chat("hello", stream=False, include_local_time=False, dialog_output_required=True) == valid
