"""Meta-tools: search tools / list groups, registered under 'default' group."""

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


@tool(name="list_tool_groups", group="default", description=(
    "List all available tool group names and the tool count in each group. "
    "Use this to discover what categories of tools are available before enabling or searching specific groups."
))
def _tool_list_groups() -> list[dict]:
    from llm.tools.tool_manager import ToolManager
    tm = ToolManager()
    all_defs = tm.get_definitions()
    group_counts: dict[str, int] = {}
    for d in all_defs:
        grp = tm.get_tool_group(d["function"]["name"])
        group_counts[grp] = group_counts.get(grp, 0) + 1
    return [{"group": g, "tool_count": c} for g, c in sorted(group_counts.items())]
