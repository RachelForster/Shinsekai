"""Wire-format compatibility and stream resource ownership of response codecs."""

import copy
from types import SimpleNamespace

import pytest

from sdk.llm_response import AnthropicResponseCodec, ChatResponse, OpenAIResponseCodec, ResponseDelta


def response(text="", *, reasoning="", calls=()):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, reasoning_content=reasoning, tool_calls=list(calls)))])


def tool_call(name, arguments="{}", *, call_id="c", extra=None):
    return SimpleNamespace(id=call_id, index=0, function=SimpleNamespace(name=name, arguments=arguments), model_extra=extra or {})


def chunk(text=None, *, calls=()):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=list(calls)))])


class ClaudeStream:
    def __init__(self, *events):
        self.events, self.closed = events, False

    def __enter__(self):
        return iter(self.events)

    def __exit__(self, *exc):
        self.closed = True


def test_openai_decoder_keeps_text_reasoning_and_tool_metadata():
    original = response("text", reasoning="reason", calls=[tool_call("probe", extra={"extra_content": {"google": {"thought_signature": "sig"}}})])
    decoded = OpenAIResponseCodec().decode(original)
    assert decoded.content == "text" and decoded.reasoning == "reason"
    assert decoded.tool_calls[0]["extra_content"]["google"]["thought_signature"] == "sig"
    decoded.tool_calls[0]["extra_content"]["google"]["thought_signature"] = "changed"
    assert original.choices[0].message.tool_calls[0].model_extra["extra_content"]["google"]["thought_signature"] == "sig"


def test_normalized_responses_and_deltas_are_valid_default_adapter_outputs():
    value = ChatResponse(content="answer")
    assert OpenAIResponseCodec().decode(value) is value
    deltas = [ResponseDelta(reasoning="reason"), ResponseDelta(content="answer")]
    assert list(OpenAIResponseCodec().iter_stream(iter(deltas), cancelled=lambda: False)) == deltas


def test_stream_accumulation_accepts_late_identity_and_does_not_mutate_chunks():
    chunks = [
        chunk(calls=[tool_call(None, None, call_id=None)]),
        chunk(calls=[tool_call("probe", '{"value":', call_id="late-id")]),
        chunk(calls=[tool_call(None, '3}', call_id=None, extra={"extra_content": {"signature": "sig"}})]),
    ]
    before = copy.deepcopy(chunks)
    output = list(OpenAIResponseCodec().iter_stream(iter(chunks), cancelled=lambda: False))
    assert output[-1].tool_calls == [{
        "id": "late-id", "type": "function", "function": {"name": "probe", "arguments": '{"value":3}'},
        "extra_content": {"signature": "sig"},
    }]
    assert chunks == before


@pytest.mark.parametrize("action", ["complete", "cancel", "close", "error"])
def test_openai_stream_closes_provider_iterator_on_every_exit(action):
    closed = []
    cancelled = [False]
    def raw_stream():
        try:
            yield chunk("one")
            if action == "error":
                raise RuntimeError("broken stream")
            yield chunk("two")
        finally:
            closed.append(True)
    stream = OpenAIResponseCodec().iter_stream(raw_stream(), cancelled=lambda: cancelled[0])
    assert next(stream).content == "one"
    if action == "close":
        stream.close()
    elif action == "error":
        with pytest.raises(RuntimeError, match="broken stream"):
            list(stream)
    else:
        cancelled[0] = action == "cancel"
        assert list(stream) == ([] if action == "cancel" else [ResponseDelta(content="two")])
    assert closed == [True]


def test_empty_usage_and_heartbeat_chunks_do_not_create_assistant_content():
    output = list(OpenAIResponseCodec().iter_stream(iter([None, SimpleNamespace(choices=[]), chunk("answer")]), cancelled=lambda: False))
    assert output == [ResponseDelta(content="answer")]


@pytest.mark.parametrize("event_type", ["content_block_delta", "record_delta"])
def test_anthropic_stream_accepts_current_and_legacy_argument_events(event_type):
    raw = ClaudeStream(
        SimpleNamespace(type="content_block_start", index=1, content_block=SimpleNamespace(type="tool_use", id="c", name="probe")),
        SimpleNamespace(type=event_type, index=1, delta=SimpleNamespace(type="input_json_delta", partial_json='{"value":')),
        SimpleNamespace(type=event_type, index=1, delta=SimpleNamespace(type="input_json_delta", partial_json='3}')),
    )
    output = list(AnthropicResponseCodec().iter_stream(raw, cancelled=lambda: False))
    assert output == [ResponseDelta(tool_calls=[{
        "id": "c", "type": "function", "function": {"name": "probe", "arguments": '{"value":3}'},
    }])]
    assert raw.closed


def test_anthropic_cancellation_closes_context_without_tool_execution():
    raw = ClaudeStream(SimpleNamespace(type="content_block_start", index=0, content_block=SimpleNamespace(type="tool_use", id="c", name="probe")))
    assert list(AnthropicResponseCodec().iter_stream(raw, cancelled=lambda: True)) == []
    assert raw.closed


def test_anthropic_decoder_ignores_non_dialog_blocks_and_preserves_tool_input():
    value = SimpleNamespace(content=[
        SimpleNamespace(type="thinking", thinking="private"),
        SimpleNamespace(type="text", text="one"),
        SimpleNamespace(type="text", text="two"),
        SimpleNamespace(type="tool_use", id="c", name="probe", input={"value": 3}),
    ])
    decoded = AnthropicResponseCodec().decode(value)
    assert decoded.content == "onetwo"
    assert decoded.tool_calls[0]["function"]["arguments"] == {"value": 3}
