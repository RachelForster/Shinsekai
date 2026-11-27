"""Provider-independent request, tool and final-response conversation loop."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack

from ai.llm.dialog_repair import repair_dialog_output
from ai.llm.request_runner import RequestRunner, RequestedRound
from ai.llm.template.integrations.localization import LocaleInput
from ai.llm.tool_session import ToolSession
from core.chat_history.identity import CHAT_OUTPUT_FORMAT
from core.messaging.dialog_output import has_valid_dialog_output
from ai.llm.formats import resolve_dialog_format
from core.messaging.stream_events import STREAM_DIALOG_REPAIR_KEY, STREAM_REASONING_DELTA_KEY
from sdk.adapters.dialog_format import DEFAULT_DIALOG_FORMAT_ID
from sdk.adapters.llm import LLMAdapter
from sdk.llm_response import ChatResponse


class ChatLoop:
    def __init__(
        self, adapter: LLMAdapter, tools: ToolSession,
        requests: RequestRunner, *, cancelled: Callable[[], bool],
        append_message: Callable[..., None], generation_config: dict,
        media_selection_mode: str, logger, locale: LocaleInput = None,
        speaker_requires_media: Callable[[str], bool] | None = None,
        bound_speakers: Sequence[str] = (),
        output_format: str = DEFAULT_DIALOG_FORMAT_ID,
    ) -> None:
        self.adapter = adapter
        self.append_message = append_message
        self.tools = tools
        self.requests = requests
        self.cancelled = cancelled
        self.generation_config = generation_config
        self.media_selection_mode = media_selection_mode
        self.logger = logger
        self.locale = locale
        self.speaker_requires_media = speaker_requires_media
        self.bound_speakers: tuple[str, ...] = tuple(bound_speakers)
        self.dialog_format = resolve_dialog_format(output_format)
        self.output_format = self.dialog_format.format_id

    def _request(
        self,
        stream: bool,
        kwargs: dict,
        *,
        dialog_output_required: bool = False,
    ) -> RequestedRound:
        merged = {**self.generation_config, **kwargs}
        if dialog_output_required and "response_format" not in merged:
            if self.dialog_format.api_response_format is not None:
                merged["response_format"] = dict(self.dialog_format.api_response_format)
            elif self.dialog_format.format_id != DEFAULT_DIALOG_FORMAT_ID:
                # OpenAIAdapter defaults omitted response_format to json_object; keep
                # non-JSON custom plugin formats on plain text unless overridden.
                merged["response_format"] = {"type": "text"}
        try:
            return self.requests.request(
                stream=stream,
                generation_kwargs=merged,
                normalize_output_format=dialog_output_required,
            )
        except TypeError:
            return self.requests.request(stream=stream, generation_kwargs=merged)

    def _persist_assistant(
        self,
        response: ChatResponse,
        *,
        dialog_output_required: bool = False,
    ) -> bool:
        if self.cancelled():
            return False
        metadata = dict(self.adapter.assistant_message_metadata(response.reasoning) or {})
        if not response.content.strip() and not metadata:
            return False
        if dialog_output_required and response.content.strip():
            metadata[CHAT_OUTPUT_FORMAT] = self.output_format
        self.append_message("assistant", response.content, **metadata)
        return True

    def _execute_tools(self, response: ChatResponse) -> None:
        if not self.tools.tools_enabled:
            raise ValueError("Unexpected tool call in a dialog-only workflow")
        self.append_message(
            "assistant", response.content, tool_calls=response.tool_calls,
            **self.adapter.assistant_message_metadata(response.reasoning),
        )
        for call in response.tool_calls:
            try:
                name, result = self.tools._execute_formatted_tool_call(call)
            except Exception as exc:
                self.logger.error("Tool execution failed: %s", exc)
                name = call["function"]["name"]
                result = json.dumps({"error": str(exc)})
            self.append_message("tool", result, tool_call_id=call["id"], name=name)

    def _repair(self, response: ChatResponse, request: RequestedRound) -> None:
        response.content = repair_dialog_output(
            self.adapter, response.content, request.context.messages,
            request.context.generation_kwargs, cancelled=self.cancelled,
            event_logger=self.logger, media_selection_mode=self.media_selection_mode,
            speaker_requires_media=self.speaker_requires_media,
            bound_speakers=self.bound_speakers,
            output_format_id=self.output_format, locale=self.locale,
        )

    def sync(self, *, dialog_output_required: bool = False, **kwargs) -> str:
        while True:
            request = self._request(
                False,
                kwargs,
                dialog_output_required=dialog_output_required,
            )
            if not request.response:
                self.requests.complete(request, outcome="no_response")
                return ""
            if self.cancelled():
                return ""
            response = self.adapter.decode_response(request.response)
            self.requests.complete(
                request, outcome="tool_calls" if response.tool_calls else "content",
                content_chars=len(response.content), reasoning_chars=len(response.reasoning),
                tool_call_count=len(response.tool_calls),
            )
            if response.tool_calls:
                self._execute_tools(response)
                if self.cancelled():
                    return ""
                continue
            if dialog_output_required:
                self._repair(response, request)
            if self.cancelled():
                return ""
            self._persist_assistant(
                response,
                dialog_output_required=dialog_output_required,
            )
            return response.content

    def stream(self, *, dialog_output_required: bool = False, **kwargs) -> Iterator[str | dict[str, str]]:
        while True:
            if self.tools._current_tool_definitions() and not self.adapter.supports_streaming_tools:
                # Preserve the public stream contract while retaining provider metadata.
                yield from self.sync(dialog_output_required=dialog_output_required, **kwargs)
                return
            request = self._request(
                True,
                kwargs,
                dialog_output_required=dialog_output_required,
            )
            if request.response is None:
                self.requests.complete(request, outcome="no_response")
                return
            response = ChatResponse()
            failed = False
            try:
                with ExitStack() as stack:
                    deltas = self.adapter.iter_response_stream(request.response, cancelled=self.cancelled)
                    close = getattr(deltas, "close", None)
                    if callable(close):
                        stack.callback(close)
                    for delta in deltas:
                        if self.cancelled():
                            break
                        response.tool_calls.extend(delta.tool_calls)
                        if delta.reasoning:
                            response.reasoning += delta.reasoning
                            yield {STREAM_REASONING_DELTA_KEY: delta.reasoning}
                        if delta.content:
                            response.content += delta.content
                            yield delta.content
            except Exception as exc:
                if self.cancelled():
                    return
                failed = True
                self.requests.fail(request, exc)
                raise
            finally:
                if not failed:
                    self.requests.complete(
                        request, outcome="cancelled" if self.cancelled() else (
                            "tool_calls" if response.tool_calls else "content"
                        ),
                        content_chars=len(response.content), reasoning_chars=len(response.reasoning),
                        tool_call_count=len(response.tool_calls),
                    )
            if self.cancelled():
                return
            if response.tool_calls:
                self._execute_tools(response)
                if self.cancelled():
                    return
                continue
            needs_repair = dialog_output_required and not has_valid_dialog_output(
                response.content,
                media_selection_mode=self.media_selection_mode,
                speaker_requires_media=self.speaker_requires_media,
                format_id=self.output_format,
            )
            if needs_repair:
                self._repair(response, request)
            if self.cancelled():
                return
            persisted = self._persist_assistant(
                response,
                dialog_output_required=dialog_output_required,
            )
            if persisted and needs_repair and has_valid_dialog_output(
                response.content,
                media_selection_mode=self.media_selection_mode,
                speaker_requires_media=self.speaker_requires_media,
                format_id=self.output_format,
            ):
                yield {STREAM_DIALOG_REPAIR_KEY: response.content}
            return
