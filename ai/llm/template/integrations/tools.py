"""Tool registry projection used by the legacy template facade."""

from typing import Any

from ai.tools.tool_manager import ToolManager
from sdk.tool_registry import apply_registered_tools

# Keep builtin registration at module import for existing application callers.
import ai.tools.character_tools  # noqa: F401
import ai.tools.memory_tools  # noqa: F401
import ai.tools.tool_search  # noqa: F401
import ai.tools.file_tools  # noqa: F401
import ai.tools.chat_ui_tools  # noqa: F401
import ai.tools.story_tools  # noqa: F401


def _summarize_tool_parameters(parameters: Any) -> str:
    if not parameters or not isinstance(parameters, dict):
        return ""
    props = parameters.get("properties")
    if not isinstance(props, dict) or not props:
        return ""
    raw_req = parameters.get("required")
    required: set[str] = (
        {str(x) for x in raw_req} if isinstance(raw_req, list) else set()
    )
    parts: list[str] = []
    for key in sorted(props.keys()):
        spec = props.get(key)
        if isinstance(spec, dict):
            ptype = str(spec.get("type", "string"))
        else:
            ptype = "string"
        mark = "*" if str(key) in required else ""
        parts.append(f"{key}{mark}: {ptype}")
    summary = ", ".join(parts)
    if len(summary) > 320:
        summary = summary[:317] + "..."
    return summary


def format_llm_tools_block(translate) -> str:
    """Only include default-group tools in the system prompt.
    Use search_tools to discover tools from other groups on demand."""
    _T = translate
    apply_registered_tools(ToolManager())
    definitions = ToolManager().get_definitions(groups="default")
    if not definitions:
        return ""
    tm = ToolManager()
    other_groups = [g for g in tm.get_groups() if g != "default"]
    other_hint = ""
    if other_groups:
        other_hint = _T("tools_other_groups", groups=", ".join(other_groups))
    lines: list[str] = [
        _T("tools_header"),
        _T("tools_intro"),
        other_hint,
        "",
    ]
    for entry in definitions:
        if not isinstance(entry, dict) or entry.get("type") != "function":
            continue
        fn = entry.get("function")
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        desc = str(fn.get("description") or "").strip()
        if not desc:
            desc = _T("tools_no_desc")
        param_summ = _summarize_tool_parameters(fn.get("parameters"))
        item = _T("tools_item", name=name, description=desc)
        if param_summ:
            item += _T("tools_param_summary", summary=param_summ)
        lines.append(item)
    lines.append("")
    return "\n".join(lines)
