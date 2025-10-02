
from asyncio import Queue
from threading import Thread
from openai import OpenAI
import json
import time
import yaml

from llm.llm_adapter import LLMAdapter, DeepSeekAdapter, OpenAIAdapter, GeminiAdapter, ClaudeAdapter

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
    def __init__(self, adapter: LLMAdapter, user_template=''):
        self.llm_adapter = adapter
        self.messages = []
        self.user_template = user_template
        self.set_user_template(user_template)

    def set_adapter(self, adapter: LLMAdapter):
        """
        Sets the current LLM adapter. This is how you switch providers.
        """
        self.llm_adapter = adapter
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
            
    def chat(self, message, stream=False, response_format = {'type':'json_object'}):
        """
        Delegates the chat request to the current LLM adapter.
        """
        self.add_message("user", message) # 先添加用户消息
        response = self.llm_adapter.chat(self.get_messages(), stream, response_format) # 传递整个消息列表
        
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
                print(f"Assistant's response added: {new_message}")
                return new_message
            except Exception as e:
                print(f"Failed to process or add assistant message: {e}")
        return response