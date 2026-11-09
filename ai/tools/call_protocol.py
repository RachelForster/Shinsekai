"""Normalize non-streaming adapter replies for scoped tool conversations."""

from __future__ import annotations

from collections.abc import Mapping
import copy
import json
from typing import Any


def _field(value: Any, key: str, default: Any = None) -> Any:
    return (
        value.get(key, default)
        if isinstance(value, Mapping)
        else getattr(value, key, default)
    )


def _tool_call(call: Any) -> dict[str, Any]:
    # Preserve provider extensions such as Gemini thought signatures.
    if isinstance(call, Mapping):
        result = copy.deepcopy(dict(call))
    elif callable(getattr(call, "model_dump", None)):
        result = call.model_dump(exclude_none=True)
    elif _field(call, "type") == "tool_use":
        result = {
            "id": _field(call, "id"),
            "type": "tool_use",
            "name": _field(call, "name"),
            "input": _field(call, "input", {}),
        }
    else:
        function = _field(call, "function")
        result = {
            "id": _field(call, "id"),
            "type": "function",
            "function": {
                "name": _field(function, "name"),
                "arguments": _field(function, "arguments"),
            },
        }
    if result.get("type") == "tool_use":
        result = {
            "id": result.get("id"),
            "type": "function",
            "function": {
                "name": result.get("name"),
                "arguments": result.get("input", {}),
            },
        }
    function = result.get("function")
    if (
        not isinstance(result.get("id"), str)
        or not result["id"]
        or not isinstance(function, dict)
    ):
        raise ValueError("tool reply is missing its call ID or function")
    if not isinstance(function.get("name"), str) or not function["name"]:
        raise ValueError("tool reply is missing its function name")
    if isinstance(function.get("arguments"), Mapping):
        function["arguments"] = json.dumps(function["arguments"], ensure_ascii=False)
    if not isinstance(function.get("arguments"), str):
        raise ValueError("tool arguments must be a JSON string or object")
    return result


def read_tool_reply(response: Any) -> tuple[Any, dict[str, Any] | None]:
    """Return final content, or the assistant message to echo before tool results."""
    choices = _field(response, "choices")
    if choices:
        message = _field(choices[0], "message")
        content = _field(message, "content") or ""
        calls = _field(message, "tool_calls") or []
        reasoning = _field(message, "reasoning_content")
    else:
        content = _field(response, "content")
        calls = []
        reasoning = None
        if isinstance(content, list):
            calls = [block for block in content if _field(block, "type") == "tool_use"]
            content = "".join(
                str(_field(block, "text", ""))
                for block in content
                if _field(block, "type") == "text"
            )
        elif content is None:
            content = _field(response, "text", response)
    if not calls:
        return content, None
    assistant = {
        "role": "assistant",
        "content": content,
        "tool_calls": [_tool_call(call) for call in calls],
    }
    if isinstance(reasoning, str):
        assistant["reasoning_content"] = reasoning
    return content, assistant
