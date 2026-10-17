"""Provider-neutral responses and codecs for legacy provider response objects.

The default codec preserves the OpenAI-compatible contract used by existing
plugins. Adapters select or override codecs; conversation policy does not
inspect concrete adapter types.
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass
class ChatResponse:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ResponseDelta:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class ResponseCodec(Protocol):
    def decode(self, response: Any) -> ChatResponse: ...
    def iter_stream(self, response: Any, *, cancelled: Callable[[], bool]) -> Iterator[ResponseDelta]: ...


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _formatted_call(value: Any, raw_extra: dict | None = None) -> dict:
    function = _field(value, "function")
    name = _field(function, "name") if function is not None else _field(value, "name")
    arguments = _field(function, "arguments") if function is not None else _field(value, "input")
    call = {
        "id": _field(value, "id"), "type": "function",
        "function": {"name": name, "arguments": arguments},
    }
    extras = _tool_call_extras(value, raw_extra)
    call["function"].update(extras.pop("function", {}))
    call.update(copy.deepcopy(extras))
    return call


class ToolCallAccumulator:
    """Assemble interleaved deltas without mutating provider-owned chunks."""

    def __init__(self) -> None:
        self._calls: dict[int, dict] = {}

    def add(self, value: Any) -> None:
        index = _field(value, "index", 0)
        incoming = _formatted_call(value)
        if index not in self._calls:
            self._calls[index] = incoming
            return
        current = self._calls[index]
        if not current["id"] and incoming["id"]:
            current["id"] = incoming["id"]
        if not current["function"]["name"] and incoming["function"]["name"]:
            current["function"]["name"] = incoming["function"]["name"]
        arguments = incoming["function"]["arguments"]
        if arguments:
            current["function"]["arguments"] = (current["function"]["arguments"] or "") + arguments
        for key, value in incoming.items():
            if key not in {"id", "type", "function"}:
                current[key] = value

    def finish(self) -> list[dict]:
        return [self._calls[index] for index in sorted(self._calls)]


class OpenAIResponseCodec:
    def decode(self, response: Any) -> ChatResponse:
        if isinstance(response, ChatResponse):
            return response
        message = _field(_field(response, "choices")[0], "message")
        calls = _field(message, "tool_calls", []) or []
        raw_extras = _raw_response_tool_call_extras(response) if calls else []
        return ChatResponse(
            content=_field(message, "content") or "",
            reasoning=_field(message, "reasoning_content") or "",
            tool_calls=[
                _formatted_call(call, raw_extras[index] if index < len(raw_extras) else None)
                for index, call in enumerate(calls)
            ],
        )

    def iter_stream(self, response: Any, *, cancelled: Callable[[], bool]) -> Iterator[ResponseDelta]:
        calls = ToolCallAccumulator()
        try:
            for chunk in response:
                if cancelled():
                    return
                if isinstance(chunk, ResponseDelta):
                    yield chunk
                    continue
                choices = _field(chunk, "choices", []) if chunk is not None else []
                if not choices:
                    continue
                delta = _field(choices[0], "delta")
                for call in _field(delta, "tool_calls", []) or []:
                    calls.add(call)
                yield ResponseDelta(
                    content=_field(delta, "content") or "",
                    reasoning=_field(delta, "reasoning_content") or "",
                )
            if calls.finish():
                yield ResponseDelta(tool_calls=calls.finish())
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.debug("Failed to close response stream", exc_info=True)


class AnthropicResponseCodec:
    def decode(self, response: Any) -> ChatResponse:
        if isinstance(response, ChatResponse):
            return response
        result = ChatResponse()
        for block in _field(response, "content", []):
            kind = _field(block, "type")
            if kind == "text":
                result.content += _field(block, "text", "")
            elif kind == "tool_use":
                result.tool_calls.append(_formatted_call(block))
        return result

    def iter_stream(self, response: Any, *, cancelled: Callable[[], bool]) -> Iterator[ResponseDelta]:
        calls: dict[int, dict] = {}
        with response as stream:
            for event in stream:
                if cancelled():
                    return
                kind = _field(event, "type")
                delta = _field(event, "delta")
                block = _field(event, "content_block")
                if kind == "content_block_start" and _field(block, "type") == "tool_use":
                    calls[_field(event, "index")] = {
                        "id": _field(block, "id"), "type": "function",
                        "function": {"name": _field(block, "name"), "arguments": ""},
                    }
                elif kind in {"content_block_delta", "record_delta"}:
                    if _field(delta, "type") == "text_delta":
                        yield ResponseDelta(content=_field(delta, "text", ""))
                    elif _field(delta, "type") == "input_json_delta":
                        calls[_field(event, "index")]["function"]["arguments"] += _field(delta, "partial_json", "")
            if calls:
                yield ResponseDelta(tool_calls=[calls[index] for index in sorted(calls)])


def _extract_tool_call_raw_extras(tc_dict: dict) -> dict:
    """Extract provider-specific fields from a raw tool-call dict that the SDK drops.

    Returns keys ready to merge into the formatted tool call dict.
    Gemini nests thought_signature as ``extra_content.google.thought_signature``,
    and expects it sent back the same way."""
    extras: dict = {}
    ec = tc_dict.get("extra_content")
    if isinstance(ec, str) and ec.strip():
        try:
            import json as _json
            ec = _json.loads(ec)
        except Exception:
            pass
    if isinstance(ec, dict):
        extras["extra_content"] = ec
    return extras

def _tool_call_extras(tc, raw_tc_extra: dict | None = None) -> dict:
    """Extract provider-specific extra fields (e.g. extra_content for Gemini).

    Returns a dict to merge into the formatted call (shallow update)."""
    extras: dict = {}

    if isinstance(tc, dict):
        extras.update(_extract_tool_call_raw_extras(tc))
        if raw_tc_extra:
            extras.update(_extract_tool_call_raw_extras(raw_tc_extra))
        return extras

    # --- object path (OpenAI SDK) ---
    _raw = {}
    try:
        _raw = tc.to_dict() if callable(getattr(tc, "to_dict", None)) else {}
    except Exception:
        pass
    if not _raw:
        try:
            _raw = getattr(tc, "model_extra", None) or {}
        except Exception:
            pass
    if not _raw:
        try:
            _raw = {k: v for k, v in tc.__dict__.items() if not k.startswith("_")}
        except Exception:
            pass
    extras.update(_extract_tool_call_raw_extras(_raw))
    if raw_tc_extra:
        extras.update(_extract_tool_call_raw_extras(raw_tc_extra))
    return extras

def _raw_response_tool_call_extras(response) -> list[dict]:
    """Parse the raw HTTP response body to extract per-tool-call extra fields.

    Returns a list parallel to ``response.choices[0].message.tool_calls``."""
    out: list[dict] = []
    raw_text = ""
    for _meth in ("to_json", "model_dump_json"):
        _fn = getattr(response, _meth, None)
        if callable(_fn):
            try:
                raw_text = _fn()
                if raw_text:
                    break
            except Exception:
                pass
    if not raw_text:
        return out
    try:
        raw_data = json.loads(raw_text)
        for tc in raw_data.get("choices", [{}])[0].get("message", {}).get("tool_calls", []):
            out.append(_extract_tool_call_raw_extras(tc))
        if out and any(e for e in out):
            logger.info(f"_raw_response_tool_call_extras: found extras for {sum(1 for e in out if e)} tool call(s)")
    except Exception as e:
        logger.warning(f"_raw_response_tool_call_extras: failed to parse raw response: {e}")
    return out
