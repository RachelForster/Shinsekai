# llm_adapter.py
from abc import ABC, abstractmethod
from openai import OpenAI
import time
import json

class LLMAdapter(ABC):
    """
    Abstract Adapter for LLM services.
    This defines the standard interface for all LLM adapters.
    """
    def __init__(self, **kwargs):
        self.user_template = ''
    
    @abstractmethod
    def chat(self, messages: list, stream: bool = False, **kwargs):
        """
        Sends a message to the LLM and returns the response.
        """
        pass

    def set_user_template(self, template: str):
        """Sets the system prompt/user template."""
        self.user_template = template

# --- Concrete Adapters ---

class DeepSeekAdapter(LLMAdapter):
    def __init__(self, api_key=None, base_url=None, model="deepseek-chat", **kwargs):
        super().__init__(**kwargs)
        self.client = OpenAI(api_key=api_key)
        self.client.base_url = base_url
        self.model = model

    def chat(self, messages: list, stream: bool = False, **kwargs):
        """Sends a message to the DeepSeek LLM."""
        try:
            # 使用传入的 messages 参数
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=stream,
                response_format={'type': 'json_object'},
                **kwargs
            )
            return response
        except Exception as e:
            print(f"DeepSeek chat error: {e}")
            return None

class OpenAIAdapter(LLMAdapter):
    def __init__(self, api_key=None, base_url=None, model="gpt-3.5-turbo", **kwargs):
        super().__init__(**kwargs)
        self.client = OpenAI(api_key=api_key)
        self.client.base_url = base_url
        self.model = model
    
    def chat(self, messages: list, stream: bool = False, **kwargs):
        """Sends a message to the OpenAI LLM."""

        try:
            # 使用传入的 messages 参数
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=stream,
                **kwargs
            )
            return response
        except Exception as e:
            print(f"OpenAI chat error: {e}")
            return None

class GeminiAdapter(LLMAdapter):
    def __init__(self, api_key=None, model="gemini-pro", **kwargs):
        super().__init__(**kwargs)
        import genai
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)

    def chat(self, messages: list, stream: bool = False, **kwargs):
        """Sends a message to the Gemini LLM."""
        
        # messages to history format
        history = []
        for msg in messages:
            role = 'user' if msg['role'] == 'user' else 'model'
            history.append({"role": role, "parts": [msg["content"]]})

        try:
            # 使用传入的 messages 参数
            response = self.model.generate_content(
                history,
                stream=stream,
                **kwargs
            )
            return response
        except Exception as e:
            print(f"Gemini chat error: {e}")
            return None
    
    def set_user_template(self, template: str):
        """Sets the system prompt for Gemini."""
        # Gemini does not have a system prompt, so we can pass it as a first message or instruction
        self.user_template = template

class ClaudeAdapter(LLMAdapter):
    def __init__(self, api_key=None, model="claude-3-opus-20240229", **kwargs):
        super().__init__(**kwargs)
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.system_prompt = ''

    def set_user_template(self, template: str):
        """Sets the system prompt for Claude."""
        self.system_prompt = template

    def chat(self, messages: list, stream: bool = False, **kwargs):
        """Sends a message to the Claude LLM."""
        try:
            start_time = time.perf_counter()
            response = self.client.messages.create(
                model=kwargs.get("model", self.model),
                messages=messages, # 使用传入的 messages
                system=self.system_prompt,
                stream=stream,
                max_tokens=1024,
            )

            end_time = time.perf_counter()
            print(f"Claude response time: {end_time - start_time:0.4f} seconds")

            return response
        except Exception as e:
            print(f"Claude chat error: {e}")
            return None