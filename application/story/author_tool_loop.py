"""Bounded, stateless tool conversations for the story compiler author."""

from __future__ import annotations

from collections.abc import Callable
import copy
import json
from typing import Any

from ai.tools.call_protocol import read_tool_reply
from ai.tools.random_tools import execute_random_tool, random_tool_definitions
from application.random_requests import RandomRequestExecutor
from core.randomness import RandomRequestError

MAX_AUTHOR_ROUNDS = 8
MAX_AUTHOR_TOOL_CALLS = 24
MAX_TOOL_ARGUMENT_CHARS = 32_000

AUTHOR_RANDOM_TOOL_PROMPT = (
    "You may call the supplied random tools to sample, shuffle, roll dice, or assign labels. "
    "Use their actual results instead of inventing random outcomes. Give each decision a stable "
    "requestId and reuse identical arguments when retrying or repairing the same decision. "
    "resolvedRandomRequests contains previously committed decisions for this task; treat those "
    "results as authoritative and do not use a new requestId to reroll an existing decision. "
    "Tool results here belong to AUTHORING: any outcomes written into the artifact become fixed "
    "story facts. They are NOT new-game identity assignments. Per-session execution is not enabled "
    "yet; do not claim that these results will be rerolled at game start or invent executable triggers. "
    "Keep secrets only in the fields permitted by the stage schema. After tool use return exactly "
    "the requested JSON artifact, without tool transcripts, seeds, or extra protocol fields."
)


class AuthorToolLoopError(RuntimeError):
    code = "generation.tool_loop_failed"


def run_author_tool_loop(
    adapter: Any,
    messages: list[dict[str, Any]],
    *,
    executor: RandomRequestExecutor,
    before_call: Callable[[], None] = lambda: None,
    on_call: Callable[[list[dict[str, Any]], Any], None] = lambda messages,
    response: None,
    native_json: bool = False,
) -> Any:
    conversation = copy.deepcopy(messages)
    used_calls = 0
    for round_index in range(MAX_AUTHOR_ROUNDS):
        before_call()
        # Give the model one final response-only turn when the budget is used.
        allow_tools = (
            round_index < MAX_AUTHOR_ROUNDS - 1 and used_calls < MAX_AUTHOR_TOOL_CALLS
        )
        kwargs = {"tools": random_tool_definitions()} if allow_tools else {}
        if not allow_tools and native_json:
            kwargs["response_format"] = {"type": "json_object"}
        recorded_response: Any = None
        try:
            response = adapter.chat(conversation, stream=False, **kwargs)
            content, assistant = read_tool_reply(response)
            recorded_response = assistant if assistant is not None else content
        finally:
            on_call(conversation, recorded_response)
        if assistant is None:
            return content
        calls = assistant["tool_calls"]
        if not allow_tools or used_calls + len(calls) > MAX_AUTHOR_TOOL_CALLS:
            raise AuthorToolLoopError("story author exceeded its random tool budget")
        conversation.append(assistant)
        for call in calls:
            before_call()
            used_calls += 1
            function = call["function"]
            try:
                raw = function["arguments"]
                if len(raw) > MAX_TOOL_ARGUMENT_CHARS:
                    raise RandomRequestError("tool arguments are too large")
                arguments = json.loads(raw)
                result = {
                    "ok": True,
                    "result": execute_random_tool(
                        function["name"],
                        arguments,
                        execute=executor.execute,
                    ),
                }
            except (RandomRequestError, json.JSONDecodeError) as error:
                result = {"ok": False, "error": str(error)}
            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": function["name"],
                    "content": json.dumps(result, ensure_ascii=False, allow_nan=False),
                }
            )
    raise AuthorToolLoopError("story author did not finish within the tool loop")
