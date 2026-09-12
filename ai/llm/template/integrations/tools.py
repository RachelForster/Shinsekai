"""Tool registry projection used by the legacy template facade."""

from typing import Any

from ai.tools.tool_manager import ToolManager
from sdk.tool_registry import iter_registered_tools
from plugin_system.host import read_plugin_manifest_items

# Keep builtin registration at module import for existing application callers.
import ai.tools.character_tools  # noqa: F401
import ai.tools.reminder_tools  # noqa: F401
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
    tm = ToolManager()
    module_states = []
    entry_states = []
    for item in read_plugin_manifest_items():
        module = item["entry"].split(":", 1)[0].strip()
        entry_states.append((module, bool(item.get("enabled", True))))
        # Tool helpers commonly live beside the plugin entry module.
        package = module.rpartition(".")[0] if "." in module else module
        if package == "plugins":
            package = module
        module_states.append((package, bool(item.get("enabled", True))))

    def visible(module: str) -> bool:
        owners = [(entry, enabled) for entry, enabled in entry_states
                  if module == entry or module.startswith(entry + ".")]
        if not owners:
            owners = [(package, enabled) for package, enabled in module_states
                      if module == package or module.startswith(package + ".")]
        if owners:
            longest = max(len(package) for package, _ in owners)
            return any(enabled for package, enabled in owners if len(package) == longest)
        # A removed local plugin can remain imported until the process restarts.
        return not module.startswith("plugins.")

    # Template generation may precede full host startup. Apply only visible
    # declarations; never resurrect disabled plugin decorators in ToolManager.
    for fn, name, description, group, risk in iter_registered_tools():
        if visible(fn.__module__):
            tm.register_function(fn, name=name, description=description, group=group, risk=risk)
    available = [entry for entry in tm.get_definitions()
                 if visible(tm.get_tool_module(entry["function"]["name"]))]
    definitions = [entry for entry in available
                   if tm.get_tool_group(entry["function"]["name"]) == "default"]
    if not definitions:
        return ""
    other_groups = sorted({tm.get_tool_group(entry["function"]["name"]) for entry in available} - {"default"})
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
