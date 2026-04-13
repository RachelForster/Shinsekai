import json
import inspect
import functools
import logging
from typing import Dict, Any, List, Callable

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
        self._functions: Dict[str, Callable] = {}
        self.logger = logging.getLogger("ToolManager")
        self._initialized = True

    def tool(self, func: Callable):
        """
        装饰器：@tool
        利用单例特性，将所有带此注解的函数集中注册到唯一实例中。
        """
        name = func.__name__
        doc = func.__doc__.strip() if func.__doc__ else "No description provided."
        
        # 自动解析参数类型和名称
        sig = inspect.signature(func)
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            # 跳过 self 参数（如果是类方法）
            if param_name == 'self':
                continue
                
            ptype = "string"
            if param.annotation == int: ptype = "integer"
            elif param.annotation == bool: ptype = "boolean"
            elif param.annotation == float: ptype = "number"

            properties[param_name] = {
                "type": ptype,
                "description": f"参数: {param_name}"
            }
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        definition = {
            "type": "function",
            "function": {
                "name": name,
                "description": doc,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }

        self._tools_definitions.append(definition)
        self._functions[name] = func
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper

    def get_definitions(self) -> List[Dict[str, Any]]:
        return self._tools_definitions

    def execute(self, name: str, arguments_json: str) -> str:
        self.logger.info(f"Executing tool: {name} with arguments: {arguments_json}")
        if name not in self._functions:
            return json.dumps({"error": f"Tool '{name}' not found."})
        
        try:
            args = json.loads(arguments_json)
            result = self._functions[name](**args)
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error executing tool '{name}': {e}")
            return json.dumps({"error": str(e)})