"""Conversation state, history compaction, hooks, and token accounting."""

import copy
import json
from typing import Any, Optional

from sdk.hooks import BeforeChatContext, MessageAddedContext, PluginHookEvent
from sdk.llm_runtime import get_llm_host_runtime


class ManagerStateMixin:
    """Manage mutable message state independently of provider request loops."""

    def cancel_current_chat(self) -> None:
        """Request cancellation and close the adapter's active connection."""
        self._cancel_requested = True
        if self.llm_adapter is not None:
            try:
                self.llm_adapter.cancel()
            except Exception:
                pass

    def _confirm_risky_tool(self, tool_name: str, risk: str, args_str: str) -> bool:
        if risk == "low":
            return True
        try:
            return get_llm_host_runtime().confirm_risky_tool(tool_name, risk, args_str)
        except Exception:
            return risk != "high"

    def set_adapter(self, adapter) -> None:
        self.llm_adapter = adapter
        self.compact_manager.llm_adapter = adapter
        print(f"LLM adapter switched to {type(self.llm_adapter).__name__}.")
        self.messages = []

    def set_user_template(self, template: str) -> None:
        self.messages = [{"role": "system", "content": template}]
        self.user_template = template
        self.llm_adapter.set_user_template(template)

    def add_message(self, role: str, content: Optional[str], **kwargs) -> None:
        if role == "tool":
            content = self._prepare_tool_result_for_history(content)
        message = {"role": role, "content": content}
        message.update(kwargs)
        self.messages.append(message)

        if self._history_file:
            from ai.llm.history_manager import HistoryManager

            HistoryManager.append_message_to_tmp(self._history_file, message)

        if self.hook_dispatcher is not None and self.hook_dispatcher.has_hooks(
            PluginHookEvent.MESSAGE_ADDED
        ):
            self.hook_dispatcher.dispatch_message_added(
                MessageAddedContext(
                    role=role,
                    message=copy.deepcopy(message),
                    messages=copy.deepcopy(self.messages),
                )
            )

        compacted_messages = self.compact_manager.auto_compact_if_needed(self.messages)
        if compacted_messages is not self.messages:
            before_tokens = self.compact_manager.count_tokens(self.messages)
            after_tokens = self.compact_manager.count_tokens(compacted_messages)
            self.logger.info(
                "Auto-compact triggered: messages %s -> %s, tokens %s -> %s",
                len(self.messages),
                len(compacted_messages),
                before_tokens,
                after_tokens,
            )
            self.messages = compacted_messages

    def clear_messages(self) -> None:
        self.messages = [{"role": "system", "content": self.user_template}]

    def _prepare_tool_result_for_history(self, result: Any) -> str:
        if result is None:
            text = json.dumps(
                {"status": "success", "result": "no return value"},
                ensure_ascii=False,
            )
        elif isinstance(result, str):
            text = result
        else:
            text = json.dumps(result, ensure_ascii=False, default=str)

        if len(text) <= self.max_tool_result_chars:
            return text

        head_chars = max(1, self.max_tool_result_chars // 2)
        tail_chars = max(0, self.max_tool_result_chars - head_chars)
        head = text[:head_chars]
        tail = text[-tail_chars:] if tail_chars else ""
        omitted_chars = max(0, len(text) - len(head) - len(tail))
        return json.dumps(
            {
                "truncated": True,
                "original_chars": len(text),
                "omitted_chars": omitted_chars,
                "head": head,
                "tail": tail,
            },
            ensure_ascii=False,
        )

    def _history_load_budget(self) -> int | None:
        if self.max_context_tokens <= 0:
            return None
        threshold_budget = int(
            self.max_context_tokens * self.compact_manager.compact_threshold
        )
        return min(threshold_budget, 50000)

    def _trim_loaded_history_if_needed(self, messages: list[dict]) -> list[dict]:
        budget = self._history_load_budget()
        if budget is None:
            return messages
        if self.compact_manager.count_tokens(messages) <= budget:
            return messages
        return self.compact_manager.trim_messages_to_budget(
            messages,
            token_budget=budget,
            recent_message_limit=self.history_recent_messages,
        )

    def _before_chat_context(
        self,
        *,
        stream: bool,
        tools_defs: list[dict] | None,
        generation_kwargs: dict[str, Any],
    ) -> BeforeChatContext:
        if self.hook_dispatcher is None or not self.hook_dispatcher.has_hooks(
            PluginHookEvent.BEFORE_CHAT
        ):
            return BeforeChatContext(
                messages=self.get_messages(),
                tools=tools_defs,
                generation_kwargs=generation_kwargs,
                stream=stream,
            )

        context = BeforeChatContext(
            messages=copy.deepcopy(self.get_messages()),
            tools=copy.deepcopy(tools_defs) if tools_defs else None,
            generation_kwargs=copy.deepcopy(generation_kwargs),
            stream=stream,
        )
        self.hook_dispatcher.dispatch_before_chat(context)
        return context

    def _estimate_context_tokens(
        self,
        tools_defs: list[dict] | None,
        messages: list[dict] | None = None,
    ) -> dict[str, int]:
        messages = self.get_messages() if messages is None else messages
        system_messages = [
            message for message in messages if message.get("role") == "system"
        ]
        history_messages = [
            message for message in messages if message.get("role") != "system"
        ]
        tool_definition_tokens = 0
        if tools_defs:
            serialized_tools = json.dumps(
                tools_defs,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
            tool_definition_tokens = self.compact_manager.count_text_tokens(
                serialized_tools
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
            get_llm_host_runtime().post_context_token_estimate(estimate)
        except Exception:
            self.logger.debug(
                "Failed to post context token estimate to UI", exc_info=True
            )

    def _persist_plain_assistant_turn(self, content: str, reasoning: str) -> bool:
        if self._cancel_requested:
            return False
        extra = self.llm_adapter.assistant_message_kwargs(reasoning)
        if not (content or "").strip() and not extra:
            return False
        self.add_message("assistant", content or "", **extra)
        return True

    def get_messages(self):
        return self.messages

    def set_messages(self, new_messages: list) -> None:
        if isinstance(new_messages, list):
            self.messages = list(new_messages)
            self._strip_orphaned_tool_calls()
            self.messages = self._trim_loaded_history_if_needed(self.messages)
            self.compact_manager.set_token_count(
                self.compact_manager.count_tokens(self.messages)
            )
            print("Chat history has been updated.")
        else:
            print("Error: new_messages must be a list.")
