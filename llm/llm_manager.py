
from asyncio import Queue
import json
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

    # llm_manager.py 修正核心片段

    def _chat_with_tools_stream(self, **kwargs) -> Generator[str, None, None]:
        tools_defs = tool_manager.get_definitions()
        response_stream = self.llm_adapter.chat(
            messages=self.get_messages(), stream=True, 
            tools=tools_defs if tools_defs else None, **kwargs
        )
        if response_stream is None: return

        full_tool_calls = {}
        has_tool_use = False
        collected_content = ""

        if isinstance(self.llm_adapter, ClaudeAdapter):
            with response_stream as stream:
                for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield event.delta.text
                        collected_content += event.delta.text
                    elif event.type == "content_block_start" and event.content_block.type == "tool_use":
                        has_tool_use = True
                        full_tool_calls[event.index] = {"id": event.content_block.id, "name": event.content_block.name, "input": ""}
                    elif event.type == "record_delta" and event.delta.type == "input_json_delta":
                        full_tool_calls[event.index]["input"] += event.delta.partial_json
        else:
            for chunk in response_stream:
                if not chunk or not chunk.choices: continue
                delta = chunk.choices[0].delta
                if hasattr(delta, 'tool_calls') and delta.tool_calls:
                    has_tool_use = True
                    for tc in delta.tool_calls:
                        if tc.index not in full_tool_calls: full_tool_calls[tc.index] = tc
                        if tc.function and tc.function.arguments:
                            full_tool_calls[tc.index].function.arguments += tc.function.arguments
                if hasattr(delta, 'content') and delta.content:
                    yield delta.content
                    collected_content += delta.content

        if has_tool_use:
            formatted_calls = []
            for idx in sorted(full_tool_calls.keys()):
                tc = full_tool_calls[idx]
                t_id = tc["id"] if isinstance(tc, dict) else tc.id
                t_name = tc["name"] if isinstance(tc, dict) else tc.function.name
                t_args = tc["input"] if isinstance(tc, dict) else tc.function.arguments
                formatted_calls.append({"id": t_id, "type": "function", "function": {"name": t_name, "arguments": t_args}})

            # --- 关键：必须先添加 Assistant 消息 ---
            self.add_message("assistant", collected_content, tool_calls=formatted_calls)

            # --- 然后添加 Tool 结果消息 ---
            for call in formatted_calls:
                try:
                    func_name = call['function']['name']
                    func_args = call['function']['arguments']
                    if isinstance(func_args, str):
                        if not func_args.strip():
                            func_args = "{}"  # 修正为空 JSON 对象字符串
                    
                    # 2. 执行工具
                    result = tool_manager.execute(func_name, func_args)
                    
                    # 3. 确保结果不为空且为字符串（以便 LLM 接收）
                    if result is None:
                        result = json.dumps({"status": "success", "result": "no return value"})
                    elif not isinstance(result, str):
                        result = json.dumps(result)

                except Exception as e:
                    self.logger.error(f"Tool execution failed: {e}")
                    result = json.dumps({"error": str(e)})
                self.add_message("tool", result, tool_call_id=call['id'], name=func_name)
            
            yield from self._chat_with_tools_stream(**kwargs)

    def _chat_with_tools_sync(self, **kwargs) -> str:
        tools_defs = tool_manager.get_definitions()
        response = self.llm_adapter.chat(
            messages=self.get_messages(), stream=False,
            tools=tools_defs if tools_defs else None, **kwargs
        )
        if not response: return ""

        content = ""
        tool_calls = []

        if isinstance(self.llm_adapter, ClaudeAdapter):
            for block in response.content:
                if block.type == 'text': content += block.text
                elif block.type == 'tool_use': tool_calls.append(block)
        else:
            message = response.choices[0].message
            content = message.content or ""
            tool_calls = getattr(message, 'tool_calls', []) or []

        if tool_calls:
            formatted_calls = []
            for tc in tool_calls:
                t_name = tc.function.name if hasattr(tc, 'function') else tc.name
                t_args = tc.function.arguments if hasattr(tc, 'function') else tc.input
                formatted_calls.append({"id": tc.id, "type": "function", "function": {"name": t_name, "arguments": t_args}})

            # --- 关键：先 Assistant 再 Tool ---
            self.add_message("assistant", content, tool_calls=formatted_calls)
            for call in formatted_calls:
                try:
                    func_name = call['function']['name']
                    func_args = call['function']['arguments']
                    if isinstance(func_args, str):
                        if not func_args.strip():
                            func_args = "{}"  # 修正为空 JSON 对象字符串
                    
                    # 2. 执行工具
                    result = tool_manager.execute(func_name, func_args)
                    
                    # 3. 确保结果不为空且为字符串（以便 LLM 接收）
                    if result is None:
                        result = json.dumps({"status": "success", "result": "no return value"})
                    elif not isinstance(result, str):
                        result = json.dumps(result)

                except Exception as e:
                    self.logger.error(f"Tool execution failed: {e}")
                    result = json.dumps({"error": str(e)})
                self.add_message("tool", result, tool_call_id=call['id'], name=func_name)

            return self._chat_with_tools_sync(**kwargs)
        else:
            return content