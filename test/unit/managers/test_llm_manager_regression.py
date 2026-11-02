"""Exercise public chat behavior with provider-shaped responses, without network I/O."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai.llm.llm_adapter import ClaudeAdapter, DeepSeekAdapter, OpenAIAdapter
from ai.llm.llm_manager import LLMManager, tool_executor, tool_manager
from core.messaging.stream_events import STREAM_DIALOG_REPAIR_KEY, STREAM_REASONING_DELTA_KEY
from sdk.adapters.llm import LLMAdapter
from sdk.hooks import PluginHookDispatcher


def response(text="", calls=(), reasoning=""):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content=text, tool_calls=list(calls), reasoning_content=reasoning,
    ))])


def tool_call(name, arguments="{}", *, call_id="call_1", index=0, extra=None):
    return SimpleNamespace(
        id=call_id, index=index,
        function=SimpleNamespace(name=name, arguments=arguments),
        model_extra=extra or {},
    )


def chunk(text=None, *, reasoning=None, calls=()):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
        content=text, reasoning_content=reasoning, tool_calls=list(calls),
    ))])


class ScriptedAdapter(LLMAdapter):
    def __init__(self, *replies, **kwargs):
        LLMAdapter.__init__(self, **kwargs)
        self.replies = iter(replies)
        self.requests = []
        self.cancel_count = 0

    def chat(self, messages, stream=False, **kwargs):
        self.requests.append(copy.deepcopy({"messages": messages, "stream": stream, **kwargs}))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply() if callable(reply) else reply

    def cancel(self):
        self.cancel_count += 1


class ScriptedClaudeAdapter(ScriptedAdapter, ClaudeAdapter):
    pass


class ScriptedOpenAIAdapter(ScriptedAdapter, OpenAIAdapter):
    pass


class ScriptedDeepSeekAdapter(ScriptedAdapter, DeepSeekAdapter):
    def __init__(self, *replies, thinking_enabled=True):
        super().__init__(*replies)
        self.thinking_enabled = thinking_enabled


class ClaudeStream:
    def __init__(self, *events):
        self.events = events
        self.closed = False

    def __enter__(self):
        return iter(self.events)

    def __exit__(self, *exc):
        self.closed = True


@pytest.fixture(autouse=True)
def isolated_tools_and_host(monkeypatch):
    for field, value in (
        ("_tools_definitions", []), ("_functions", {}),
        ("_tool_groups", {}), ("_tool_risks", {}),
    ):
        monkeypatch.setattr(tool_manager, field, value)
    monkeypatch.setattr(tool_executor, "_cooldowns", {})
    config = SimpleNamespace(config=SimpleNamespace(api_config=SimpleNamespace(llm_provider="ChatGPT")))
    monkeypatch.setattr("config.config_manager.ConfigManager", lambda: config)
    host = SimpleNamespace(
        notify_tool_call=Mock(), confirm_risky_tool=Mock(return_value=True),
        post_context_token_estimate=Mock(), notify_tool_ready=Mock(),
    )
    monkeypatch.setattr("ai.llm.llm_manager.get_llm_host_runtime", lambda: host)
    return host


def run_chat(manager, *, stream, **kwargs):
    result = manager.chat("hello", stream=stream, include_local_time=False, **kwargs)
    return list(result) if stream else result


@pytest.mark.parametrize("stream", [False, True])
def test_plain_response_persists_exactly_once_and_closes_turn(stream):
    adapter = ScriptedAdapter(iter([chunk("hello "), chunk("world")]) if stream else response("hello world"))
    manager = LLMManager(adapter, user_template="rules")
    result = run_chat(manager, stream=stream)
    assert result == (["hello ", "world"] if stream else "hello world")
    assert manager.messages == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hello world"},
    ]
    assert manager._chat_depth == 0
    assert manager._turn_state is None


def test_interleaved_stream_tool_arguments_reach_actual_executor_in_index_order():
    executed = []
    tool_manager.register_function(lambda value: executed.append(value) or {"value": value}, name="record")
    adapter = ScriptedAdapter(iter([
        chunk(calls=[tool_call("record", None, call_id="b", index=1)]),
        chunk(calls=[tool_call("record", '{"value":', call_id="a", index=0)]),
        chunk(calls=[tool_call(None, '{"value":"second"}', index=1)]),
        chunk(calls=[tool_call(None, '"first"}', index=0)]),
    ]), iter([chunk("done")]))
    manager = LLMManager(adapter, first_turn_tool_call_limit=10)
    assert run_chat(manager, stream=True) == ["done"]
    assert executed == ["first", "second"]
    assert [m["role"] for m in manager.messages] == ["system", "user", "assistant", "tool", "tool", "assistant"]
    assert [m["tool_call_id"] for m in manager.messages if m["role"] == "tool"] == ["a", "b"]
    assert manager.messages[2]["tool_calls"][1]["function"]["arguments"] == '{"value":"second"}'


@pytest.mark.parametrize("stream", [False, True])
def test_tool_metadata_survives_history_and_followup_request(stream):
    tool_manager.register_function(lambda: "ok", name="probe")
    extra = {"extra_content": {"google": {"thought_signature": "signature"}}}
    call = tool_call("probe", extra=extra)
    first = iter([chunk(calls=[call])]) if stream else response(calls=[call])
    adapter = ScriptedAdapter(first, iter([chunk("done")]) if stream else response("done"))
    manager = LLMManager(adapter)
    run_chat(manager, stream=stream)
    assert manager.messages[2]["tool_calls"][0]["extra_content"] == extra["extra_content"]
    assert adapter.requests[1]["messages"][2]["tool_calls"][0]["extra_content"] == extra["extra_content"]


def test_sync_recovers_metadata_dropped_from_provider_object():
    tool_manager.register_function(lambda: "ok", name="probe")
    first = response(calls=[tool_call("probe")])
    first.to_json = lambda: json.dumps({"choices": [{"message": {"tool_calls": [{
        "extra_content": '{"google":{"thought_signature":"raw-signature"}}',
    }]}}]})
    manager = LLMManager(ScriptedAdapter(first, response("done")))
    run_chat(manager, stream=False)
    assert manager.messages[2]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "raw-signature"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("thinking", [False, True])
def test_deepseek_reasoning_history_follows_adapter_thinking_mode(stream, thinking):
    reply = iter([chunk(reasoning="reason"), chunk("answer")]) if stream else response("answer", reasoning="reason")
    manager = LLMManager(ScriptedDeepSeekAdapter(reply, thinking_enabled=thinking))
    result = run_chat(manager, stream=stream)
    if stream:
        assert result == [{STREAM_REASONING_DELTA_KEY: "reason"}, "answer"]
    assert manager.messages[-1] == {"role": "assistant", "content": "answer", **({"reasoning_content": "reason"} if thinking else {})}


def test_claude_sync_text_and_tool_blocks_use_same_history_contract():
    tool_manager.register_function(lambda value: value, name="probe")
    first = SimpleNamespace(content=[
        SimpleNamespace(type="text", text="checking"),
        SimpleNamespace(type="tool_use", id="claude-call", name="probe", input={"value": "ok"}),
    ])
    adapter = ScriptedClaudeAdapter(first, SimpleNamespace(content=[SimpleNamespace(type="text", text="done")]))
    manager = LLMManager(adapter)
    assert run_chat(manager, stream=False) == "done"
    assert manager.messages[2]["content"] == "checking"
    assert manager.messages[2]["tool_calls"][0]["function"]["arguments"] == {"value": "ok"}
    assert manager.messages[3]["tool_call_id"] == "claude-call"


def test_claude_stream_closes_context_and_accumulates_legacy_json_events():
    tool_manager.register_function(lambda value: value, name="probe")
    first = ClaudeStream(
        SimpleNamespace(type="content_block_start", index=0, content_block=SimpleNamespace(type="tool_use", id="c", name="probe")),
        SimpleNamespace(type="record_delta", index=0, delta=SimpleNamespace(type="input_json_delta", partial_json='{"value":"ok"}')),
    )
    last = ClaudeStream(SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text="done")))
    manager = LLMManager(ScriptedClaudeAdapter(first, last))
    assert run_chat(manager, stream=True) == ["done"]
    assert first.closed and last.closed
    assert manager.messages[2]["tool_calls"][0]["function"]["arguments"] == '{"value":"ok"}'


@pytest.mark.parametrize("stream", [False, True])
def test_request_exception_propagates_and_scope_is_reusable(stream):
    adapter = ScriptedAdapter(RuntimeError("offline"), iter([chunk("recovered")]) if stream else response("recovered"))
    manager = LLMManager(adapter)
    with pytest.raises(RuntimeError, match="offline"):
        run_chat(manager, stream=stream)
    assert manager._chat_depth == 0 and manager._turn_state is None
    assert not any(m["role"] == "assistant" for m in manager.messages)
    assert run_chat(manager, stream=stream) == (["recovered"] if stream else "recovered")


def test_partial_stream_failure_propagates_without_persisting_partial_answer():
    def broken_stream():
        yield chunk("partial")
        raise RuntimeError("stream failed")
    manager = LLMManager(ScriptedAdapter(broken_stream))
    stream = manager.chat("hello", include_local_time=False)
    assert next(stream) == "partial"
    with pytest.raises(RuntimeError, match="stream failed"):
        next(stream)
    assert manager._chat_depth == 0 and manager._active_tool_groups == ["default"]
    assert manager.messages[-1]["role"] == "user"


def test_closing_partially_consumed_stream_releases_scope_and_does_not_persist():
    manager = LLMManager(ScriptedAdapter(iter([chunk("one"), chunk("two")])))
    stream = manager.chat("hello", include_local_time=False, tool_groups=["memory"])
    assert next(stream) == "one"
    stream.close()
    assert manager._chat_depth == 0 and manager._turn_state is None
    assert manager._active_tool_groups == ["default"]
    assert manager.messages[-1]["role"] == "user"


@pytest.mark.parametrize("stream", [False, True])
def test_cancel_during_request_does_not_persist_answer(stream):
    adapter = ScriptedAdapter()
    manager = LLMManager(adapter)
    def cancelled_reply():
        manager.cancel_current_chat()
        return iter([chunk("discard")]) if stream else response("discard")
    adapter.replies = iter([cancelled_reply])
    assert run_chat(manager, stream=stream) == ([] if stream else "")
    assert adapter.cancel_count == 1
    assert manager.messages[-1]["role"] == "user"
    assert manager._chat_depth == 0


@pytest.mark.parametrize("stream", [False, True])
def test_tools_disabled_rejects_unexpected_provider_tool_call(stream):
    first = iter([chunk(calls=[tool_call("probe")])]) if stream else response(calls=[tool_call("probe")])
    adapter = ScriptedAdapter(first)
    manager = LLMManager(adapter, tools_enabled=False)
    with pytest.raises(ValueError, match="tool call"):
        run_chat(manager, stream=stream)
    assert adapter.requests[0]["tools"] is None
    assert manager._chat_depth == 0


@pytest.mark.parametrize("stream", [False, True])
def test_risky_tool_denial_is_recorded_and_does_not_execute(stream, isolated_tools_and_host):
    executed = []
    tool_manager.register_function(lambda: executed.append(True), name="write", risk="high")
    isolated_tools_and_host.confirm_risky_tool.return_value = False
    adapter = ScriptedAdapter(
        iter([chunk(calls=[tool_call("write")])]) if stream else response(calls=[tool_call("write")]),
        iter([chunk("denied")]) if stream else response("denied"),
    )
    manager = LLMManager(adapter)
    run_chat(manager, stream=stream)
    assert not executed
    assert json.loads(manager.messages[3]["content"])["cancelled"] is True
    isolated_tools_and_host.confirm_risky_tool.assert_called_once_with("write", "high", "{}")


@pytest.mark.parametrize("stream", [False, True])
def test_no_response_finishes_scope_without_assistant_history(stream):
    manager = LLMManager(ScriptedAdapter(None))
    assert run_chat(manager, stream=stream) == ([] if stream else "")
    assert manager.messages[-1]["role"] == "user"
    assert manager._chat_depth == 0 and manager._turn_state is None


@pytest.mark.parametrize("stream", [False, True])
def test_dialog_repair_is_tool_free_and_persists_only_repaired_answer(stream):
    repaired = '{"dialog":[{"character_name":"Alice","sprite":"0","speech":"hi"}]}'
    adapter = ScriptedAdapter(iter([chunk("bad JSON")]) if stream else response("bad JSON"), response(repaired))
    manager = LLMManager(adapter)
    result = run_chat(manager, stream=stream, dialog_output_required=True)
    assert result == (["bad JSON", {STREAM_DIALOG_REPAIR_KEY: repaired}] if stream else repaired)
    assert adapter.requests[1]["stream"] is False and adapter.requests[1]["tools"] is None
    assert manager.messages[-1]["content"] == repaired
    assert len([m for m in manager.messages if m["role"] == "assistant"]) == 1


def test_message_journal_and_story_hook_preserve_persistence_ownership(tmp_path):
    history = tmp_path / "history.json"
    manager = LLMManager(ScriptedAdapter(response("answer")), history_file=str(history))
    run_chat(manager, stream=False)
    saved = [json.loads(line.rstrip(",\n")) for line in history.with_suffix(".json.tmp").read_text(encoding="utf-8").splitlines()]
    assert saved == manager.messages[1:]

    intercepted = tmp_path / "story.json"
    manager = LLMManager(ScriptedAdapter(response("story answer")), history_file=str(intercepted))
    hook = SimpleNamespace(persist_message=Mock(return_value=True))
    manager.story_prompt_hooks = hook
    run_chat(manager, stream=False)
    assert hook.persist_message.call_count == 2
    assert not intercepted.with_suffix(".json.tmp").exists()


@pytest.mark.parametrize("stream", [False, True])
def test_tool_pair_recovery_retries_request_copy_without_changing_history(stream):
    class PairError(Exception):
        status_code = 400
        def __str__(self):
            return "Messages with role 'tool' must be a response to a preceding message with 'tool_calls'"
    dispatcher = PluginHookDispatcher()
    dispatcher.register_before_chat(lambda context: context.messages.append({"role": "tool", "tool_call_id": "orphan", "content": "bad"}))
    adapter = ScriptedAdapter(PairError(), iter([chunk("done")]) if stream else response("done"))
    manager = LLMManager(adapter, hook_dispatcher=dispatcher)
    run_chat(manager, stream=stream)
    assert adapter.requests[0]["messages"][-1]["role"] == "tool"
    assert adapter.requests[1]["messages"][-1]["role"] == "user"
    assert [m["role"] for m in manager.messages] == ["system", "user", "assistant"]


@pytest.mark.parametrize("stream", [False, True])
def test_executor_failure_becomes_tool_result_and_followup_continues(stream, monkeypatch):
    tool_manager.register_function(lambda: "ok", name="probe")
    monkeypatch.setattr(tool_executor, "execute", Mock(side_effect=RuntimeError("broken tool")))
    adapter = ScriptedAdapter(
        iter([chunk(calls=[tool_call("probe", "")])]) if stream else response(calls=[tool_call("probe", "")]),
        iter([chunk("done")]) if stream else response("done"),
    )
    manager = LLMManager(adapter)
    run_chat(manager, stream=stream)
    assert json.loads(manager.messages[3]["content"]) == {"error": "broken tool"}
    assert tool_executor.execute.call_args.args == ("probe", "{}")
    assert manager.messages[-1]["content"] == "done"


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("result", [None, {"value": 3}])
def test_executor_results_are_normalized_into_serializable_history(stream, result, monkeypatch):
    tool_manager.register_function(lambda: "ok", name="probe")
    monkeypatch.setattr(tool_executor, "execute", Mock(return_value=result))
    adapter = ScriptedAdapter(
        iter([chunk(calls=[tool_call("probe")])]) if stream else response(calls=[tool_call("probe")]),
        iter([chunk("done")]) if stream else response("done"),
    )
    manager = LLMManager(adapter)
    run_chat(manager, stream=stream)
    assert json.loads(manager.messages[3]["content"]) == (result if result is not None else {"status": "success", "result": "no return value"})


@pytest.mark.parametrize("stream", [False, True])
def test_cooldown_tool_call_is_skipped_even_if_provider_ignores_filtered_definitions(stream, monkeypatch):
    executed = []
    tool_manager.register_function(lambda: executed.append(True), name="probe", group="vision")
    monkeypatch.setattr(tool_executor, "cooldown_message_for_tool", lambda name: '{"message":"loading"}')
    adapter = ScriptedAdapter(
        iter([chunk(calls=[tool_call("probe")])]) if stream else response(calls=[tool_call("probe")]),
        iter([chunk("done")]) if stream else response("done"),
    )
    manager = LLMManager(adapter)
    run_chat(manager, stream=stream)
    assert not executed
    assert json.loads(manager.messages[3]["content"])["reason"] == "tool_group_in_cooldown"


def test_gemini_tool_stream_uses_sync_request_and_preserves_public_stream(monkeypatch):
    config = SimpleNamespace(config=SimpleNamespace(api_config=SimpleNamespace(llm_provider="Gemini")))
    monkeypatch.setattr("config.config_manager.ConfigManager", lambda: config)
    tool_manager.register_function(lambda: "ok", name="probe")
    adapter = ScriptedOpenAIAdapter(response("done"), llm_provider="Gemini")
    manager = LLMManager(adapter)
    assert run_chat(manager, stream=True) == list("done")
    assert adapter.requests[0]["stream"] is False
    assert manager._chat_depth == 0


@pytest.mark.parametrize("risk,allowed", [("high", False), ("medium", True)])
def test_confirmation_host_failure_keeps_existing_risk_policy(risk, allowed, isolated_tools_and_host):
    isolated_tools_and_host.confirm_risky_tool.side_effect = RuntimeError("no UI")
    manager = LLMManager(ScriptedAdapter())
    assert manager._confirm_risky_tool("probe", risk, "{}") is allowed
