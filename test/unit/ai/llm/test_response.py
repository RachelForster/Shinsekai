from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ai.llm.adapter_factory import LLMAdapterFactory
from ai.llm.response import create_stream_decoder, decode_response


def _openai_chunk(*, content=None, reasoning=None, tool_calls=None):
    delta = SimpleNamespace(
        content=content,
        reasoning_content=reasoning,
        tool_calls=tool_calls or [],
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _tool_delta(index: int, *, tool_id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index,
        id=tool_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def test_openai_stream_decoder_accumulates_content_reasoning_and_tools() -> None:
    decoder = create_stream_decoder("openai")
    chunks = [
        _openai_chunk(
            reasoning="think ",
            tool_calls=[
                _tool_delta(0, tool_id="call_1", name="search", arguments=None)
            ],
        ),
        _openai_chunk(
            content="hello",
            tool_calls=[_tool_delta(0, arguments='{"query":')],
        ),
        _openai_chunk(tool_calls=[_tool_delta(0, arguments='"weather"}')]),
    ]

    deltas = list(decoder.consume(chunks, cancelled=lambda: False))
    result = decoder.result()

    assert [delta.reasoning for delta in deltas if delta.reasoning] == ["think "]
    assert [delta.content for delta in deltas if delta.content] == ["hello"]
    assert result.content == "hello"
    assert result.reasoning == "think "
    assert result.tool_calls[0].as_message() == {
        "id": "call_1",
        "type": "function",
        "function": {"name": "search", "arguments": '{"query":"weather"}'},
    }


def test_openai_sync_decoder_preserves_raw_tool_call_extras() -> None:
    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="search", arguments="{}"),
        model_extra={},
    )
    message = SimpleNamespace(
        content="",
        reasoning_content=None,
        tool_calls=[tool_call],
    )
    raw = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "extra_content": {
                                "google": {"thought_signature": "signature"}
                            }
                        }
                    ]
                }
            }
        ]
    }
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        model_dump_json=lambda: json.dumps(raw),
    )

    result = decode_response("openai", response)

    assert result.tool_calls[0].as_message()["extra_content"] == {
        "google": {"thought_signature": "signature"}
    }


def test_anthropic_sync_decoder_normalizes_content_and_tools() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="hello"),
            SimpleNamespace(
                type="tool_use",
                id="call_1",
                name="search",
                input={"query": "weather"},
            ),
        ]
    )

    result = decode_response("anthropic", response)

    assert result.content == "hello"
    assert result.tool_calls[0].as_message()["function"] == {
        "name": "search",
        "arguments": {"query": "weather"},
    }


def test_anthropic_stream_decoder_owns_wire_event_handling() -> None:
    class EventStream:
        def __init__(self, events):
            self.events = events

        def __enter__(self):
            return iter(self.events)

        def __exit__(self, *_args):
            return False

    events = [
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="text_delta", text="hello"),
        ),
        SimpleNamespace(
            type="content_block_start",
            index=1,
            content_block=SimpleNamespace(
                type="tool_use",
                id="call_1",
                name="search",
            ),
        ),
        SimpleNamespace(
            type="record_delta",
            index=1,
            delta=SimpleNamespace(type="input_json_delta", partial_json='{"q":"x"}'),
        ),
    ]
    decoder = create_stream_decoder("anthropic")

    deltas = list(decoder.consume(EventStream(events), cancelled=lambda: False))
    result = decoder.result()

    assert [delta.content for delta in deltas] == ["hello"]
    assert result.tool_calls[0].as_message()["function"] == {
        "name": "search",
        "arguments": '{"q":"x"}',
    }


def test_unknown_response_protocol_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported LLM response protocol"):
        create_stream_decoder("unknown")


def test_factory_sets_provider_response_capabilities(monkeypatch) -> None:
    for name in (
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "SOCKS_PROXY",
        "socks_proxy",
    ):
        monkeypatch.delenv(name, raising=False)

    adapter = LLMAdapterFactory.create_adapter(
        "Gemini",
        api_key="sk-test",
        base_url="https://example.test",
        model="gemini-test",
    )

    assert adapter.provider == "Gemini"
    assert adapter.response_protocol == "openai"
    assert adapter.supports_streaming_tools is False
