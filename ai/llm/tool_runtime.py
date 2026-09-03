"""Shared tool registry used by LLM manager instances."""

from ai.tools.tool_executor import ToolExecutor
from ai.tools.tool_manager import ToolManager
from sdk.llm_runtime import get_llm_host_runtime
from sdk.tool_registry import set_tool_ready_callback


tool_manager = ToolManager()
tool_executor = ToolExecutor(tool_manager)


def _on_tool_ready(group: str, message: str) -> None:
    tool_executor.clear_cooldown(group)
    get_llm_host_runtime().notify_tool_ready(group, message)


set_tool_ready_callback(_on_tool_ready)
