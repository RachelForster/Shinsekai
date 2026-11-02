"""Build request snapshots, recover malformed tool pairs and report request metrics."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from ai.llm.conversation_history import ConversationHistory
from ai.llm.message_sanitizer import filter_unpaired_tool_messages_for_request
from ai.llm.tool_session import ToolSession
from sdk.adapters.llm import LLMAdapter
from sdk.exception.types import HTTP_REASON_UNPAIRED_TOOL_MESSAGES, classify_exception
from sdk.hooks import BeforeChatContext


@dataclass
class RequestedRound:
    response: Any
    context: BeforeChatContext
    index: int
    started: float
    stream: bool


class RequestRunner:
    def __init__(self, adapter: LLMAdapter, history: ConversationHistory, tools: ToolSession, *, host, logger) -> None:
        self.llm_adapter = adapter
        self.history = history
        self.tools = tools
        self.host = host
        self.logger = logger
        self.last_token_estimate = {
            "system_prompt_tokens": 0, "history_tokens": 0,
            "tool_definition_tokens": 0, "estimated_total_tokens": 0,
        }

    @property
    def compact_manager(self):
        return self.history.compact_manager

    @property
    def _active_tool_groups(self):
        return self.tools._active_tool_groups

    def get_messages(self):
        return self.history.get_messages()

    def request(self, *, stream: bool, generation_kwargs: dict) -> RequestedRound:
        context = self.history._before_chat_context(
            stream=stream, tools_defs=self.tools._current_tool_definitions(),
            generation_kwargs=generation_kwargs,
        )
        definitions = context.tools or []
        estimate = self._estimate_context_tokens(definitions, context.messages)
        index = self.tools._next_llm_round()
        started = time.perf_counter()
        self._log_llm_request_started(
            round_index=index, stream=stream, tools_defs=definitions,
            estimate=estimate, message_count=len(context.messages),
        )
        try:
            response, context.messages = self._send_llm_request_with_recovery(
                messages=context.messages, stream=stream, tools_defs=definitions,
                generation_kwargs=context.generation_kwargs,
            )
        except Exception as exc:
            self._log_llm_request_failed(round_index=index, stream=stream, started=started, exc=exc)
            raise
        return RequestedRound(response, context, index, started, stream)

    def complete(self, request: RequestedRound, *, outcome: str, content_chars: int = 0, reasoning_chars: int = 0, tool_call_count: int = 0) -> None:
        self._log_llm_request_completed(
            round_index=request.index, stream=request.stream, started=request.started,
            outcome=outcome, content_chars=content_chars, reasoning_chars=reasoning_chars,
            tool_call_count=tool_call_count,
        )

    def fail(self, request: RequestedRound, exc: Exception) -> None:
        self._log_llm_request_failed(round_index=request.index, stream=request.stream, started=request.started, exc=exc)

    def _adapter_profile(self) -> dict[str, str]:
        return {
            "adapter": type(self.llm_adapter).__name__,
            "model": str(getattr(self.llm_adapter, "model", "") or ""),
        }

    def _estimate_context_tokens(
        self,
        tools_defs: list[dict] | None,
        messages: list[dict] | None = None,
    ) -> dict[str, int]:
        messages = self.get_messages() if messages is None else messages
        system_messages = [m for m in messages if m.get("role") == "system"]
        history_messages = [m for m in messages if m.get("role") != "system"]
        tool_definition_tokens = 0
        if tools_defs:
            tool_definition_tokens = self.compact_manager.count_text_tokens(
                json.dumps(tools_defs, ensure_ascii=False, separators=(",", ":"), default=str)
            )
        estimate = {
            "system_prompt_tokens": self.compact_manager.count_tokens(system_messages),
            "history_tokens": self.compact_manager.count_tokens(history_messages),
            "tool_definition_tokens": tool_definition_tokens,
        }
        estimate["estimated_total_tokens"] = sum(estimate.values())
        self.last_token_estimate = estimate
        self.logger.info(
            "Context token estimate: system=%s history=%s tools=%s total=%s",
            estimate["system_prompt_tokens"],
            estimate["history_tokens"],
            estimate["tool_definition_tokens"],
            estimate["estimated_total_tokens"],
        )
        self._post_context_token_estimate(estimate)
        return estimate

    def get_context_token_estimate(self) -> dict[str, int]:
        return dict(self.last_token_estimate)

    def _post_context_token_estimate(self, estimate: dict[str, int]) -> None:
        try:
            self.host().post_context_token_estimate(estimate)
        except Exception:
            self.logger.debug("Failed to post context token estimate to UI", exc_info=True)

    def _log_llm_request_started(
        self,
        *,
        round_index: int,
        stream: bool,
        tools_defs: list[dict],
        estimate: dict[str, int],
        message_count: int | None = None,
    ) -> None:
        self.logger.info(
            "LLM request started",
            extra={
                "event": "llm.request.started",
                "llm_round": round_index,
                "stream": stream,
                "message_count": len(self.get_messages()) if message_count is None else message_count,
                "active_tool_groups": list(self._active_tool_groups),
                "tool_count": len(tools_defs or []),
                "tool_names": [
                    str(d.get("function", {}).get("name") or "")
                    for d in (tools_defs or [])
                ],
                **self._adapter_profile(),
                **estimate,
            },
        )

    def _log_llm_request_completed(
        self,
        *,
        round_index: int,
        stream: bool,
        started: float,
        outcome: str,
        content_chars: int = 0,
        reasoning_chars: int = 0,
        tool_call_count: int = 0,
    ) -> None:
        self.logger.info(
            "LLM request completed",
            extra={
                "event": "llm.request.completed",
                "llm_round": round_index,
                "stream": stream,
                "outcome": outcome,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "content_chars": content_chars,
                "reasoning_chars": reasoning_chars,
                "tool_call_count": tool_call_count,
                **self._adapter_profile(),
            },
        )

    def _log_llm_request_failed(
        self,
        *,
        round_index: int,
        stream: bool,
        started: float,
        exc: Exception,
    ) -> None:
        self.logger.exception(
            "LLM request failed",
            extra={
                "event": "llm.request.failed",
                "llm_round": round_index,
                "stream": stream,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error_type": type(exc).__name__,
                **self._adapter_profile(),
            },
        )

    def _recover_request_tool_pairs(self, exc: Exception, messages: list[dict]) -> list[dict] | None:
        error_info = classify_exception(exc)
        if (
            not error_info
            or error_info.get("kind") != "http_client"
            or error_info.get("reason") != HTTP_REASON_UNPAIRED_TOOL_MESSAGES
        ):
            return None
        filtered = filter_unpaired_tool_messages_for_request(messages)
        if filtered is messages:
            return None
        self.logger.warning(
            "Recovering LLM request by filtering unpaired tool messages",
            extra={
                "event": "llm.request.tool_pairs.recovered",
                "before_count": len(messages),
                "after_count": len(filtered),
                "error_type": type(exc).__name__,
            },
        )
        return filtered

    def _send_llm_request_with_recovery(
        self,
        *,
        messages: list[dict],
        stream: bool,
        tools_defs: list[dict],
        generation_kwargs: dict[str, Any],
    ) -> tuple[Any, list[dict]]:
        try:
            response = self.llm_adapter.chat(
                messages=messages,
                stream=stream,
                tools=tools_defs if tools_defs else None,
                **generation_kwargs,
            )
            return response, messages
        except Exception as exc:
            recovered_messages = self._recover_request_tool_pairs(exc, messages)
            if recovered_messages is None:
                raise
            response = self.llm_adapter.chat(
                messages=recovered_messages,
                stream=stream,
                tools=tools_defs if tools_defs else None,
                **generation_kwargs,
            )
            return response, recovered_messages
