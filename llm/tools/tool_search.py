"""Meta-tool: search available tools by keyword or group, registered as 'search_tools'."""

from __future__ import annotations

from sdk.tool_registry import tool


@tool(name="search_tools", group="default", description=(
    "Search available tools by keyword or group name. "
    "Call this FIRST when you need a capability you don't see in your current tool list. "
    "Returns matching tool names, groups, and descriptions."
))
def _tool_search_tools(keyword: str = "") -> list[dict]:
    from llm.tools.tool_manager import ToolManager
    tm = ToolManager()
    if not keyword or not keyword.strip():
        return [{"name": d["function"]["name"],
                 "group": tm.get_tool_group(d["function"]["name"]),
                 "description": d["function"]["description"]}
                for d in tm.get_definitions()]
    return tm.search_tools(keyword)
