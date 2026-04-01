
from asyncio import Queue
from threading import Thread
from openai import OpenAI
import json
import time
import yaml
import traceback
import logging

from llm.llm_adapter import LLMAdapter, DeepSeekAdapter, OpenAIAdapter, GeminiAdapter, ClaudeAdapter
from llm.compact_manager import CompactManager

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
        
    def add_message(self, role, content):
        """Adds a message to the conversation history."""
        self.messages.append({"role": role, "content": content})

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
            
    def chat(self, message, stream=False, response_format = {'type':'json_object'}, auto_compact: bool = True):
        """
        Delegates the chat request to the current LLM adapter.
        
        Args:
            message: 用户消息
            stream: 是否使用流式响应
            response_format: 响应格式
            auto_compact: 是否自动压缩记忆
        """
        # 添加用户消息
        self.add_message("user", message)
        
        # 获取当前消息列表
        current_messages = self.get_messages()
        
        # 如果需要自动压缩，检查并压缩消息
        if auto_compact:
            try:
                compacted_messages = self.compact_manager.auto_compact_if_needed(current_messages)
                if compacted_messages != current_messages:
                    self.logger.info("Messages were compacted")
                    self.set_messages(compacted_messages)
            except Exception as e:
                self.logger.error(f"Auto-compaction failed: {e}")
        
        # 传递消息列表给LLM适配器
        response = self.llm_adapter.chat(self.get_messages(), stream, response_format)
        
        # 如果不是流式响应，处理并添加助手消息
        if not stream and response:
            try:
                # 获取不同适配器的响应内容
                if isinstance(self.llm_adapter, (DeepSeekAdapter, OpenAIAdapter)):
                    new_message = response.choices[0].message.content
                elif isinstance(self.llm_adapter, GeminiAdapter):
                    new_message = response.text
                elif isinstance(self.llm_adapter, ClaudeAdapter):
                    new_message = response.content[0].text
                
                self.add_message("assistant", new_message) # 添加助手消息
                self.logger.info(f"Assistant's response added: {new_message[:100]}...")
                return new_message
            except Exception as e:
                self.logger.error(f"Failed to process or add assistant message: {e}")
        return response
    
    def manual_compact(self) -> bool:
        """
        手动触发记忆压缩
        
        Returns:
            bool: 压缩是否成功
        """
        try:
            current_messages = self.get_messages()
            compacted_messages = self.compact_manager.compact_messages(current_messages)
            
            if compacted_messages != current_messages:
                self.set_messages(compacted_messages)
                self.logger.info("Manual compaction completed successfully")
                return True
            else:
                self.logger.info("No compaction needed or compaction failed")
                return False
        except Exception as e:
            self.logger.error(f"Manual compaction failed: {e}")
            return False
    
    def get_token_count(self) -> int:
        """
        获取当前消息列表的token数量
        
        Returns:
            int: token数量
        """
        return self.compact_manager.count_tokens(self.get_messages())
    
    def get_compaction_status(self) -> dict:
        """
        获取压缩状态信息
        
        Returns:
            dict: 包含token数量、阈值等信息的字典
        """
        token_count = self.get_token_count()
        threshold = self.compact_manager.max_tokens * self.compact_manager.compact_threshold
        
        return {
            'token_count': token_count,
            'max_tokens': self.compact_manager.max_tokens,
            'compact_threshold': self.compact_manager.compact_threshold,
            'threshold_tokens': threshold,
            'needs_compaction': token_count > threshold,
            'percentage_used': (token_count / self.compact_manager.max_tokens) * 100 if self.compact_manager.max_tokens > 0 else 0
        }