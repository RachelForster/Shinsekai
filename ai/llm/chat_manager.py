"""Top-level chat orchestration and request lifecycle handling."""

import copy
import time
from typing import Any, Generator, Optional, Union

from ai.llm.chat_types import ChatTurnState, prefix_user_text_with_local_time
from ai.llm.message_sanitizer import (
    filter_unpaired_tool_messages_for_request,
    strip_orphaned_tool_calls,
)
from sdk.exception.types import HTTP_REASON_UNPAIRED_TOOL_MESSAGES, classify_exception


class ChatManagerMixin:
    """Coordinate one logical chat turn across recursive tool-call rounds."""

    def _has_conversation_history(self) -> bool:
        return any(message.get("role") != "system" for message in self.messages)

    def _begin_chat_turn(self, *, first_user_turn: bool) -> None:
        self._turn_state = ChatTurnState(
            started_at=time.perf_counter(),
            first_user_turn=first_user_turn,
            first_turn_tool_call_limit=self.first_turn_tool_call_limit,
        )
        self.logger.info(
            "Chat turn profile started",
            extra={
                "event": "chat.turn.profile.started",
                "first_user_turn": first_user_turn,
                "first_turn_tool_call_limit": self.first_turn_tool_call_limit,
            },
        )

    def _next_llm_round(self) -> int:
        if self._turn_state is None:
            return 1
        self._turn_state.llm_rounds += 1
        return self._turn_state.llm_rounds

    def _adapter_profile(self) -> dict[str, str]:
        return {
            "adapter": type(self.llm_adapter).__name__,
            "model": str(getattr(self.llm_adapter, "model", "") or ""),
        }

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
                "message_count": (
                    len(self.get_messages()) if message_count is None else message_count
                ),
                "active_tool_groups": list(self._active_tool_groups),
                "tool_count": len(tools_defs or []),
                "tool_names": [
                    str(definition.get("function", {}).get("name") or "")
                    for definition in (tools_defs or [])
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

    def _finish_chat_scope(self) -> None:
        self._chat_depth = max(0, self._chat_depth - 1)
        if self._chat_depth != 0:
            return

        state = self._turn_state
        if state is not None:
            self.logger.info(
                "Chat turn profile completed",
                extra={
                    "event": "chat.turn.profile.completed",
                    "duration_ms": round(
                        (time.perf_counter() - state.started_at) * 1000, 2
                    ),
                    "first_user_turn": state.first_user_turn,
                    "llm_rounds": state.llm_rounds,
                    "tool_call_attempts": state.tool_call_attempts,
                    "tool_calls_executed": state.tool_calls_executed,
                    "tool_calls_skipped": state.tool_calls_skipped,
                    "tool_failures": dict(state.tool_failures),
                },
            )
        self._turn_state = None
        self._reset_active_tool_groups()

    def _stream_with_chat_scope(
        self, stream: Generator[Union[str, dict[str, str]], None, None]
    ):
        try:
            yield from stream
        finally:
            self._finish_chat_scope()

    def chat(
        self,
        user_input: Optional[Any],
        stream: bool = True,
        dialog_output_required: bool = False,
        **kwargs,
    ) -> Union[Generator, str]:
        """Run a chat turn using either the streaming or synchronous transport."""
        outer_chat = self._chat_depth == 0
        first_user_turn = (
            outer_chat
            and user_input is not None
            and not self._has_conversation_history()
        )
        if outer_chat:
            self._begin_chat_turn(first_user_turn=first_user_turn)
        self._chat_depth += 1
        self._cancel_requested = False
        self._strip_orphaned_tool_calls()

        try:
            include_local_time = bool(kwargs.pop("include_local_time", True))
            user_display_text = str(kwargs.pop("user_display_text", "") or "").strip()
            user_input_text = kwargs.pop("user_input_text", None)
            user_attachments = kwargs.pop("user_attachments", None)
            requested_tool_groups = kwargs.pop("tool_groups", ())
            if isinstance(requested_tool_groups, str):
                requested_tool_groups = (requested_tool_groups,)
            for group in requested_tool_groups:
                self._activate_tool_group(str(group or "").strip())
            if user_input:
                if include_local_time:
                    user_input = prefix_user_text_with_local_time(user_input)
                user_metadata: dict[str, Any] = {}
                if user_display_text:
                    user_metadata["display_content"] = user_display_text
                if user_input_text is not None:
                    user_metadata["input_text"] = str(user_input_text or "")
                if isinstance(user_attachments, list):
                    user_metadata["attachments"] = copy.deepcopy(user_attachments)
                self.add_message("user", user_input, **user_metadata)

            if stream:
                return self._stream_with_chat_scope(
                    self._chat_with_tools_stream(
                        _dialog_output_required=dialog_output_required,
                        **kwargs,
                    )
                )
            return self._chat_with_tools_sync(
                _dialog_output_required=dialog_output_required,
                **kwargs,
            )
        finally:
            if not stream:
                self._finish_chat_scope()

    def _strip_orphaned_tool_calls(self) -> None:
        strip_orphaned_tool_calls(self.get_messages())

    def _recover_request_tool_pairs(
        self, exc: Exception, messages: list[dict]
    ) -> list[dict] | None:
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
