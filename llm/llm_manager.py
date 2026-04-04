
from asyncio import Queue
from threading import Thread
from openai import OpenAI
import logging
from typing import List, Dict, Any, Optional, Generator, Union
import logging

from llm.llm_adapter import LLMAdapter, DeepSeekAdapter, OpenAIAdapter, GeminiAdapter, ClaudeAdapter
from llm.compact_manager import CompactManager
from llm.tools.tool_manager import ToolManager

tool_manager = ToolManager()

class LLMAdapterFactory:
    """Factory for creating different LLMAdapter instances."""
    _adapters = {
        "Deepseek": DeepSeekAdapter,
        "ChatGPT": OpenAIAdapter,
        "Gemini":  OpenAIAdapter,
        "Claude": ClaudeAdapter,
        "豆包": OpenAIAdapter,
        "通义千问": OpenAIAdapter,
    }

    @staticmethod
    def create_adapter(llm_provider: str, **kwargs) -> LLMAdapter:
        """Creates and returns an LLMAdapter instance based on the given name."""
        adapter_class = LLMAdapterFactory._adapters.get(llm_provider)
        
        if not adapter_class:
            raise ValueError(f"Unsupported LLM adapter: '{llm_provider}'. Supported adapters are: {list(LLMAdapterFactory._adapters.keys())}")
        
        try:
            return adapter_class(**kwargs)
        except TypeError as e:
            print(f"Error creating adapter '{llm_provider}'. Check the required arguments.")
            raise e


class LLMManager:
    def __init__(self, adapter: LLMAdapter, user_template='', max_tokens: int = 128000, compact_threshold: float = 0.9):
        self.llm_adapter = adapter
        self.messages = []
        self.user_template = user_template
        self.compact_manager = CompactManager(adapter, max_tokens, compact_threshold)
        self.set_user_template(user_template)
        self.tools_definitions = tool_manager.get_definitions()  # 获取工具定义列表
        self.tools_manager = tool_manager
        
        # 设置日志
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def set_adapter(self, adapter: LLMAdapter):
        """
        Sets the current LLM adapter. This is how you switch providers.
        """
        self.llm_adapter = adapter
        self.compact_manager.llm_adapter = adapter
        print(f"LLM adapter switched to {type(self.llm_adapter).__name__}.")
        self.messages = []

    def set_user_template(self, template: str):
        """Sets the system prompt/user template and resets the messages list."""
        self.messages = [{"role": "system", "content": template}]
        self.user_template = template
        self.llm_adapter.set_user_template(template)
        
    def add_message(self, role: str, content: Optional[str], **kwargs):
        """
        通用消息添加方法。
        集成了 Auto-Compact 逻辑：每当消息增加，自动检查并压缩。
        """
        msg = {"role": role, "content": content}
        msg.update(kwargs)
        self.messages.append(msg)
        
        # --- Auto-Compact 逻辑 ---
        # 自动调用 compact_manager 检查 token 是否超限并执行压缩
        compacted_messages = self.compact_manager.auto_compact_if_needed(self.messages)
        if len(compacted_messages) < len(self.messages):
            self.logger.info(f"Auto-compact triggered: Reduced messages from {len(self.messages)} to {len(compacted_messages)}")
            self.messages = compacted_messages

    def clear_messages(self):
        self.messages = [{"role": "system", "content": self.user_template}]

    def get_messages(self):
        """Returns the current list of messages."""
        return self.messages

    def set_messages(self, new_messages: list):
        """Sets the conversation history to a new list of messages."""
        if isinstance(new_messages, list):
            self.messages = new_messages
            print("Chat history has been updated.")
        else:
            print("Error: new_messages must be a list.")
            
    # def chat(self, message, stream=False, response_format = {'type':'json_object'}, auto_compact: bool = True):
    #     """
    #     Delegates the chat request to the current LLM adapter.
        
    #     Args:
    #         message: 用户消息
    #         stream: 是否使用流式响应
    #         response_format: 响应格式
    #         auto_compact: 是否自动压缩记忆
    #     """
    #     # 添加用户消息
    #     self.add_message("user", message)
        
    #     # 获取当前消息列表
    #     current_messages = self.get_messages()
        
    #     # 如果需要自动压缩，检查并压缩消息
    #     if auto_compact:
    #         try:
    #             compacted_messages = self.compact_manager.auto_compact_if_needed(current_messages)
    #             if compacted_messages != current_messages:
    #                 self.logger.info("Messages were compacted")
    #                 self.set_messages(compacted_messages)
    #         except Exception as e:
    #             self.logger.error(f"Auto-compaction failed: {e}")
        
    #     # 传递消息列表给LLM适配器
    #     response = self.llm_adapter.chat(self.get_messages(), stream, response_format, tools=self.tools_definitions)
        
    #     # 如果不是流式响应，处理并添加助手消息
    #     if not stream and response:
    #         try:
    #             # 获取不同适配器的响应内容
    #             if isinstance(self.llm_adapter, (DeepSeekAdapter, OpenAIAdapter)):
    #                 new_message = response.choices[0].message.content
    #             elif isinstance(self.llm_adapter, GeminiAdapter):
    #                 new_message = response.text
    #             elif isinstance(self.llm_adapter, ClaudeAdapter):
    #                 new_message = response.content[0].text
                
    #             self.add_message("assistant", new_message) # 添加助手消息
    #             self.logger.info(f"Assistant's response added: {new_message[:100]}...")
    #             return new_message
    #         except Exception as e:
    #             self.logger.error(f"Failed to process or add assistant message: {e}")
    #     return response
    
    def chat(self, user_input: Optional[str], stream: bool = True, **kwargs) -> Union[Generator, str]:
        """
        统一入口：根据 stream 参数决定调用流式还是同步私有方法。
        """
        if user_input:
            self.add_message("user", user_input)

        if stream:
            return self._chat_with_tools_stream(**kwargs)
        else:
            return self._chat_with_tools_sync(**kwargs)

    def _chat_with_tools_stream(self, **kwargs) -> Generator[str, None, None]:
        """
        流式工具处理逻辑 (内部私有)
        """
        tools_defs = tool_manager.get_definitions()  # 获取工具定义列表
        # print("tools_defs:", tools_defs)
        
        response_stream = self.llm_adapter.chat(
            messages=self.get_messages(),
            stream=True,
            tools=tools_defs if tools_defs else None,
            **kwargs
        )

        full_tool_calls = {}
        has_tool_use = False
        collected_content = ""

        for chunk in response_stream:
            delta = chunk.choices[0].delta
            
            # 1. 处理工具碎片
            if hasattr(delta, 'tool_calls') and delta.tool_calls:
                has_tool_use = True
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in full_tool_calls:
                        full_tool_calls[idx] = tc
                    if tc.function and tc.function.arguments:
                        full_tool_calls[idx].function.arguments += tc.function.arguments
                continue

            # 2. 正常内容 yield 给 Worker
            if hasattr(delta, 'content') and delta.content:
                content = delta.content
                collected_content += content
                yield content

        # 3. 如果需要调工具，执行完后递归
        if has_tool_use:
            tool_calls_list = list(full_tool_calls.values())
            
            # 【关键修改】：将 ToolCall 对象转换为字典列表
            serializable_tool_calls = []
            for tc in tool_calls_list:
                tc_dict = tc.model_dump()
                if 'index' in tc_dict:
                    del tc_dict['index']
                serializable_tool_calls.append(tc_dict)

            # 存入消息历史的是纯字典
            self.add_message("assistant", "", tool_calls=serializable_tool_calls)
            
            for tc in tool_calls_list:
                self.logger.info(f"Executing tool: {tc.function.name}")
                result = tool_manager.execute(tc.function.name, tc.function.arguments)
                self.add_message("tool", result, tool_call_id=tc.id, name=tc.function.name)
            
            yield from self._chat_with_tools_stream(**kwargs)

    def _chat_with_tools_sync(self, **kwargs) -> str:
        """
        同步工具处理逻辑，无流式处理
        """
        tools_defs = tool_manager.get_definitions()  # 获取工具定义列表
        # print("tools_defs:", tools_defs)        

        response = self.llm_adapter.chat(
            messages=self.get_messages(),
            stream=False,
            tools=tools_defs if tools_defs else None,
            **kwargs
        )

        message = response.choices[0].message
        
        if hasattr(message, 'tool_calls') and message.tool_calls:
            self.add_message("assistant", "", tool_calls=message.tool_calls)
            for tc in message.tool_calls:
                result = self.tool_manager.execute(tc.function.name, tc.function.arguments)
                self.add_message("tool", result, tool_call_id=tc.id, name=tc.function.name)

            self.logger.info("Tools executed, fetching final response...")
            return self._chat_with_tools_sync(**kwargs)
        else:
            content = message.content or ""
            self.add_message("assistant", content)
            return content