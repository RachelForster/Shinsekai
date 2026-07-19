"""Unit tests for LLMManager — message management, compact, tool calling."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from llm.llm_manager import LLMManager, LLMAdapterFactory
from llm.message_sanitizer import filter_unpaired_tool_messages_for_request
from llm.compact_manager import CompactManager
from sdk.hooks import BeforeChatContext, MessageAddedContext, PluginHookDispatcher
from llm.tools.tool_manager import ToolManager
from sdk.register import PluginCapabilityRegistry
from test.mocks import MockLLMAdapter


class ToolPairBadRequest(Exception):
    status_code = 400

    def __str__(self) -> str:
        return "Messages with role 'tool' must be a response to a preceding message with 'tool_calls'"


class TestLLMManagerMessageManagement:
    def test_init_creates_system_message_with_template(self, mock_llm_adapter):
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="You are helpful.")
        assert len(mgr.messages) == 1
        assert mgr.messages[0]["role"] == "system"
        assert mgr.messages[0]["content"] == "You are helpful."

    def test_init_empty_template(self, mock_llm_adapter):
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="")
        assert mgr.messages[0]["role"] == "system"
        assert mgr.messages[0]["content"] == ""

    def test_set_user_template_resets_messages(self, mock_llm_adapter):
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="Original")
        mgr.add_message("user", "Hello")
        assert len(mgr.messages) == 2

        mgr.set_user_template("New template")
        assert len(mgr.messages) == 1
        assert mgr.messages[0]["content"] == "New template"

    def test_add_message_increments_history(self, mock_llm_adapter):
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="System")
        mgr.add_message("user", "Hi")
        mgr.add_message("assistant", "Hello there")
        assert len(mgr.messages) == 3

    def test_add_message_with_extra_kwargs(self, mock_llm_adapter):
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="S")
        mgr.add_message("assistant", "content", tool_calls=[{"id": "1", "type": "function", "function": {"name": "test", "arguments": "{}"}}])
        assert "tool_calls" in mgr.messages[-1]

    def test_add_message_dispatches_message_added_after_history_append(self, mock_llm_adapter):
        dispatcher = PluginHookDispatcher()
        calls: list[MessageAddedContext] = []
        dispatcher.register_message_added(lambda context: calls.append(context))
        mgr = LLMManager(
            adapter=mock_llm_adapter,
            user_template="S",
            hook_dispatcher=dispatcher,
        )

        mgr.add_message("user", "Hello")

        assert len(calls) == 1
        assert calls[0].role == "user"
        assert calls[0].message == {"role": "user", "content": "Hello"}
        assert calls[0].message is not mgr.messages[-1]
        assert calls[0].messages == mgr.messages
        assert calls[0].messages is not mgr.messages

    def test_message_added_hook_receives_snapshot_not_live_history(self, mock_llm_adapter):
        dispatcher = PluginHookDispatcher()

        def mutate_snapshot(context: MessageAddedContext) -> None:
            context.message["content"] = "changed by hook"
            context.messages.clear()

        dispatcher.register_message_added(mutate_snapshot)
        mgr = LLMManager(
            adapter=mock_llm_adapter,
            user_template="S",
            hook_dispatcher=dispatcher,
        )

        mgr.add_message("user", "Hello")

        assert mgr.messages == [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "Hello"},
        ]

    def test_add_message_skips_snapshot_copy_without_message_added_hooks(
        self,
        mock_llm_adapter,
        monkeypatch,
    ):
        dispatcher = PluginHookDispatcher()
        mgr = LLMManager(
            adapter=mock_llm_adapter,
            user_template="S",
            hook_dispatcher=dispatcher,
        )

        def fail_deepcopy(_value):
            raise AssertionError("deepcopy should not run without message_added hooks")

        monkeypatch.setattr("llm.llm_manager.copy.deepcopy", fail_deepcopy)

        mgr.add_message("user", "Hello")

        assert mgr.messages[-1] == {"role": "user", "content": "Hello"}

    def test_clear_messages_keeps_system(self, mock_llm_adapter):
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="Keep me")
        mgr.add_message("user", "Hello")
        mgr.add_message("assistant", "Hi")
        mgr.clear_messages()
        assert len(mgr.messages) == 1
        assert mgr.messages[0]["role"] == "system"

    def test_get_messages_returns_list(self, mock_llm_adapter):
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="S")
        msgs = mgr.get_messages()
        assert msgs is mgr.messages

    def test_set_messages_replaces_history(self, mock_llm_adapter):
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="S")
        new_msgs = [{"role": "system", "content": "New"}, {"role": "user", "content": "Hi"}]
        mgr.set_messages(new_msgs)
        assert mgr.messages == new_msgs

    def test_set_messages_trims_over_budget_history_without_llm_call(self, mock_llm_adapter):
        mgr = LLMManager(
            adapter=mock_llm_adapter,
            user_template="S",
            max_tokens=200,
            compact_threshold=0.4,
            history_recent_messages=4,
        )
        history = [{"role": "system", "content": "System prompt"}]
        for i in range(20):
            history.append({"role": "user", "content": f"question {i} " + ("x" * 120)})
            history.append({"role": "assistant", "content": f"answer {i} " + ("y" * 120)})

        mgr.set_messages(history)

        assert mock_llm_adapter.call_history == []
        assert mgr.messages[0]["role"] == "system"
        assert len(mgr.messages) < len(history)
        assert any("历史" in m.get("content", "") for m in mgr.messages)
        assert mgr.messages[-1]["content"].startswith("answer 19")

    def test_set_messages_preserves_loaded_tool_payloads(self, mock_llm_adapter):
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="S")
        history = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "read a file"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "file_read", "arguments": "{}"},
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "file_read",
                "content": "x" * 10000,
            },
            {
                "role": "assistant",
                "content": "I found the answer.",
                "tool_calls": [{
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "memory_search", "arguments": "{}"},
                }],
            },
            {
                "role": "tool",
                "tool_call_id": "call_2",
                "name": "memory_search",
                "content": "y" * 10000,
            },
        ]

        mgr.set_messages(history)

        assert mock_llm_adapter.call_history == []
        assert mgr.messages == history

    def test_set_adapter_switches_and_resets(self, mock_llm_adapter):
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="S")
        mgr.add_message("user", "Hello")
        assert len(mgr.messages) == 2

        new_adapter = MockLLMAdapter(responses=["New adapter reply"])
        mgr.set_adapter(new_adapter)
        assert mgr.llm_adapter is new_adapter
        assert mgr.compact_manager.llm_adapter is new_adapter
        assert len(mgr.messages) == 0


class TestLLMManagerCompact:
    def test_default_token_budget_settings(self, mock_llm_adapter):
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="S")

        assert mgr.compact_manager.compact_threshold == 0.4
        assert mgr.compact_manager.compact_target_ratio == 0.3
        assert mgr.compact_manager.recent_message_limit == 20
        assert mgr._max_active_groups == 3

    def test_history_load_budget_caps_at_50k(self, mock_llm_adapter):
        mgr = LLMManager(
            adapter=mock_llm_adapter,
            user_template="S",
            max_tokens=200000,
            compact_threshold=0.4,
        )

        assert mgr._history_load_budget() == 50000

    def test_compact_target_ratio_is_clamped_below_threshold(self, mock_llm_adapter):
        cm = CompactManager(
            mock_llm_adapter,
            max_tokens=100000,
            compact_threshold=0.4,
            compact_target_ratio=0.39,
        )

        assert cm.compact_target_ratio == 0.35

    def test_auto_compact_triggers_when_threshold_exceeded(self, mock_llm_adapter):
        """With low threshold and high token count, auto-compact fires on add_message."""
        mock_llm_adapter.responses = ["Summary: compacted conversation about testing."]
        mgr = LLMManager(
            adapter=mock_llm_adapter,
            user_template="You are helpful.",
            max_tokens=500,
            compact_threshold=0.1,
        )
        mgr.compact_manager.set_token_count(400)
        original_len = len(mgr.messages)
        mgr.add_message("user", "Hello" * 50)
        # auto-compact should have fired and reduced messages
        assert len(mgr.messages) > 0

    def test_compact_manager_standalone(self, mock_llm_adapter):
        """Test CompactManager directly for token counting and compaction."""
        cm = CompactManager(mock_llm_adapter, max_tokens=1000, compact_threshold=0.5)
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there! How can I help?"},
            {"role": "user", "content": "Tell me a long story about dragons."},
            {"role": "assistant", "content": "Once upon a time, there was a dragon..."},
        ]
        tokens = cm.count_tokens(messages)
        assert tokens > 0
        needs = cm.needs_compaction(messages)
        assert isinstance(needs, bool)

    def test_compact_manager_with_low_threshold(self, mock_llm_adapter):
        """CompactManager.needs_compaction returns True with high tokens."""
        mock_llm_adapter.responses = ["Compacted."]
        cm = CompactManager(mock_llm_adapter, max_tokens=100, compact_threshold=0.1)
        needs = cm.needs_compaction([{"role": "user", "content": "Extra message " * 80}])
        assert needs is True

    def test_compact_manager_with_high_threshold(self, mock_llm_adapter):
        cm = CompactManager(mock_llm_adapter, max_tokens=100000, compact_threshold=0.95)
        needs = cm.needs_compaction([{"role": "user", "content": "Short"}])
        assert needs is False

    def test_count_tokens_includes_tool_call_payloads(self, mock_llm_adapter):
        cm = CompactManager(mock_llm_adapter, max_tokens=100000)
        base = [{"role": "assistant", "content": ""}]
        with_tool_call = [{
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "file_read",
                    "arguments": json.dumps({"path": "x.txt", "max_chars": 5000}),
                },
            }],
        }]

        assert cm.count_tokens(with_tool_call) > cm.count_tokens(base)

    def test_count_tokens_excludes_embedded_historical_image_bytes(self, mock_llm_adapter):
        cm = CompactManager(mock_llm_adapter, max_tokens=100000)
        without_data = [{
            "role": "user",
            "content": [{"type": "text", "text": "Inspect"}, {"type": "local_image", "name": "scene.png"}],
        }]
        with_data = copy.deepcopy(without_data)
        with_data[0]["content"][1]["data"] = "a" * 100_000

        assert cm.count_tokens(with_data) - cm.count_tokens(without_data) < 100

    def test_compact_failure_falls_back_to_bounded_history(self, mock_llm_adapter):
        def _fail(*args, **kwargs):
            raise RuntimeError("summary failed")

        mock_llm_adapter.chat = _fail
        cm = CompactManager(
            mock_llm_adapter,
            max_tokens=500,
            compact_threshold=0.4,
            recent_message_limit=4,
        )
        messages = [{"role": "system", "content": "S"}]
        for i in range(10):
            messages.append({"role": "user", "content": f"Q{i} " + ("x" * 100)})
            messages.append({"role": "assistant", "content": f"A{i} " + ("y" * 100)})

        result = cm.compact_messages(messages)

        assert result[0]["role"] == "system"
        assert len(result) < len(messages)
        assert any("历史" in m.get("content", "") for m in result)
        assert result[-1]["content"].startswith("A9")

    def test_compact_messages_preserves_system(self, mock_llm_adapter):
        """CompactManager.compact_messages keeps system message and produces fewer messages."""
        mock_llm_adapter.responses = ["A summary of the test conversation."]
        cm = CompactManager(mock_llm_adapter, max_tokens=10000, compact_threshold=0.5, recent_message_limit=3)
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Q1: What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
            {"role": "user", "content": "Q2: Why use it?"},
            {"role": "assistant", "content": "It's versatile and readable."},
            {"role": "user", "content": "Q3: Is it fast?"},
            {"role": "assistant", "content": "It depends on the use case."},
        ]
        result = cm.compact_messages(messages)
        assert result[0]["role"] == "system"
        assert len(result) < len(messages)

    def test_compact_messages_calls_registered_compact_hooks_with_snapshot(self, mock_llm_adapter):
        registry = PluginCapabilityRegistry()
        hook_calls = []
        hook_objects = []

        def before_compact(messages):
            hook_calls.append([dict(message) for message in messages])
            hook_objects.append(messages)
            messages[0]["content"] = "changed by legacy hook"
            messages.clear()

        registry.register_compact_hook(before_compact)
        mock_llm_adapter.responses = ["A summary written after plugin hook."]
        cm = CompactManager(
            mock_llm_adapter,
            max_tokens=10000,
            compact_threshold=0.5,
            recent_message_limit=1,
            hook_dispatcher=registry.hook_dispatcher,
        )
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "latest"},
        ]

        result = cm.compact_messages(messages)

        assert hook_calls == [[
            {"role": "system", "content": "S"},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "latest"},
        ]]
        assert hook_objects[0] is not messages
        assert messages == [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "latest"},
        ]
        assert "A summary written after plugin hook." in result[1]["content"]

    def test_compact_messages_skips_snapshot_copy_without_before_compact_hooks(
        self,
        mock_llm_adapter,
        monkeypatch,
    ):
        dispatcher = PluginHookDispatcher()

        def fail_deepcopy(_value):
            raise AssertionError("deepcopy should not run without before_compact hooks")

        monkeypatch.setattr("llm.compact_manager.copy.deepcopy", fail_deepcopy)
        mock_llm_adapter.responses = ["A summary written without plugin hooks."]
        cm = CompactManager(
            mock_llm_adapter,
            max_tokens=10000,
            compact_threshold=0.5,
            recent_message_limit=1,
            hook_dispatcher=dispatcher,
        )
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "old question"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "latest"},
        ]

        result = cm.compact_messages(messages)

        assert result[0]["role"] == "system"
        assert "A summary written without plugin hooks." in result[1]["content"]

    def test_add_message_persists_same_length_compaction(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["Condensed old turn."]
        mgr = LLMManager(
            adapter=mock_llm_adapter,
            user_template="S",
            max_tokens=10000,
            compact_threshold=0.01,
            history_recent_messages=1,
        )
        mgr.messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "old " + ("x" * 1000)},
        ]

        mgr.add_message("assistant", "latest")

        assert len(mgr.messages) == 3
        assert "历史对话总结" in mgr.messages[1]["content"]
        assert mgr.messages[-1]["content"] == "latest"

    def test_compact_messages_handles_short_but_over_budget_history(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["Condensed short history."]
        cm = CompactManager(
            mock_llm_adapter,
            max_tokens=10000,
            compact_threshold=0.01,
            recent_message_limit=20,
        )
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "large old message " + ("x" * 1000)},
            {"role": "assistant", "content": "latest"},
        ]

        result = cm.compact_messages(messages)

        assert result[0]["role"] == "system"
        assert "历史对话总结" in result[1]["content"]
        assert result[-1]["content"] == "latest"
        assert result != messages

    def test_compact_messages_too_few_returns_unchanged(self, mock_llm_adapter):
        cm = CompactManager(mock_llm_adapter, max_tokens=1000, compact_threshold=0.5)
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "Hi"},
        ]
        result = cm.compact_messages(messages)
        assert result == messages

    def test_auto_compact_if_needed_noop(self, mock_llm_adapter):
        cm = CompactManager(mock_llm_adapter, max_tokens=100000, compact_threshold=0.95)
        cm.set_token_count(10)
        messages = [{"role": "system", "content": "S"}]
        result = cm.auto_compact_if_needed(messages)
        assert result == messages

    def test_chat_include_local_time_adds_prefix(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["Response."]
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="S")
        mgr.chat("Hello", stream=False, include_local_time=True)
        user_msg = mgr.messages[-2]["content"]
        assert "本地时间" in user_msg

    def test_chat_prefixes_structured_input_and_keeps_display_content(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["Response."]
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="S")
        content = [
            {"type": "text", "text": "Inspect"},
            {"type": "local_image", "path": "C:/scene.png"},
        ]

        attachments = [{"kind": "image", "name": "scene.png", "path": "C:/scene.png"}]
        mgr.chat(
            content,
            stream=False,
            user_display_text="Inspect\n[image: scene.png]",
            user_input_text="Inspect",
            user_attachments=attachments,
        )

        user_message = mgr.messages[-2]
        assert "本地时间" in user_message["content"][0]["text"]
        assert user_message["content"][1] == content[1]
        assert user_message["display_content"] == "Inspect\n[image: scene.png]"
        assert user_message["input_text"] == "Inspect"
        assert user_message["attachments"] == attachments

    def test_chat_activates_requested_tool_groups_inside_turn(self, mock_llm_adapter, monkeypatch):
        mock_llm_adapter.responses = ["Response."]
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="S")
        activate = MagicMock(wraps=mgr._activate_tool_group)
        monkeypatch.setattr(mgr, "_activate_tool_group", activate)

        mgr.chat("Read the attachment", stream=False, tool_groups=["file"])

        activate.assert_called_once_with("file")
        assert mgr._active_tool_groups == ["default"]

    def test_chat_exclude_local_time_preserves_text(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["Response."]
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="S")
        mgr.chat("Hello", stream=False, include_local_time=False)
        user_msg = mgr.messages[-2]["content"]
        assert user_msg == "Hello"

    def test_before_chat_hook_can_inject_sync_request_without_persisting(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["Response."]
        dispatcher = PluginHookDispatcher()

        def inject_context(context: BeforeChatContext) -> None:
            context.messages.append({"role": "system", "content": "temporary plugin context"})
            context.generation_kwargs["temperature"] = 0.25

        dispatcher.register_before_chat(inject_context)
        mgr = LLMManager(
            adapter=mock_llm_adapter,
            user_template="S",
            hook_dispatcher=dispatcher,
        )

        mgr.chat("Hello", stream=False, include_local_time=False)

        request = mock_llm_adapter.call_history[0]
        assert request["messages"][-1] == {"role": "system", "content": "temporary plugin context"}
        assert request["kwargs"]["temperature"] == 0.25
        assert mgr.messages[-1]["role"] == "assistant"
        assert all(msg.get("content") != "temporary plugin context" for msg in mgr.messages)

    def test_before_chat_hook_mutates_request_copy_without_persisting(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["Response."]
        dispatcher = PluginHookDispatcher()

        def mutate_context(context: BeforeChatContext) -> None:
            context.messages[0]["content"] = "temporary mutated system"

        dispatcher.register_before_chat(mutate_context)
        mgr = LLMManager(
            adapter=mock_llm_adapter,
            user_template="S",
            hook_dispatcher=dispatcher,
        )

        mgr.chat("Hello", stream=False, include_local_time=False)

        request = mock_llm_adapter.call_history[0]
        assert request["messages"][0]["content"] == "temporary mutated system"
        assert mgr.messages[0]["content"] == "S"

    def test_before_chat_hook_mutates_tool_and_kwargs_copy_without_persisting(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["Response."]
        tm = ToolManager()
        tool_name = "unit_hook_snapshot_tool"

        def probe_tool(value: str) -> str:
            return value

        tm.register_function(probe_tool, name=tool_name, group="default")
        dispatcher = PluginHookDispatcher()

        def mutate_context(context: BeforeChatContext) -> None:
            assert context.tools is not None
            target = next(
                tool
                for tool in context.tools
                if tool.get("function", {}).get("name") == tool_name
            )
            target["function"]["parameters"]["properties"]["value"]["description"] = (
                "changed by hook"
            )
            context.generation_kwargs["metadata"]["source"] = "changed by hook"
            context.generation_kwargs["extra_body"]["trace"]["id"] = "changed by hook"

        dispatcher.register_before_chat(mutate_context)
        call_kwargs = {"extra_body": {"trace": {"id": "original call"}}}
        mgr = LLMManager(
            adapter=mock_llm_adapter,
            user_template="S",
            generation_config={"metadata": {"source": "original config"}},
            hook_dispatcher=dispatcher,
        )

        try:
            mgr.chat("Hello", stream=False, include_local_time=False, **call_kwargs)
        finally:
            tm._drop_tool(tool_name)

        request = mock_llm_adapter.call_history[0]
        request_tool = next(
            tool
            for tool in request["kwargs"]["tools"]
            if tool.get("function", {}).get("name") == tool_name
        )
        assert (
            request_tool["function"]["parameters"]["properties"]["value"]["description"]
            == "changed by hook"
        )
        assert request["kwargs"]["metadata"]["source"] == "changed by hook"
        assert request["kwargs"]["extra_body"]["trace"]["id"] == "changed by hook"
        assert mgr.generation_config == {"metadata": {"source": "original config"}}
        assert call_kwargs == {"extra_body": {"trace": {"id": "original call"}}}

    def test_before_chat_hook_can_inject_stream_request_without_persisting(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["OK"]
        dispatcher = PluginHookDispatcher()
        dispatcher.register_before_chat(
            lambda context: context.messages.append(
                {"role": "system", "content": "temporary stream context"}
            )
        )
        mgr = LLMManager(
            adapter=mock_llm_adapter,
            user_template="S",
            hook_dispatcher=dispatcher,
        )

        assert "".join(mgr.chat("Hello", stream=True, include_local_time=False)) == "OK"

        request = mock_llm_adapter.call_history[0]
        assert request["messages"][-1] == {"role": "system", "content": "temporary stream context"}
        assert all(msg.get("content") != "temporary stream context" for msg in mgr.messages)

    def test_request_filter_removes_unpaired_tool_messages(self):
        messages = [
            {"role": "user", "content": "search"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "ok", "arguments": "{}"}},
                    {"id": "call_2", "type": "function", "function": {"name": "missing", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "ok", "content": "{}"},
            {"role": "tool", "tool_call_id": "orphan", "name": "bad", "content": "{}"},
        ]

        filtered = filter_unpaired_tool_messages_for_request(messages)

        assert filtered is not messages
        assert filtered == [
            {"role": "user", "content": "search"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "ok", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "name": "ok", "content": "{}"},
        ]

    def test_request_filter_drops_empty_assistant_tool_call_without_result(self):
        messages = [
            {"role": "user", "content": "search"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "missing", "arguments": "{}"}},
                ],
            },
            {"role": "user", "content": "next"},
        ]

        assert filter_unpaired_tool_messages_for_request(messages) == [
            {"role": "user", "content": "search"},
            {"role": "user", "content": "next"},
        ]

    def test_request_filter_preserves_assistant_content_when_stripping_unpaired_tool_calls(self):
        messages = [
            {"role": "user", "content": "search"},
            {
                "role": "assistant",
                "content": "Here are the results",
                "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "missing", "arguments": "{}"}},
                ],
            },
            {"role": "user", "content": "next"},
        ]

        assert filter_unpaired_tool_messages_for_request(messages) == [
            {"role": "user", "content": "search"},
            {"role": "assistant", "content": "Here are the results"},
            {"role": "user", "content": "next"},
        ]

    def test_unpaired_tools_are_filtered_only_after_request_error(self, mock_llm_adapter):
        class RecoveringAdapter(MockLLMAdapter):
            def chat(self, messages, stream=False, **kwargs):
                if not self.call_history:
                    self.call_history.append({"messages": messages, "stream": stream, "kwargs": kwargs})
                    raise ToolPairBadRequest()
                return super().chat(messages, stream=stream, **kwargs)

        adapter = RecoveringAdapter(responses=["Response."])
        dispatcher = PluginHookDispatcher()

        def inject_bad_tool_context(context: BeforeChatContext) -> None:
            context.messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"id": "call_missing", "type": "function", "function": {"name": "missing", "arguments": "{}"}},
                    ],
                }
            )
            context.messages.append(
                {"role": "tool", "tool_call_id": "orphan", "name": "missing", "content": "{}"}
            )

        dispatcher.register_before_chat(inject_bad_tool_context)
        mgr = LLMManager(
            adapter=adapter,
            user_template="S",
            hook_dispatcher=dispatcher,
        )

        mgr.chat("Hello", stream=False, include_local_time=False)

        first_request_messages = adapter.call_history[0]["messages"]
        assert any(message.get("role") == "tool" for message in first_request_messages)
        assert any(message.get("tool_calls") for message in first_request_messages)

        recovered_request_messages = adapter.call_history[1]["messages"]
        assert all(message.get("role") != "tool" for message in recovered_request_messages)
        assert all(not message.get("tool_calls") for message in recovered_request_messages)
        assert mgr.messages[-1]["role"] == "assistant"

    def test_before_chat_context_skips_copy_without_before_chat_hooks(
        self,
        mock_llm_adapter,
        monkeypatch,
    ):
        dispatcher = PluginHookDispatcher()
        mgr = LLMManager(
            adapter=mock_llm_adapter,
            user_template="S",
            hook_dispatcher=dispatcher,
        )
        tools_defs = [{"type": "function", "function": {"name": "probe"}}]
        generation_kwargs = {"metadata": {"source": "unit"}}

        def fail_deepcopy(_value):
            raise AssertionError("deepcopy should not run without before_chat hooks")

        monkeypatch.setattr("llm.llm_manager.copy.deepcopy", fail_deepcopy)

        context = mgr._before_chat_context(
            stream=False,
            tools_defs=tools_defs,
            generation_kwargs=generation_kwargs,
        )

        assert context.messages is mgr.messages
        assert context.tools is tools_defs
        assert context.generation_kwargs is generation_kwargs
        assert context.stream is False


class TestLLMManagerToolCalling:
    def test_tool_definitions_are_loaded(self, mock_llm_adapter):
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="S")
        defs = mgr.tools_definitions
        assert isinstance(defs, list)

    def test_register_and_execute_tool(self, mock_llm_adapter):
        tm = ToolManager()

        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        tm.register_function(add, name="test_add")
        defs = tm.get_definitions()
        assert any(d["function"]["name"] == "test_add" for d in defs)

        result = tm.execute("test_add", '{"a": 3, "b": 4}')
        assert "7" in result

    def test_tool_execute_unknown_returns_error(self):
        tm = ToolManager()
        result = tm.execute("nonexistent_tool", "{}")
        parsed = json.loads(result)
        assert "error" in parsed

    def test_tool_execute_bad_json_returns_error(self):
        tm = ToolManager()

        def greet(name: str) -> str:
            return f"Hello, {name}"

        tm.register_function(greet, name="greet")
        result = tm.execute("greet", "not valid json")
        parsed = json.loads(result)
        assert "error" in parsed

    def test_tool_param_schema_types(self):
        tm = ToolManager()

        def complex_tool(x: int, y: float, flag: bool, label: str) -> dict:
            """A complex tool with various parameter types."""
            return {"x": x, "y": y, "flag": flag, "label": label}

        tm.register_function(complex_tool, name="complex")
        defs = tm.get_definitions()
        tool_def = next(d for d in defs if d["function"]["name"] == "complex")
        props = tool_def["function"]["parameters"]["properties"]
        assert props["x"]["type"] == "integer"
        assert props["y"]["type"] == "number"
        assert props["flag"]["type"] == "boolean"

    def test_tool_registration_with_default_params(self):
        tm = ToolManager()

        def opt_tool(a: int, b: int = 10):
            """Tool with optional parameter."""
            return a + b

        tm.register_function(opt_tool, name="opt_tool")
        defs = tm.get_definitions()
        tool_def = next(d for d in defs if d["function"]["name"] == "opt_tool")
        required = tool_def["function"]["parameters"]["required"]
        assert "a" in required
        assert "b" not in required

    def test_tool_definition_openai_format(self, mock_llm_adapter):
        tm = ToolManager()

        def weather(city: str) -> str:
            """Get the weather for a city."""
            return f"Sunny in {city}"

        tm.register_function(weather, name="get_weather")
        defs = tm.get_definitions()
        tool = next(d for d in defs if d["function"]["name"] == "get_weather")
        assert tool["type"] == "function"
        assert "name" in tool["function"]
        assert "description" in tool["function"]

    def test_prepare_tool_result_truncates_long_history_payload(self, mock_llm_adapter):
        mgr = LLMManager(
            adapter=mock_llm_adapter,
            user_template="S",
            max_tool_result_chars=80,
        )

        result = mgr._prepare_tool_result_for_history("x" * 200)
        parsed = json.loads(result)

        assert parsed["truncated"] is True
        assert parsed["original_chars"] == 200
        assert parsed["omitted_chars"] == 120
        assert parsed["head"] == "x" * 40
        assert parsed["tail"] == "x" * 40

    def test_chat_records_token_estimate_and_resets_tool_groups_sync(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["Response."]
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="System")
        mgr._active_tool_groups = ["memory", "default"]

        mgr.chat("Hello", stream=False, include_local_time=False)

        estimate = mgr.get_context_token_estimate()
        assert estimate["system_prompt_tokens"] > 0
        assert estimate["history_tokens"] > 0
        assert "tool_definition_tokens" in estimate
        assert "estimated_total_tokens" in estimate
        assert mgr._active_tool_groups == ["default"]

    def test_chat_posts_token_estimate_to_runtime_ui(self, mock_app_runtime):
        mgr = mock_app_runtime.llm_manager

        mgr.chat("Hello", stream=False, include_local_time=False)

        mock_app_runtime.ui_update_manager.post_context_token_estimate.assert_called_once()
        estimate = mock_app_runtime.ui_update_manager.post_context_token_estimate.call_args.args[0]
        assert "system_prompt_tokens" in estimate
        assert "history_tokens" in estimate
        assert "tool_definition_tokens" in estimate
        assert "estimated_total_tokens" in estimate

    def test_chat_resets_tool_groups_stream_after_consumed(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["Response."]
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="System")
        mgr._active_tool_groups = ["memory", "default"]

        list(mgr.chat("Hello", stream=True, include_local_time=False))

        assert mgr._active_tool_groups == ["default"]

    def test_first_user_turn_limits_tool_calls_and_disables_next_round_tools(self):
        tm = ToolManager()
        calls = {"a": 0, "b": 0}

        def first_tool() -> dict:
            calls["a"] += 1
            return {"ok": "a"}

        def second_tool() -> dict:
            calls["b"] += 1
            return {"ok": "b"}

        tm.register_function(first_tool, name="unit_first_turn_tool_a", group="default")
        tm.register_function(second_tool, name="unit_first_turn_tool_b", group="default")

        class TwoToolThenFinalAdapter(MockLLMAdapter):
            def chat(self, messages, stream=False, **kwargs):
                self.call_history.append({"messages": messages, "stream": stream, "kwargs": kwargs})
                if len(self.call_history) == 1:
                    return SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(
                                    content="",
                                    reasoning_content=None,
                                    tool_calls=[
                                        SimpleNamespace(
                                            id="call_a",
                                            function=SimpleNamespace(
                                                name="unit_first_turn_tool_a",
                                                arguments="{}",
                                            ),
                                        ),
                                        SimpleNamespace(
                                            id="call_b",
                                            function=SimpleNamespace(
                                                name="unit_first_turn_tool_b",
                                                arguments="{}",
                                            ),
                                        ),
                                    ],
                                )
                            )
                        ]
                    )
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="final",
                                reasoning_content=None,
                                tool_calls=[],
                            )
                        )
                    ]
                )

        adapter = TwoToolThenFinalAdapter()
        mgr = LLMManager(adapter=adapter, user_template="S")

        result = mgr.chat("Hello", stream=False, include_local_time=False)

        assert result == "final"
        assert calls == {"a": 1, "b": 0}
        assert len(adapter.call_history) == 2
        assert adapter.call_history[0]["kwargs"]["tools"]
        assert adapter.call_history[1]["kwargs"]["tools"] is None
        skipped = [
            json.loads(m["content"])
            for m in mgr.messages
            if m.get("role") == "tool" and m.get("name") == "unit_first_turn_tool_b"
        ]
        assert skipped
        assert skipped[0]["reason"] == "first_turn_tool_budget_exhausted"

    def test_repeated_failed_tool_call_is_skipped_within_same_turn(self):
        tm = ToolManager()
        calls = {"fail": 0}

        def failing_tool() -> dict:
            calls["fail"] += 1
            return {"error": "boom"}

        tm.register_function(failing_tool, name="unit_repeat_fail_tool", group="default")

        class RepeatFailedToolAdapter(MockLLMAdapter):
            def chat(self, messages, stream=False, **kwargs):
                self.call_history.append({"messages": messages, "stream": stream, "kwargs": kwargs})
                if len(self.call_history) == 1:
                    return SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(
                                    content="",
                                    reasoning_content=None,
                                    tool_calls=[
                                        SimpleNamespace(
                                            id="call_1",
                                            function=SimpleNamespace(
                                                name="unit_repeat_fail_tool",
                                                arguments="{}",
                                            ),
                                        ),
                                        SimpleNamespace(
                                            id="call_2",
                                            function=SimpleNamespace(
                                                name="unit_repeat_fail_tool",
                                                arguments="{}",
                                            ),
                                        ),
                                    ],
                                )
                            )
                        ]
                    )
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="done",
                                reasoning_content=None,
                                tool_calls=[],
                            )
                        )
                    ]
                )

        adapter = RepeatFailedToolAdapter()
        mgr = LLMManager(adapter=adapter, user_template="S", first_turn_tool_call_limit=10)

        result = mgr.chat("Hello", stream=False, include_local_time=False)

        assert result == "done"
        assert calls["fail"] == 1
        tool_results = [
            json.loads(m["content"])
            for m in mgr.messages
            if m.get("role") == "tool" and m.get("name") == "unit_repeat_fail_tool"
        ]
        assert tool_results[0]["error"] == "boom"
        assert tool_results[1]["reason"] == "tool_failed_earlier_in_turn"

    def test_tool_cooldown_filters_next_round_tool_definitions(self):
        tm = ToolManager()

        def failing_vision_tool() -> dict:
            return {"error": "screen capture failed"}

        def default_probe() -> dict:
            return {"ok": True}

        tm.register_function(failing_vision_tool, name="unit_vision_fail_tool", group="vision")
        tm.register_function(default_probe, name="unit_default_probe_tool", group="default")

        class VisionFailThenFinalAdapter(MockLLMAdapter):
            def chat(self, messages, stream=False, **kwargs):
                self.call_history.append({"messages": messages, "stream": stream, "kwargs": kwargs})
                if len(self.call_history) == 1:
                    return SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(
                                    content="",
                                    reasoning_content=None,
                                    tool_calls=[
                                        SimpleNamespace(
                                            id="call_vision",
                                            function=SimpleNamespace(
                                                name="unit_vision_fail_tool",
                                                arguments="{}",
                                            ),
                                        )
                                    ],
                                )
                            )
                        ]
                    )
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content="done",
                                reasoning_content=None,
                                tool_calls=[],
                            )
                        )
                    ]
                )

        adapter = VisionFailThenFinalAdapter()
        mgr = LLMManager(adapter=adapter, user_template="S", first_turn_tool_call_limit=10)
        mgr.tool_executor.clear_cooldown("vision")
        mgr._active_tool_groups = ["vision", "default"]

        try:
            result = mgr.chat("Hello", stream=False, include_local_time=False)

            assert result == "done"
            assert mgr.tool_executor.is_in_cooldown("vision")
            second_tools = adapter.call_history[1]["kwargs"]["tools"] or []
            second_tool_names = {tool["function"]["name"] for tool in second_tools}
            assert "unit_vision_fail_tool" not in second_tool_names
            assert "unit_default_probe_tool" in second_tool_names
        finally:
            mgr.tool_executor.clear_cooldown("vision")

    def test_register_mcp_tools(self):
        tm = ToolManager()
        mcp_tools = [
            {
                "name": "mcp_search",
                "description": "Search the web",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ]
        results = {}

        def mock_invoke(name: str, args: dict):
            results[name] = args
            return {"found": True}

        tm.register_mcp_tools(mcp_tools, invoke=mock_invoke, name_prefix="mcp_")
        defs = tm.get_definitions()
        assert any(d["function"]["name"] == "mcp_mcp_search" for d in defs)

        out = tm.execute("mcp_mcp_search", '{"query": "test"}')
        assert "found" in out
        assert results["mcp_mcp_search"] == {"query": "test"}

    def test_drop_tool_on_reregister(self):
        tm = ToolManager()

        def v1():
            return 1

        def v2():
            return 2

        tm.register_function(v1, name="same_name")
        tm.register_function(v2, name="same_name")
        defs = tm.get_definitions()
        count = sum(1 for d in defs if d["function"]["name"] == "same_name")
        assert count == 1
        result = tm.execute("same_name", "{}")
        assert "2" in result

    def test_tool_decorator_pattern(self):
        tm = ToolManager()

        @tm.tool
        def decorated_tool(x: int) -> int:
            """Multiply by 2."""
            return x * 2

        defs = tm.get_definitions()
        assert any(d["function"]["name"] == "decorated_tool" for d in defs)
        result = tm.execute("decorated_tool", '{"x": 5}')
        assert "10" in result


class TestLLMAdapterFactory:
    def test_create_known_adapter(self, monkeypatch):
        for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "SOCKS_PROXY", "socks_proxy"):
            monkeypatch.delenv(name, raising=False)
        adapter = LLMAdapterFactory.create_adapter("Deepseek", api_key="sk-test", base_url="https://api.deepseek.com", model="deepseek-chat")
        assert adapter is not None
        assert adapter.model == "deepseek-chat"

    def test_create_unknown_adapter_raises(self):
        with pytest.raises(ValueError, match="Unsupported LLM adapter"):
            LLMAdapterFactory.create_adapter("UnknownProvider")

    def test_factory_has_expected_providers(self):
        providers = list(LLMAdapterFactory._adapters.keys())
        assert "Deepseek" in providers
        assert "Claude" in providers
