"""Conversation history, prompt snapshots, compaction and message persistence."""

from __future__ import annotations

import copy
import json
from typing import Any, Optional

from ai.llm.message_sanitizer import strip_orphaned_tool_calls
from ai.llm.ports import HistoryCompactor, MessageJournal
from sdk.hooks import BeforeChatContext, MessageAddedContext, PluginHookDispatcher, PluginHookEvent


class ConversationHistory:
    def __init__(
        self, *, compact_manager: HistoryCompactor, journal: MessageJournal,
        user_template: str, max_context_tokens: int, history_recent_messages: int,
        max_tool_result_chars: int, hook_dispatcher: PluginHookDispatcher | None,
        use_current_template_for_history: bool, logger,
    ) -> None:
        self.compact_manager = compact_manager
        self.journal = journal
        self.user_template = user_template
        self.max_context_tokens = max_context_tokens
        self.history_recent_messages = history_recent_messages
        self.max_tool_result_chars = max_tool_result_chars
        self.hook_dispatcher = hook_dispatcher
        self.use_current_template_for_history = use_current_template_for_history
        self.logger = logger
        self.messages: list[dict] = []

    def set_user_template(self, template: str):
        """Sets the system prompt/user template and resets the messages list."""
        self.messages = [{"role": "system", "content": template}]
        self.user_template = template

    def add_message(self, role: str, content: Optional[str], **kwargs):
        """
        通用消息添加方法。
        集成了 Auto-Compact 逻辑：每当消息增加，自动检查并压缩。
        """
        if role == "tool":
            content = self._prepare_tool_result_for_history(content)
        msg = {"role": role, "content": content}
        msg.update(kwargs)
        self.messages.append(msg)

        self.journal.append(msg)

        if (
            self.hook_dispatcher is not None
            and self.hook_dispatcher.has_hooks(PluginHookEvent.MESSAGE_ADDED)
        ):
            self.hook_dispatcher.dispatch_message_added(
                MessageAddedContext(
                    role=role,
                    message=copy.deepcopy(msg),
                    messages=copy.deepcopy(self.messages),
                )
            )

        # --- Auto-Compact 逻辑 ---
        # 自动调用 compact_manager 检查 token 是否超限并执行压缩
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

    def clear_messages(self):
        self.messages = [{"role": "system", "content": self.user_template}]

    def _prepare_tool_result_for_history(self, result: Any) -> str:
        """Bound tool output before it becomes permanent prompt history."""
        if result is None:
            text = json.dumps({"status": "success", "result": "no return value"}, ensure_ascii=False)
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
        threshold_budget = int(self.max_context_tokens * self.compact_manager.compact_threshold)
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
        if (
            self.hook_dispatcher is None
            or not self.hook_dispatcher.has_hooks(PluginHookEvent.BEFORE_CHAT)
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

    def get_messages(self):
        """Returns the current list of messages."""
        return self.messages

    def set_messages(self, new_messages: list):
        """Sets the conversation history to a new list of messages."""
        if isinstance(new_messages, list):
            self.messages = list(new_messages)
            if getattr(self, "use_current_template_for_history", False):
                if self.messages and self.messages[0].get("role") == "system":
                    self.messages[0] = {**self.messages[0], "content": self.user_template}
                else:
                    self.messages.insert(0, {"role": "system", "content": self.user_template})
            self._strip_orphaned_tool_calls()
            self.messages = self._trim_loaded_history_if_needed(self.messages)
            self.compact_manager.set_token_count(self.compact_manager.count_tokens(self.messages))
            print("Chat history has been updated.")
        else:
            print("Error: new_messages must be a list.")

    def _strip_orphaned_tool_calls(self) -> None:
        """清理不完整的 tool call 对：删孤立的 tool，补缺失的回执。"""
        strip_orphaned_tool_calls(self.get_messages())
