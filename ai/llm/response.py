"""Normalize provider wire responses for the chat transport."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
import json
import logging
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Any
    extras: dict[str, Any] = field(default_factory=dict)

    def as_message(self) -> dict[str, Any]:
        call = {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }
        extras = dict(self.extras)
        call["function"].update(extras.pop("function", {}))
        call.update(extras)
        return call


@dataclass
class Response:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass(frozen=True)
class ResponseDelta:
    content: str = ""
    reasoning: str = ""


class StreamDecoder(Protocol):
    cancelled: bool

    def consume(
        self,
        response_stream: Any,
        *,
        cancelled: Callable[[], bool],
    ) -> Iterator[ResponseDelta]: ...

    def result(self) -> Response: ...


def _extract_tool_call_raw_extras(tool_call: dict) -> dict:
    extras: dict = {}
    extra_content = tool_call.get("extra_content")
    if isinstance(extra_content, str) and extra_content.strip():
        try:
            extra_content = json.loads(extra_content)
        except Exception:
            pass
    if isinstance(extra_content, dict):
        extras["extra_content"] = extra_content
    return extras


def tool_call_extras(tool_call, raw_tool_call: dict | None = None) -> dict:
    """Collect provider extension fields from dict or SDK tool-call objects."""
    extras: dict = {}
    if isinstance(tool_call, dict):
        extras.update(_extract_tool_call_raw_extras(tool_call))
        if raw_tool_call:
            extras.update(_extract_tool_call_raw_extras(raw_tool_call))
        return extras

    raw = {}
    try:
        raw = (
            tool_call.to_dict() if callable(getattr(tool_call, "to_dict", None)) else {}
        )
    except Exception:
        pass
    if not raw:
        try:
            raw = getattr(tool_call, "model_extra", None) or {}
        except Exception:
            pass
    if not raw:
        try:
            raw = {
                key: value
                for key, value in tool_call.__dict__.items()
                if not key.startswith("_")
            }
        except Exception:
            pass
    extras.update(_extract_tool_call_raw_extras(raw))
    if raw_tool_call:
        extras.update(_extract_tool_call_raw_extras(raw_tool_call))
    return extras


def raw_response_tool_call_extras(
    response: Any, *, logger: logging.Logger | None = None
) -> list[dict]:
    """Read per-tool-call extension fields from an SDK response's raw JSON."""
    output: list[dict] = []
    raw_text = ""
    for method_name in ("to_json", "model_dump_json"):
        method = getattr(response, method_name, None)
        if callable(method):
            try:
                raw_text = method()
                if raw_text:
                    break
            except Exception:
                pass
    if not raw_text:
        return output
    try:
        raw_data = json.loads(raw_text)
        raw_calls = (
            raw_data.get("choices", [{}])[0].get("message", {}).get("tool_calls", [])
        )
        output.extend(_extract_tool_call_raw_extras(call) for call in raw_calls)
        if logger is not None and output and any(output):
            logger.info(
                "Found provider extras for %s tool call(s)",
                sum(1 for extra in output if extra),
            )
    except Exception as exc:
        if logger is not None:
            logger.warning("Failed to parse raw response tool calls: %s", exc)
    return output


def _openai_tool_call(tool_call: Any, raw_extra: dict | None = None) -> ToolCall:
    return ToolCall(
        id=tool_call.id,
        name=tool_call.function.name,
        arguments=tool_call.function.arguments,
        extras=tool_call_extras(tool_call, raw_extra),
    )


class OpenAIStreamDecoder:
    def __init__(self) -> None:
        self.cancelled = False
        self._content = ""
        self._reasoning = ""
        self._tool_calls: dict[int, Any] = {}

    def consume(
        self,
        response_stream: Any,
        *,
        cancelled: Callable[[], bool],
    ) -> Iterator[ResponseDelta]:
        for chunk in response_stream:
            if cancelled():
                self.cancelled = True
                break
            if not chunk or not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            for tool_call in getattr(delta, "tool_calls", None) or []:
                accumulated = self._tool_calls.get(tool_call.index)
                if accumulated is None:
                    self._tool_calls[tool_call.index] = tool_call
                elif tool_call.function and tool_call.function.arguments:
                    if accumulated.function.arguments is None:
                        accumulated.function.arguments = ""
                    accumulated.function.arguments += tool_call.function.arguments

            reasoning = getattr(delta, "reasoning_content", None) or ""
            content = getattr(delta, "content", None) or ""
            if reasoning:
                self._reasoning += reasoning
                yield ResponseDelta(reasoning=reasoning)
            if content:
                self._content += content
                yield ResponseDelta(content=content)

    def result(self) -> Response:
        return Response(
            content=self._content,
            reasoning=self._reasoning,
            tool_calls=[
                _openai_tool_call(self._tool_calls[index])
                for index in sorted(self._tool_calls)
            ],
        )


class AnthropicStreamDecoder:
    def __init__(self) -> None:
        self.cancelled = False
        self._content = ""
        self._tool_calls: dict[int, dict[str, Any]] = {}

    def consume(
        self,
        response_stream: Any,
        *,
        cancelled: Callable[[], bool],
    ) -> Iterator[ResponseDelta]:
        with response_stream as stream:
            for event in stream:
                if cancelled():
                    self.cancelled = True
                    break
                if (
                    event.type == "content_block_delta"
                    and event.delta.type == "text_delta"
                ):
                    self._content += event.delta.text
                    yield ResponseDelta(content=event.delta.text)
                elif (
                    event.type == "content_block_start"
                    and event.content_block.type == "tool_use"
                ):
                    self._tool_calls[event.index] = {
                        "id": event.content_block.id,
                        "name": event.content_block.name,
                        "arguments": "",
                    }
                elif (
                    event.type == "record_delta"
                    and event.delta.type == "input_json_delta"
                ):
                    self._tool_calls[event.index][
                        "arguments"
                    ] += event.delta.partial_json

    def result(self) -> Response:
        return Response(
            content=self._content,
            tool_calls=[
                ToolCall(**self._tool_calls[index])
                for index in sorted(self._tool_calls)
            ],
        )


_STREAM_DECODERS: dict[
    str, type[OpenAIStreamDecoder] | type[AnthropicStreamDecoder]
] = {
    "openai": OpenAIStreamDecoder,
    "anthropic": AnthropicStreamDecoder,
}


def create_stream_decoder(protocol: str) -> StreamDecoder:
    try:
        decoder = _STREAM_DECODERS[protocol]
    except KeyError as exc:
        raise ValueError(f"Unsupported LLM response protocol: {protocol!r}") from exc
    return decoder()


def decode_response(
    protocol: str,
    response: Any,
    *,
    logger: logging.Logger | None = None,
) -> Response:
    if protocol == "anthropic":
        content = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input,
                    )
                )
        return Response(content=content, tool_calls=tool_calls)

    if protocol != "openai":
        raise ValueError(f"Unsupported LLM response protocol: {protocol!r}")

    message = response.choices[0].message
    raw_extras = raw_response_tool_call_extras(response, logger=logger)
    raw_calls = getattr(message, "tool_calls", None) or []
    return Response(
        content=message.content or "",
        reasoning=getattr(message, "reasoning_content", None) or "",
        tool_calls=[
            _openai_tool_call(
                tool_call,
                raw_extras[index] if index < len(raw_extras) else None,
            )
            for index, tool_call in enumerate(raw_calls)
        ],
    )
