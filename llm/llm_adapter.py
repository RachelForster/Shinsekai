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
        self.messages = []
        self.user_template = ''
    
    @abstractmethod
    def chat(self, message: str, stream: bool = False, **kwargs):
        """
        Sends a message to the LLM and returns the response.
        """
        pass

    def add_message(self, role, message):
        """Adds a message to the conversation history."""
        self.messages.append({"role": role, "content": message})

    def set_user_template(self, template: str):
        """Sets the system prompt/user template."""
        self.user_template = template
        self.messages = [{"role": "system", "content": self.user_template}]

# --- Concrete Adapters ---

class DeepSeekAdapter(LLMAdapter):
    def __init__(self, api_key=None, base_url=None, model="deepseek-chat", **kwargs):
        super().__init__(**kwargs)
        self.client = OpenAI(api_key=api_key)
        self.client.base_url = base_url
        self.model = model

    def chat(self, message: str, stream: bool = False, **kwargs):

        self.add_message("user", message)
        
        try:
            start_time = time.perf_counter()
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                response_format={'type': 'json_object'},
                stream=stream
            )
            
            if stream:
                return response
            
            end_time = time.perf_counter()
            print(f"DeepSeek response time: {end_time - start_time:0.4f} seconds")
            
            new_message = response.choices[0].message.content
            print(new_message)
            self.add_message("assistant", new_message)

            dialog = json.loads(new_message)
            return dialog['dialog']
        except Exception as e:
            print(f"DeepSeek request failed: {e}")
            return "您写的代码好像出错了呢，请检查一下, 出错的地方在chat方法里。"

class OpenAIAdapter(LLMAdapter):
    def __init__(self, api_key=None, base_url=None, **kwargs):
        super().__init__(**kwargs)
        self.client = OpenAI(api_key=api_key)
        self.client.base_url = base_url if base_url else "https://api.openai.com/v1"
        self.model = "gpt-4"

    def chat(self, message: str, stream: bool = False, **kwargs):
        self.add_message("user", message)
        
        try:
            start_time = time.perf_counter()
            response = self.client.chat.completions.create(
                model=kwargs.get("model", self.model),
                messages=self.messages,
                response_format={'type': 'json_object'},
                stream=stream
            )
            
            if stream:
                return response
            
            end_time = time.perf_counter()
            print(f"OpenAI response time: {end_time - start_time:0.4f} seconds")
            
            new_message = response.choices[0].message.content
            print(new_message)
            self.add_message("assistant", new_message)

            dialog = json.loads(new_message)
            return dialog['dialog']
        except Exception as e:
            print(f"OpenAI request failed: {e}")
            return "对不起，好像出了点问题。我的代码出错了呢。"
        
class GeminiAdapter(LLMAdapter):
    def __init__(self, api_key=None, model="gemini-1.5-pro", **kwargs):
        super().__init__(**kwargs)
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name=model)
        self.history = []

    def chat(self, message: str, stream: bool = False, **kwargs):
        """Sends a message to the Gemini LLM."""
        import json

        # Gemini's chat history is handled differently.
        # It's a sequence of user/model messages. The user template is not part of this history.
        
        # Start a new chat session with the user template as the initial context.
        chat_session = self.model.start_chat(history=[
            {"role": "user", "parts": [self.user_template]},
            {"role": "model", "parts": ["好的。"]}
        ])
        
        try:
            start_time = time.perf_counter()
            response = chat_session.send_message(message, stream=stream)
            
            if stream:
                return response
            
            end_time = time.perf_counter()
            print(f"Gemini response time: {end_time - start_time:0.4f} seconds")

            # Gemini returns a `GenerateContentResponse` object.
            new_message = response.text
            print(new_message)
            
            # Since Gemini doesn't have a `response_format` parameter,
            # you must rely on the prompt to instruct it to return JSON.
            dialog = json.loads(new_message)
            return dialog['dialog']
        except Exception as e:
            print(f"Gemini request failed: {e}")
            return "您写得代码好像出错了呢，请检查一下, 出错的地方在chat方法里。"
        
class ClaudeAdapter(LLMAdapter):
    def __init__(self, api_key=None, model="claude-3-opus-20240229", **kwargs):
        super().__init__(**kwargs)
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.system_prompt = ''

    def set_user_template(self, template: str):
        """Sets the system prompt for Claude."""
        self.system_prompt = template
        self.messages = [] # Reset messages

    def chat(self, message: str, stream: bool = False, **kwargs):
        """Sends a message to the Claude LLM."""
        import time
        import json

        self.add_message("user", message)

        try:
            start_time = time.perf_counter()
            response = self.client.messages.create(
                model=kwargs.get("model", self.model),
                messages=self.messages,
                system=self.system_prompt,
                stream=stream,
                max_tokens=1024,
            )

            if stream:
                return response

            end_time = time.perf_counter()
            print(f"Claude response time: {end_time - start_time:0.4f} seconds")

            new_message = response.content[0].text
            print(new_message)
            self.add_message("assistant", new_message)

            dialog = json.loads(new_message)
            return dialog['dialog']
        except Exception as e:
            print(f"Claude request failed: {e}")
            return "您写得代码好像出错了呢，请检查一下, 出错的地方在chat方法里。"