import functools
import inspect
import json
import logging
from typing import Any, Callable, Dict, List


class ToolManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(ToolManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._tools_definitions: List[Dict[str, Any]] = []
        self._functions: Dict[str, Callable[..., Any]] = {}
        self._tool_groups: Dict[str, str] = {}  # tool_name -> group
        self.logger = logging.getLogger("ToolManager")
        self._initialized = True

    def _drop_tool(self, tool_name: str) -> None:
        self._tools_definitions = [
            d
            for d in self._tools_definitions
            if d.get("function", {}).get("name") != tool_name
        ]
        self._functions.pop(tool_name, None)
        self._tool_groups.pop(tool_name, None)

    def _schema_type_for_param(self, annotation: Any) -> str:
        if annotation is inspect.Parameter.empty:
            return "string"
        if annotation is int:
            return "integer"
        if annotation is bool:
            return "boolean"
        if annotation is float:
            return "number"
        if annotation is str:
            return "string"
        return "string"

    def _normalize_mcp_input_schema(self, schema: Any) -> Dict[str, Any]:
        """将 MCP ``inputSchema`` 规范为 OpenAI 工具 ``parameters`` 形态（object）。"""
        if not schema or not isinstance(schema, dict):
            return {"type": "object", "properties": {}, "required": []}
        if schema.get("type") == "object":
            return {
                "type": "object",
                "properties": dict(schema.get("properties") or {}),
                "required": list(schema.get("required") or []),
            }
        return {
            "type": "object",
            "properties": {"value": schema},
            "required": ["value"],
        }

    def register_function(
        self,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
        group: str | None = None,
    ) -> None:
        """
        将可调用对象注册为 LLM 工具（OpenAI 风格 function schema）。
        同名工具会先被移除再注册，便于热重载或覆盖。
        ``group`` 为工具分组（"character" / "memory" / "mcp" 等），默认 "default"。
        """
        tool_name = (name or func.__name__).strip()
        if not tool_name:
            raise ValueError("tool name cannot be empty")

        doc_raw = func.__doc__ or ""
        doc = (description or doc_raw).strip() or "No description provided."

        sig = inspect.signature(func)
        properties: Dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            ptype = self._schema_type_for_param(param.annotation)
            properties[param_name] = {
                "type": ptype,
                "description": f"参数: {param_name}",
            }
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        definition = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": doc,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

        self._drop_tool(tool_name)
        self._tools_definitions.append(definition)
        self._functions[tool_name] = func
        self._tool_groups[tool_name] = group or "default"

    def register_mcp_tools(
        self,
        tools: List[Dict[str, Any]],
        *,
        invoke: Callable[[str, Dict[str, Any]], Any],
        name_prefix: str = "",
        group: str = "mcp",
    ) -> None:
        """
        注册来自 MCP ``tools/list`` 的工具条目（``name`` / ``description`` / ``inputSchema``）。

        ``invoke`` 在 LLM 选中某工具时调用：``invoke(registered_name, arguments_dict)``，
        返回值由 :meth:`execute` 以 JSON 序列化；请返回可 JSON 编码的对象或字符串。

        ``name_prefix`` 用于隔离多套 MCP 工具，避免与内置工具名冲突。
        ``group`` 为 MCP 工具分组，默认 "mcp"。
        """
        prefix = name_prefix.strip()
        grp = (group or "mcp").strip()
        for raw in tools:
            if not isinstance(raw, dict):
                self.logger.warning("register_mcp_tools: skip non-dict item %r", raw)
                continue
            name = raw.get("name")
            if not isinstance(name, str) or not name.strip():
                self.logger.warning("register_mcp_tools: skip tool without name: %r", raw)
                continue
            tool_name = f"{prefix}{name.strip()}"
            desc_raw = raw.get("description")
            doc = (
                str(desc_raw).strip()
                if isinstance(desc_raw, str)
                else "No description provided."
            )
            schema = raw.get("inputSchema")
            if schema is None and isinstance(raw.get("parameters"), dict):
                schema = raw.get("parameters")

            parameters = self._normalize_mcp_input_schema(schema)
            definition = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": doc,
                    "parameters": parameters,
                },
            }

            def _make_runner(
                registered: str, inv: Callable[[str, Dict[str, Any]], Any]
            ) -> Callable[..., Any]:
                def _run(**kwargs: Any) -> Any:
                    return inv(registered, kwargs)

                return _run

            self._drop_tool(tool_name)
            self._tools_definitions.append(definition)
            self._functions[tool_name] = _make_runner(tool_name, invoke)
            self._tool_groups[tool_name] = grp

    def tool(self, func: Callable[..., Any] = None, *, group: str | None = None) -> Callable[..., Any]:
        """
        装饰器：@tool_manager.tool 或 @tool_manager.tool(group="character")
        利用单例特性，将函数注册到当前实例（与 :func:`register_function` 等价）。
        """
        def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.register_function(fn, group=group)
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                return fn(*args, **kwargs)
            return wrapper
        if func is None:
            return _decorator
        return _decorator(func)

    def get_definitions(self, groups: str | List[str] | None = None) -> List[Dict[str, Any]]:
        """Return tool definitions, optionally filtered by group(s)."""
        if groups is None:
            return self._tools_definitions
        if isinstance(groups, str):
            groups = [groups]
        return [
            d for d in self._tools_definitions
            if self._tool_groups.get(d["function"]["name"], "default") in groups
        ]

    def search_tools(self, keyword: str) -> List[Dict[str, Any]]:
        """Search tools by keyword in name, description, or group."""
        kw = keyword.strip().lower()
        if not kw:
            return []
        results = []
        for d in self._tools_definitions:
            fn = d["function"]
            name = fn.get("name", "").lower()
            desc = fn.get("description", "").lower()
            grp = self._tool_groups.get(fn["name"], "default").lower()
            if kw in name or kw in desc or kw == grp:
                results.append({
                    "name": fn["name"],
                    "group": self._tool_groups.get(fn["name"], "default"),
                    "description": fn.get("description", ""),
                })
        return results

    def get_tool_group(self, tool_name: str) -> str:
        """Return the group name for a tool."""
        return self._tool_groups.get(tool_name, "default")

    def get_groups(self) -> List[str]:
        """Return list of all registered groups."""
        return list(sorted(set(self._tool_groups.values())))

    def execute(self, name: str, arguments_json: str) -> str:
        self.logger.info("Executing tool: %s with arguments: %s", name, arguments_json)
        if name not in self._functions:
            return json.dumps({"error": f"Tool '{name}' not found."})

        try:
            args = json.loads(arguments_json)
            result = self._functions[name](**args)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            self.logger.error("Error executing tool '%s': %s", name, e)
            return json.dumps({"error": str(e)})
