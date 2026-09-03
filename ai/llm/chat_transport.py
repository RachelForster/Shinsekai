"""Synchronous and streaming LLM request loops."""

import json
import time
from typing import Generator, Union

from ai.llm.repair import repair_if_needed
from ai.llm.response import create_stream_decoder, decode_response
from core.messaging.stream_events import (
    STREAM_DIALOG_REPAIR_KEY,
    STREAM_REASONING_DELTA_KEY,
)


class ChatTransportMixin:
    """Advance request/response loops using adapter-declared capabilities."""

    def _chat_with_tools_stream(
        self, **kwargs
    ) -> Generator[Union[str, dict[str, str]], None, None]:
        dialog_output_required = bool(kwargs.pop("_dialog_output_required", False))
        tools_defs = self._current_tool_definitions()
        if tools_defs and not self.llm_adapter.supports_streaming_tools:
            yield from self._chat_with_tools_sync(
                _dialog_output_required=dialog_output_required,
                **kwargs,
            )
            return

        merged_kwargs = dict(self.generation_config)
        merged_kwargs.update(kwargs)
        chat_context = self._before_chat_context(
            stream=True,
            tools_defs=tools_defs,
            generation_kwargs=merged_kwargs,
        )
        tools_defs = chat_context.tools or []
        merged_kwargs = chat_context.generation_kwargs
        estimate = self._estimate_context_tokens(tools_defs, chat_context.messages)
        round_index = self._next_llm_round()
        request_started = time.perf_counter()
        self._log_llm_request_started(
            round_index=round_index,
            stream=True,
            tools_defs=tools_defs,
            estimate=estimate,
            message_count=len(chat_context.messages),
        )
        try:
            response_stream, chat_context.messages = (
                self._send_llm_request_with_recovery(
                    messages=chat_context.messages,
                    stream=True,
                    tools_defs=tools_defs,
                    generation_kwargs=merged_kwargs,
                )
            )
        except Exception as exc:
            self._log_llm_request_failed(
                round_index=round_index,
                stream=True,
                started=request_started,
                exc=exc,
            )
            raise
        if response_stream is None:
            self._log_llm_request_completed(
                round_index=round_index,
                stream=True,
                started=request_started,
                outcome="no_response",
            )
            return

        decoder = create_stream_decoder(self.llm_adapter.response_protocol)
        stream_failed = False
        try:
            for delta in decoder.consume(
                response_stream,
                cancelled=lambda: self._cancel_requested,
            ):
                if delta.reasoning:
                    yield {STREAM_REASONING_DELTA_KEY: delta.reasoning}
                if delta.content:
                    yield delta.content
        except Exception as exc:
            if self._cancel_requested:
                decoder.cancelled = True
                return
            stream_failed = True
            self._log_llm_request_failed(
                round_index=round_index,
                stream=True,
                started=request_started,
                exc=exc,
            )
            raise
        finally:
            if not stream_failed:
                normalized = decoder.result()
                outcome = (
                    "cancelled"
                    if decoder.cancelled or self._cancel_requested
                    else "tool_calls" if normalized.tool_calls else "content"
                )
                self._log_llm_request_completed(
                    round_index=round_index,
                    stream=True,
                    started=request_started,
                    outcome=outcome,
                    content_chars=len(normalized.content),
                    reasoning_chars=len(normalized.reasoning),
                    tool_call_count=len(normalized.tool_calls),
                )

        if self._cancel_requested or decoder.cancelled:
            return

        normalized = decoder.result()
        if normalized.tool_calls:
            formatted_calls = [call.as_message() for call in normalized.tool_calls]
            self.add_message(
                "assistant",
                normalized.content,
                tool_calls=formatted_calls,
                **self.llm_adapter.assistant_message_kwargs(normalized.reasoning),
            )
            self._execute_and_record_tool_calls(formatted_calls)

            if self._cancel_requested:
                return
            yield from self._chat_with_tools_stream(
                _dialog_output_required=dialog_output_required,
                **kwargs,
            )
            return

        repair = repair_if_needed(
            required=dialog_output_required,
            adapter=self.llm_adapter,
            content=normalized.content,
            messages=chat_context.messages,
            generation_kwargs=merged_kwargs,
            cancelled=lambda: self._cancel_requested,
            event_logger=self.logger,
        )
        if self._cancel_requested:
            return
        persisted = self._persist_plain_assistant_turn(
            repair.content, normalized.reasoning
        )
        if persisted and repair.repaired:
            yield {STREAM_DIALOG_REPAIR_KEY: repair.content}

    def _chat_with_tools_sync(self, **kwargs) -> str:
        dialog_output_required = bool(kwargs.pop("_dialog_output_required", False))
        tools_defs = self._current_tool_definitions()
        merged_kwargs = dict(self.generation_config)
        merged_kwargs.update(kwargs)
        chat_context = self._before_chat_context(
            stream=False,
            tools_defs=tools_defs,
            generation_kwargs=merged_kwargs,
        )
        tools_defs = chat_context.tools or []
        merged_kwargs = chat_context.generation_kwargs
        estimate = self._estimate_context_tokens(tools_defs, chat_context.messages)
        round_index = self._next_llm_round()
        request_started = time.perf_counter()
        self._log_llm_request_started(
            round_index=round_index,
            stream=False,
            tools_defs=tools_defs,
            estimate=estimate,
            message_count=len(chat_context.messages),
        )
        try:
            response, chat_context.messages = self._send_llm_request_with_recovery(
                messages=chat_context.messages,
                stream=False,
                tools_defs=tools_defs,
                generation_kwargs=merged_kwargs,
            )
        except Exception as exc:
            self._log_llm_request_failed(
                round_index=round_index,
                stream=False,
                started=request_started,
                exc=exc,
            )
            raise
        if not response:
            self._log_llm_request_completed(
                round_index=round_index,
                stream=False,
                started=request_started,
                outcome="no_response",
            )
            return ""
        if self._cancel_requested:
            return ""

        normalized = decode_response(
            self.llm_adapter.response_protocol,
            response,
            logger=self.logger,
        )
        self._log_llm_request_completed(
            round_index=round_index,
            stream=False,
            started=request_started,
            outcome="tool_calls" if normalized.tool_calls else "content",
            content_chars=len(normalized.content),
            reasoning_chars=len(normalized.reasoning),
            tool_call_count=len(normalized.tool_calls),
        )

        if normalized.tool_calls:
            formatted_calls = [call.as_message() for call in normalized.tool_calls]
            self.add_message(
                "assistant",
                normalized.content,
                tool_calls=formatted_calls,
                **self.llm_adapter.assistant_message_kwargs(normalized.reasoning),
            )
            self._execute_and_record_tool_calls(formatted_calls)

            if self._cancel_requested:
                return ""
            return self._chat_with_tools_sync(
                _dialog_output_required=dialog_output_required,
                **kwargs,
            )

        repair = repair_if_needed(
            required=dialog_output_required,
            adapter=self.llm_adapter,
            content=normalized.content,
            messages=chat_context.messages,
            generation_kwargs=merged_kwargs,
            cancelled=lambda: self._cancel_requested,
            event_logger=self.logger,
        )
        if self._cancel_requested:
            return ""
        self._persist_plain_assistant_turn(repair.content, normalized.reasoning)
        return repair.content

    def _execute_and_record_tool_calls(self, formatted_calls: list[dict]) -> None:
        """Execute normalized calls and append each result in protocol order."""
        for call in formatted_calls:
            try:
                function_name, result = self._execute_formatted_tool_call(call)
            except Exception as exc:
                self.logger.error("Tool execution failed: %s", exc)
                result = json.dumps({"error": str(exc)})
                function_name = call["function"]["name"]
            self.add_message(
                "tool",
                result,
                tool_call_id=call["id"],
                name=function_name,
            )
