"""User-facing memory operations backed by SOLID narrow ports."""

from __future__ import annotations

import urllib.error
import urllib.request

from ai.memory.operations.context import (
    MemoryToolSessionContext,
    _SEMANTIC_DEDUPLICATION_SEARCH_LIMIT,
    _mem0_operation_lock,
    _memory_request_context,
    _memory_row,
    _resolve_agent_id,
    _search_mem0,
    bind_memory_tool_context,
    current_memory_tool_context,
    reset_memory_tool_context,
    update_memory_tool_context_mode,
)
from ai.memory.operations.mutations import (
    memory_awaken,
    memory_awaken_and_list,
    memory_forget,
    memory_forget_and_list,
    memory_forget_many_and_list,
    memory_remember,
    memory_remember_and_list,
    memory_set_pinned,
    memory_set_pinned_and_list,
)
from ai.memory.operations.queries import (
    memory_list,
    memory_list_all,
    memory_recall_turn,
    memory_search,
)
from ai.memory.operations.rollback import (
    memory_rollback_after_turn,
    memory_rollback_count,
)
from ai.memory.operations.service_client import (
    _memory_service_request,
    _memory_service_timeout_sec,
    _memory_service_url,
    _start_memory_service_ready_monitor,
    memory_service_status,
)
from ai.memory.runtime import ensure_mem0, peek_mem0

__all__ = [
    "MemoryToolSessionContext",
    "bind_memory_tool_context",
    "current_memory_tool_context",
    "ensure_mem0",
    "memory_awaken",
    "memory_awaken_and_list",
    "memory_forget",
    "memory_forget_and_list",
    "memory_forget_many_and_list",
    "memory_list",
    "memory_list_all",
    "memory_recall_turn",
    "memory_remember",
    "memory_remember_and_list",
    "memory_rollback_after_turn",
    "memory_rollback_count",
    "memory_search",
    "memory_service_status",
    "memory_set_pinned",
    "memory_set_pinned_and_list",
    "peek_mem0",
    "reset_memory_tool_context",
    "update_memory_tool_context_mode",
    "urllib",
]
