"""Conversation facade with explicit dependencies and scoped turn lifecycle.

Legacy constructor arguments and imports remain available. History, request
recovery, provider responses and tool policy each have a separate owner.
"""

from __future__ import annotations

import copy
from collections.abc import Generator
from datetime import datetime
from typing import Any, Dict, Optional, Union

from ai.llm.adapter_factory import LLMAdapterFactory
from ai.llm.chat_loop import ChatLoop
from ai.llm.compact_manager import CompactManager
from ai.llm.conversation_history import ConversationHistory
from ai.llm.message_journal import HistoryFileJournal
from ai.llm.ports import ChatHost, HistoryCompactor, MessageJournal, ToolCatalog, ToolRunner
from ai.llm.request_runner import RequestRunner
from ai.llm.runtime_defaults import tool_executor, tool_manager
from ai.llm.tool_session import FIRST_USER_TURN_TOOL_CALL_LIMIT, ToolSession
from core.chat_history.identity import CHAT_TURN_ID
from sdk.adapters.llm import LLMAdapter
from sdk.hooks import PluginHookDispatcher
from sdk.llm_runtime import get_llm_host_runtime
from sdk.logging import get_logger

logger = get_logger(__name__)


def _prefix_user_text_with_local_time(text: Any) -> Any:
    """为发送给模型的用户正文加上本机本地时间（供模型感知「何时」发送）。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[本地时间 {ts}]"
    if not isinstance(text, list):
        return f"{prefix}\n{text}"
    content = copy.deepcopy(text)
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            block["text"] = f"{prefix}\n{str(block.get('text') or '')}"
            return content
    content.insert(0, {"type": "text", "text": prefix})
    return content


def _view(owner: str, attribute: str) -> property:
    """Keep legacy state attributes as views of their single owning component."""
    def get(instance):
        return getattr(getattr(instance, owner), attribute)
    def set_value(instance, value):
        setattr(getattr(instance, owner), attribute, value)
    return property(get, set_value)


class LLMManager:
    messages = _view("_history", "messages")
    user_template = _view("_history", "user_template")
    compact_manager = _view("_history", "compact_manager")
    max_context_tokens = _view("_history", "max_context_tokens")
    history_recent_messages = _view("_history", "history_recent_messages")
    max_tool_result_chars = _view("_history", "max_tool_result_chars")
    use_current_template_for_history = _view("_history", "use_current_template_for_history")
    tools_manager = _view("_tools", "catalog")
    tool_executor = _view("_tools", "tool_executor")
    tools_enabled = _view("_tools", "tools_enabled")
    first_turn_tool_call_limit = _view("_tools", "first_turn_tool_call_limit")
    _active_tool_groups = _view("_tools", "_active_tool_groups")
    _max_active_groups = _view("_tools", "_max_active_groups")
    _turn_state = _view("_tools", "_turn_state")
    last_token_estimate = _view("_requests", "last_token_estimate")
    generation_config = _view("_loop", "generation_config")
    media_selection_mode = _view("_loop", "media_selection_mode")

    def __init__(
        self, adapter: LLMAdapter, user_template='', max_tokens: int = 128000,
        compact_threshold: float = 0.4, compact_target_ratio: float = 0.3,
        history_recent_messages: int = 20, max_tool_result_chars: int = 6000,
        max_active_tool_groups: int = 3,
        first_turn_tool_call_limit: int = FIRST_USER_TURN_TOOL_CALL_LIMIT,
        generation_config: Optional[Dict[str, Any]] = None, history_file: str = "",
        hook_dispatcher: PluginHookDispatcher | None = None,
        media_selection_mode: str = "indexed", tools_enabled: bool = True,
        use_current_template_for_history: bool = False, *,
        tools: ToolCatalog | None = None, executor: ToolRunner | None = None,
        host: ChatHost | None = None, journal: MessageJournal | None = None,
        compactor: HistoryCompactor | None = None,
    ) -> None:
        if tools is not None and executor is None:
            raise ValueError("An injected tool catalog requires a matching executor")
        self._adapter = adapter
        self._host = host
        self.logger = logger
        self._chat_depth = 0
        self._cancel_requested = False
        self._history_file = history_file
        compactor = compactor if compactor is not None else CompactManager(
            adapter, int(max_tokens), compact_threshold,
            compact_target_ratio=compact_target_ratio,
            recent_message_limit=max(1, int(history_recent_messages)),
            hook_dispatcher=hook_dispatcher,
        )
        journal = journal if journal is not None else HistoryFileJournal(history_file, self._persist_story_message)
        self._history = ConversationHistory(
            compact_manager=compactor, journal=journal, user_template=user_template,
            max_context_tokens=int(max_tokens), history_recent_messages=max(1, int(history_recent_messages)),
            max_tool_result_chars=max(1, int(max_tool_result_chars)), hook_dispatcher=hook_dispatcher,
            use_current_template_for_history=use_current_template_for_history, logger=self.logger,
        )
        self._tools = ToolSession(
            tools if tools is not None else tool_manager,
            executor if executor is not None else tool_executor,
            enabled=tools_enabled, max_active_groups=max(1, int(max_active_tool_groups)),
            first_turn_tool_call_limit=max(0, int(first_turn_tool_call_limit)),
            confirm=self._confirm_risky_tool, notify=self._notify_tool_call, logger=self.logger,
        )
        self._requests = RequestRunner(adapter, self._history, self._tools, host=self._get_host, logger=self.logger)
        self._loop = ChatLoop(
            adapter, self._tools, self._requests,
            cancelled=lambda: self._cancel_requested,
            append_message=lambda role, content, **metadata: self.add_message(role, content, **metadata),
            generation_config=generation_config or {},
            media_selection_mode="semantic" if str(media_selection_mode or "").strip().lower() == "semantic" else "indexed",
            logger=self.logger,
        )
        self.set_user_template(user_template)
        self.tools_definitions = self.tools_manager.get_definitions(groups="default") if tools_enabled else []

    @property
    def llm_adapter(self):
        return self._adapter

    @llm_adapter.setter
    def llm_adapter(self, adapter):
        self._adapter = adapter
        self._requests.llm_adapter = adapter
        self._loop.adapter = adapter

    @property
    def hook_dispatcher(self):
        return self._history.hook_dispatcher

    @hook_dispatcher.setter
    def hook_dispatcher(self, dispatcher):
        self._history.hook_dispatcher = dispatcher
        if hasattr(self.compact_manager, "hook_dispatcher"):
            self.compact_manager.hook_dispatcher = dispatcher

    def _get_host(self) -> ChatHost:
        return self._host if self._host is not None else get_llm_host_runtime()

    def _persist_story_message(self, message: dict) -> bool:
        hooks = getattr(self, "story_prompt_hooks", None)
        return hooks is not None and hooks.persist_message(message)

    def _notify_tool_call(self, name: str) -> None:
        try:
            self._get_host().notify_tool_call(name)
        except Exception:
            pass

    def _confirm_risky_tool(self, tool_name: str, risk: str, args_str: str) -> bool:
        if risk == "low":
            return True
        try:
            return self._get_host().confirm_risky_tool(tool_name, risk, args_str)
        except Exception:
            return risk != "high"

    def cancel_current_chat(self) -> None:
        self._cancel_requested = True
        if self.llm_adapter is not None:
            try:
                self.llm_adapter.cancel()
            except Exception:
                pass

    def set_adapter(self, adapter: LLMAdapter) -> None:
        self.llm_adapter = adapter
        if hasattr(self.compact_manager, "llm_adapter"):
            self.compact_manager.llm_adapter = adapter
        print(f"LLM adapter switched to {type(adapter).__name__}.")
        self.messages = []

    def set_user_template(self, template: str) -> None:
        self._history.set_user_template(template)
        self.llm_adapter.set_user_template(template)

    def add_message(self, role: str, content: Optional[str], **kwargs) -> None:
        self._history.add_message(role, content, **kwargs)

    def clear_messages(self) -> None:
        self._history.clear_messages()

    def get_messages(self):
        return self.messages

    def set_messages(self, new_messages: list) -> None:
        self._history.set_messages(new_messages)

    def get_context_token_estimate(self) -> dict[str, int]:
        return self._requests.get_context_token_estimate()

    def _finish_chat_scope(self) -> None:
        self._chat_depth = max(0, self._chat_depth - 1)
        if self._chat_depth == 0:
            self._tools.finish_turn()

    def _stream_with_chat_scope(self, stream):
        def scoped():
            try:
                # Enter the cleanup guard before returning, without provider I/O.
                yield
                yield from stream
            finally:
                self._finish_chat_scope()
        result = scoped()
        next(result)
        return result

    def chat(
        self, user_input: Optional[Any], stream: bool = True,
        dialog_output_required: bool = False, **kwargs,
    ) -> Union[Generator, str]:
        outer_chat = self._chat_depth == 0
        first_user_turn = outer_chat and user_input is not None and not any(
            message.get("role") != "system" for message in self.messages
        )
        if outer_chat:
            self._tools._begin_chat_turn(first_user_turn=first_user_turn)
        self._chat_depth += 1
        self._cancel_requested = False
        stream_owns_scope = False
        try:
            self._history._strip_orphaned_tool_calls()
            include_local_time = bool(kwargs.pop("include_local_time", True))
            display_text = str(kwargs.pop("user_display_text", "") or "").strip()
            input_text = kwargs.pop("user_input_text", None)
            history_turn_id = kwargs.pop("history_turn_id", "")
            attachments = kwargs.pop("user_attachments", None)
            groups = kwargs.pop("tool_groups", ())
            if isinstance(groups, str):
                groups = (groups,)
            for group in groups:
                self._activate_tool_group(str(group or "").strip())
            if user_input:
                if include_local_time:
                    user_input = _prefix_user_text_with_local_time(user_input)
                metadata = {}
                if history_turn_id:
                    metadata[CHAT_TURN_ID] = str(history_turn_id)
                if display_text:
                    metadata["display_content"] = display_text
                if input_text is not None:
                    metadata["input_text"] = str(input_text or "")
                if isinstance(attachments, list):
                    metadata["attachments"] = copy.deepcopy(attachments)
                self.add_message("user", user_input, **metadata)
            if stream:
                result = self._stream_with_chat_scope(self._chat_with_tools_stream(
                    _dialog_output_required=dialog_output_required, **kwargs,
                ))
                stream_owns_scope = True
                return result
            return self._chat_with_tools_sync(_dialog_output_required=dialog_output_required, **kwargs)
        finally:
            if not stream_owns_scope:
                self._finish_chat_scope()

    def _chat_with_tools_stream(self, **kwargs):
        return self._loop.stream(dialog_output_required=bool(kwargs.pop("_dialog_output_required", False)), **kwargs)

    def _chat_with_tools_sync(self, **kwargs):
        return self._loop.sync(dialog_output_required=bool(kwargs.pop("_dialog_output_required", False)), **kwargs)

    def _prepare_tool_result_for_history(self, result):
        return self._history._prepare_tool_result_for_history(result)

    def _history_load_budget(self):
        return self._history._history_load_budget()

    def _trim_loaded_history_if_needed(self, messages):
        return self._history._trim_loaded_history_if_needed(messages)

    def _before_chat_context(self, **kwargs):
        return self._history._before_chat_context(**kwargs)

    def _strip_orphaned_tool_calls(self):
        self._history._strip_orphaned_tool_calls()

    def _estimate_context_tokens(self, tools_defs, messages=None):
        return self._requests._estimate_context_tokens(tools_defs, messages)

    def _current_tool_definitions(self):
        return self._tools._current_tool_definitions()

    def _activate_tool_group(self, group):
        self._tools._activate_tool_group(group)

    def _activate_tool_group_from_search(self, arguments):
        self._tools._activate_tool_group_from_search(arguments)
