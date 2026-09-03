"""Public LLM manager facade.

The implementation is split by responsibility while this module keeps the
historical import surface stable for application code and plugins.
"""

from typing import Any, Dict, Optional

from ai.llm.adapter_factory import LLMAdapterFactory
from ai.llm.chat_manager import ChatManagerMixin
from ai.llm.chat_transport import ChatTransportMixin
from ai.llm.chat_types import (
    FIRST_USER_TURN_TOOL_CALL_LIMIT,
    ChatTurnState as _ChatTurnState,
)
from ai.llm.compact_manager import CompactManager
from ai.llm.llm_adapter import LLMAdapter
from ai.llm.manager_state import ManagerStateMixin
from ai.llm.tool_calling import ToolCallingMixin
from ai.llm.tool_runtime import tool_executor, tool_manager
from sdk.hooks import PluginHookDispatcher
from sdk.logging import get_logger


logger = get_logger(__name__)


class LLMManager(
    ManagerStateMixin,
    ChatManagerMixin,
    ToolCallingMixin,
    ChatTransportMixin,
):
    """Coordinate LLM conversation state, requests, and tool execution."""

    def __init__(
        self,
        adapter: LLMAdapter,
        user_template: str = "",
        max_tokens: int = 128000,
        compact_threshold: float = 0.4,
        compact_target_ratio: float = 0.3,
        history_recent_messages: int = 20,
        max_tool_result_chars: int = 6000,
        max_active_tool_groups: int = 3,
        first_turn_tool_call_limit: int = FIRST_USER_TURN_TOOL_CALL_LIMIT,
        generation_config: Optional[Dict[str, Any]] = None,
        history_file: str = "",
        hook_dispatcher: PluginHookDispatcher | None = None,
    ) -> None:
        self.llm_adapter = adapter
        self.messages = []
        self.user_template = user_template
        self.hook_dispatcher = hook_dispatcher
        self.max_context_tokens = int(max_tokens)
        self.history_recent_messages = max(1, int(history_recent_messages))
        self.max_tool_result_chars = max(1, int(max_tool_result_chars))
        self.first_turn_tool_call_limit = max(0, int(first_turn_tool_call_limit))
        self.compact_manager = CompactManager(
            adapter,
            self.max_context_tokens,
            compact_threshold,
            compact_target_ratio=compact_target_ratio,
            recent_message_limit=self.history_recent_messages,
            hook_dispatcher=self.hook_dispatcher,
        )
        self.generation_config = generation_config or {}
        self.set_user_template(user_template)
        self.tools_definitions = tool_manager.get_definitions(groups="default")
        self._active_tool_groups: list[str] = ["default"]
        self._max_active_groups = max(1, int(max_active_tool_groups))
        self.tools_manager = tool_manager
        self.tool_executor = tool_executor
        self.last_token_estimate = {
            "system_prompt_tokens": 0,
            "history_tokens": 0,
            "tool_definition_tokens": 0,
            "estimated_total_tokens": 0,
        }
        self._chat_depth = 0
        self._cancel_requested = False
        self._turn_state: Optional[_ChatTurnState] = None
        self._history_file = history_file
        self.logger = logger


__all__ = ["FIRST_USER_TURN_TOOL_CALL_LIMIT", "LLMAdapterFactory", "LLMManager"]
