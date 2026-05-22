"""Unit tests for LLMManager — message management, compact, tool calling."""

import json
import pytest

from llm.llm_manager import LLMManager, LLMAdapterFactory
from llm.compact_manager import CompactManager
from llm.tools.tool_manager import ToolManager
from test.mocks import MockLLMAdapter


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

    def test_set_messages_drops_loaded_tool_payloads(self, mock_llm_adapter):
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
        assert all(message.get("role") != "tool" for message in mgr.messages)
        assert all("tool_calls" not in message for message in mgr.messages)
        assert [message["content"] for message in mgr.messages] == [
            "System prompt",
            "read a file",
            "I found the answer.",
        ]

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

    def test_chat_exclude_local_time_preserves_text(self, mock_llm_adapter):
        mock_llm_adapter.responses = ["Response."]
        mgr = LLMManager(adapter=mock_llm_adapter, user_template="S")
        mgr.chat("Hello", stream=False, include_local_time=False)
        user_msg = mgr.messages[-2]["content"]
        assert user_msg == "Hello"


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
        assert len(parsed["preview"]) <= 80

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
    def test_create_known_adapter(self):
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
