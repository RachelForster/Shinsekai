"""Conversation history, prompt snapshots, compaction and message persistence."""

from __future__ import annotations

from collections.abc import Mapping
import copy
import json
from typing import Any, Optional

from ai.llm.message_sanitizer import strip_orphaned_tool_calls
from ai.llm.ports import HistoryCompactor, MessageJournal
from core.chat_history.models import (
    COMPACT_UP_TO_SEQ_KEY,
    build_compact_summary_message,
    is_compact_summary_message,
    strip_internal_message_keys,
)
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
        self._seq_by_msg_id: dict[int, int] = {}
        self._bind_compactor_session_hooks()

    def _journal_session_id(self) -> str:
        return str(getattr(self.journal, "session_id", "") or "").strip()

    def _journal_branch_id(self) -> str:
        return str(getattr(self.journal, "active_branch_id", "main") or "main").strip() or "main"

    def _journal_session_store(self) -> Any | None:
        return getattr(self.journal, "session_store", None)

    def _bind_compactor_session_hooks(self) -> None:
        if (
            hasattr(self.compact_manager, "resolve_message_seq")
            and getattr(self.compact_manager, "resolve_message_seq", None) is None
        ):
            self.compact_manager.resolve_message_seq = self.resolve_message_seq
        if (
            hasattr(self.compact_manager, "on_checkpoint")
            and getattr(self.compact_manager, "on_checkpoint", None) is None
        ):
            self.compact_manager.on_checkpoint = self._record_compact_checkpoint
        sid = self._journal_session_id()
        if (
            sid
            and hasattr(self.compact_manager, "session_id")
            and not getattr(self.compact_manager, "session_id", "")
        ):
            self.compact_manager.session_id = sid

    def resolve_message_seq(self, message: Mapping[str, Any]) -> int | None:
        mapped = self._seq_by_msg_id.get(id(message))
        if mapped is not None:
            return mapped
        for key in ("_turn_seq", COMPACT_UP_TO_SEQ_KEY):
            raw = message.get(key)
            if raw is not None:
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    pass
        return None

    def _record_compact_checkpoint(self, up_to_seq: int, rolling_summary: str) -> None:
        store = self._journal_session_store()
        if store is None or up_to_seq <= 0 or not str(rolling_summary or "").strip():
            return
        store.add_compact_checkpoint(
            up_to_seq=int(up_to_seq),
            rolling_summary=str(rolling_summary),
            branch_id=self._journal_branch_id(),
        )

    def _prune_seq_index(self) -> None:
        live_ids = {id(m) for m in self.messages}
        self._seq_by_msg_id = {
            mid: seq for mid, seq in self._seq_by_msg_id.items() if mid in live_ids
        }

    def _rebind_seq_index_from_store(self) -> None:
        self._seq_by_msg_id.clear()
        store = self._journal_session_store()
        if store is None:
            return
        branch_id = self._journal_branch_id()
        after_seq = 0
        body_msgs: list[dict[str, Any]] = []
        for msg in self.messages:
            if not isinstance(msg, dict) or msg.get("role") == "system":
                continue
            if is_compact_summary_message(msg):
                raw_anchor = msg.get(COMPACT_UP_TO_SEQ_KEY)
                if raw_anchor is not None:
                    try:
                        after_seq = max(after_seq, int(raw_anchor))
                    except (TypeError, ValueError):
                        pass
                else:
                    cp = store.get_active_compact_checkpoint(branch_id=branch_id)
                    if cp is not None:
                        after_seq = max(after_seq, cp.up_to_seq)
                continue
            body_msgs.append(msg)

        turns = list(store.list_turns(branch_id=branch_id, after_seq=after_seq))
        if len(turns) == len(body_msgs):
            for msg, turn in zip(body_msgs, turns):
                self._seq_by_msg_id[id(msg)] = turn.seq
            return
        # Prefix match fallback (e.g. after in-memory revert before persist)
        for msg, turn in zip(body_msgs, turns):
            if strip_internal_message_keys(msg) == dict(turn.raw_message):
                self._seq_by_msg_id[id(msg)] = turn.seq
            else:
                break

    def set_user_template(self, template: str):
        """Sets the system prompt/user template and resets the messages list."""
        self.messages = [{"role": "system", "content": template}]
        self.user_template = template
        self._seq_by_msg_id.clear()

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

        appended_seq = self.journal.append(msg)
        if not isinstance(appended_seq, int):
            appended_seq = getattr(self.journal, "last_turn_seq", None)
        if isinstance(appended_seq, int) and appended_seq > 0:
            self._seq_by_msg_id[id(msg)] = appended_seq

        if (
            self.hook_dispatcher is not None
            and self.hook_dispatcher.has_hooks(PluginHookEvent.MESSAGE_ADDED)
        ):
            self.hook_dispatcher.dispatch_message_added(
                MessageAddedContext(
                    role=role,
                    message=copy.deepcopy(msg),
                    messages=copy.deepcopy(self.messages),
                    session_id=self._journal_session_id(),
                    turn_seq=appended_seq if isinstance(appended_seq, int) else None,
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
            self._prune_seq_index()

    def clear_messages(self):
        self.messages = [{"role": "system", "content": self.user_template}]
        self._seq_by_msg_id.clear()

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

    def _apply_checkpoint_window_if_matching(self, messages: list[dict]) -> list[dict]:
        store = self._journal_session_store()
        if store is None or any(is_compact_summary_message(m) for m in messages):
            return messages
        branch_id = self._journal_branch_id()
        cp = store.get_active_compact_checkpoint(branch_id=branch_id)
        if cp is None:
            return messages

        sys_msg = messages[0] if messages and messages[0].get("role") == "system" else None
        non_sys = [
            strip_internal_message_keys(m)
            for m in (messages[1:] if sys_msg is not None else messages)
            if isinstance(m, Mapping)
        ]
        all_turns = list(store.list_turns(branch_id=branch_id))
        if not all_turns or [dict(t.raw_message) for t in all_turns] != non_sys:
            return messages

        assembled: list[dict[str, Any]] = []
        if sys_msg is not None:
            assembled.append(dict(sys_msg))
        assembled.append(
            build_compact_summary_message(cp.rolling_summary, up_to_seq=cp.up_to_seq)
        )
        for turn in all_turns:
            if turn.seq > cp.up_to_seq:
                assembled.append(copy.deepcopy(dict(turn.raw_message)))
        return assembled

    def set_messages(self, new_messages: list):
        """Sets the conversation history to a new list of messages."""
        if isinstance(new_messages, list):
            self.messages = list(new_messages)
            if getattr(self, "use_current_template_for_history", False):
                if self.messages and self.messages[0].get("role") == "system":
                    self.messages[0] = {**self.messages[0], "content": self.user_template}
                else:
                    self.messages.insert(0, {"role": "system", "content": self.user_template})
            self.messages = self._apply_checkpoint_window_if_matching(self.messages)
            self._strip_orphaned_tool_calls()
            self.messages = self._trim_loaded_history_if_needed(self.messages)
            self._rebind_seq_index_from_store()
            self._prune_seq_index()
            self.compact_manager.set_token_count(self.compact_manager.count_tokens(self.messages))
            print("Chat history has been updated.")
        else:
            print("Error: new_messages must be a list.")

    def _strip_orphaned_tool_calls(self) -> None:
        """清理不完整的 tool call 对：删孤立的 tool，补缺失的回执。"""
        strip_orphaned_tool_calls(self.get_messages())
