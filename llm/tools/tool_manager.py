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
        self.logger = logging.getLogger("ToolManager")
        self._initialized = True

    def _drop_tool(self, tool_name: str) -> None:
        self._tools_definitions = [
            d
            for d in self._tools_definitions
            if d.get("function", {}).get("name") != tool_name
        ]
        self._functions.pop(tool_name, None)

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

    def register_function(
        self,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """
        将可调用对象注册为 LLM 工具（OpenAI 风格 function schema）。
        同名工具会先被移除再注册，便于热重载或覆盖。
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

    def tool(self, func: Callable[..., Any]) -> Callable[..., Any]:
        """
        装饰器：@tool_manager.tool
        利用单例特性，将函数注册到当前实例（与 :func:`register_function` 等价）。
        """
        self.register_function(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        return wrapper

    def get_definitions(self) -> List[Dict[str, Any]]:
        return self._tools_definitions

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
