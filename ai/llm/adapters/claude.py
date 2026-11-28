"""Anthropic Claude LLM adapter."""

from __future__ import annotations

import json
from typing import Any

from ai.llm.adapters.common import (
    CLAUDE_CHAT_PARAMS,
    close_active_stream,
    filter_adapter_chat_params,
    raise_if_http_client_error,
)
from ai.llm.claude_url import normalize_claude_base_url_for_sdk
from ai.vision.message_content import normalize_anthropic_user_content
from core.adapters import builtin_adapter
from sdk.adapters import LLMAdapter
from sdk.llm_response import AnthropicResponseCodec
from sdk.logging import get_logger

logger = get_logger(__name__)


@builtin_adapter("Claude", label="Claude", order=40)
class ClaudeAdapter(LLMAdapter):
    """Adapter for the Anthropic Messages API."""

    supported_chat_params = CLAUDE_CHAT_PARAMS

    @property
    def response_codec(self) -> AnthropicResponseCodec:
        return AnthropicResponseCodec()

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "claude-3-5-sonnet-20240620",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        import anthropic

        self.client = anthropic.Anthropic(
            api_key=api_key,
            base_url=normalize_claude_base_url_for_sdk(base_url),
        )
        self.model = model
        self.system_prompt = ""

    def cancel(self) -> None:
        """Close the active Claude stream/response to abort an in-flight request."""
        close_active_stream(self)

    @property
    def supports_native_vision(self) -> bool:
        return True

    def set_user_template(self, template: str) -> None:
        self.system_prompt = template

    def _clean_messages(self, messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        """Normalize conversation messages to conform to Anthropic Messages API rules."""
        api_messages: list[dict[str, Any]] = []
        system_parts = [self.system_prompt] if self.system_prompt else []

        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if content:
                    system_parts.append(content)
        system_content = "\n\n".join(system_parts)

        raw_msgs = [m for m in messages if m.get("role") != "system"]
        for msg in raw_msgs:
            role = msg.get("role")
            content = msg.get("content") or ""

            if role == "assistant":
                anthropic_content: list[dict[str, Any]] = []
                if isinstance(content, str) and content.strip():
                    anthropic_content.append({"type": "text", "text": content})
                elif content and not isinstance(content, str):
                    anthropic_content.append({"type": "text", "text": str(content)})

                for tc in msg.get("tool_calls") or []:
                    if "function" in tc:
                        raw_args = tc.get("function", {}).get("arguments")
                        name = tc.get("function", {}).get("name")
                    else:
                        raw_args = tc.get("input")
                        name = tc.get("name")
                    if isinstance(raw_args, str):
                        try:
                            parsed_args = json.loads(raw_args)
                        except (ValueError, TypeError):
                            parsed_args = {}
                    else:
                        parsed_args = raw_args

                    anthropic_content.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id"),
                            "name": name,
                            "input": parsed_args,
                        }
                    )

                # Anthropic rejects empty assistant content blocks.
                if not anthropic_content:
                    anthropic_content.append({"type": "text", "text": "..."})

                api_messages.append({"role": "assistant", "content": anthropic_content})

            elif role == "user":
                user_content = normalize_anthropic_user_content(content)
                if user_content:
                    api_messages.append({"role": "user", "content": user_content})

            elif role == "tool":
                api_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_call_id"),
                                "content": str(content) if content else "Success",
                            }
                        ],
                    }
                )

        # Merge consecutive same-role messages as required by Anthropic API.
        final_msgs: list[dict[str, Any]] = []
        for message in api_messages:
            if final_msgs and final_msgs[-1]["role"] == message["role"]:
                prev_content = final_msgs[-1]["content"]
                curr_content = message["content"]
                if isinstance(prev_content, str) and isinstance(curr_content, str):
                    final_msgs[-1]["content"] = f"{prev_content}\n{curr_content}"
                else:
                    if isinstance(prev_content, str):
                        final_msgs[-1]["content"] = [{"type": "text", "text": prev_content}]
                    if isinstance(curr_content, str):
                        curr_content = [{"type": "text", "text": curr_content}]
                    final_msgs[-1]["content"].extend(curr_content)
            else:
                final_msgs.append(message)

        return system_content, final_msgs

    def chat(
        self,
        messages: list[dict[str, Any]],
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Send a messages request to Anthropic Claude."""
        try:
            filtered = filter_adapter_chat_params(self, kwargs)
            system_msg, cleaned_msgs = self._clean_messages(messages)

            if not cleaned_msgs:
                cleaned_msgs = [{"role": "user", "content": "Hello"}]

            logger.debug("Claude cleaned messages count=%d", len(cleaned_msgs))
            tools = filtered.get("tools")
            anthropic_tools: list[dict[str, Any]] = []
            if tools:
                for tool_def in tools:
                    fn = tool_def.get("function", tool_def)
                    anthropic_tools.append(
                        {
                            "name": fn["name"],
                            "description": fn.get("description", ""),
                            "input_schema": fn["parameters"],
                        }
                    )

            request_kwargs: dict[str, Any] = {
                "model": self.model,
                "system": system_msg,
                "messages": cleaned_msgs,
                "tools": anthropic_tools if anthropic_tools else None,
                "max_tokens": filtered.get("max_tokens", 4096),
                "temperature": filtered.get("temperature", 0.7),
            }
            if stream:
                stream_obj = self.client.messages.stream(**request_kwargs)
                self._current_stream = stream_obj
                return stream_obj
            resp = self.client.messages.create(**request_kwargs)
            self._current_response = resp
            return resp
        except Exception as exc:
            raise_if_http_client_error(exc)
            logger.error("Claude API Error: %s", exc)
            return None
