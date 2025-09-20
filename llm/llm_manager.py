
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
        'deepseek': DeepSeekAdapter,
        'openai': OpenAIAdapter,
        'gemini': GeminiAdapter,
        'claude': ClaudeAdapter,
    }

    @staticmethod
    def create_adapter(adapter_name: str, **kwargs) -> LLMAdapter:
        """Creates and returns an LLMAdapter instance based on the given name."""
        adapter_class = LLMAdapterFactory._adapters.get(adapter_name.lower())
        
        if not adapter_class:
            raise ValueError(f"Unsupported LLM adapter: '{adapter_name}'. Supported adapters are: {list(LLMAdapterFactory._adapters.keys())}")
        
        try:
            return adapter_class(**kwargs)
        except TypeError as e:
            print(f"Error creating adapter '{adapter_name}'. Check the required arguments.")
            raise e


class LLMManager:
    def __init__(self, adapter: LLMAdapter, user_template=''):
        self.llm_adapter = adapter
        self.llm_adapter.set_user_template(user_template)

    def set_adapter(self, adapter: LLMAdapter):
        """
        Sets the current LLM adapter. This is how you switch providers.
        """
        self.llm_adapter = adapter
        print(f"LLM adapter switched to {type(self.llm_adapter).__name__}.")

    def chat(self, message, stream=False):
        """
        Delegates the chat request to the current LLM adapter.
        """
        return self.llm_adapter.chat(message, stream)
    
    def add_message(self, role, message):
        """
        Adds a message to the conversation history via the adapter.
        """
        self.llm_adapter.add_message(role, message)
