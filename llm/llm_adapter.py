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

class DeepSeekAdapter(LLMAdapter):
    def __init__(self, api_key=None, base_url=None, model="deepseek-chat", **kwargs):
        super().__init__(**kwargs)
        self.client = OpenAI(api_key=api_key)
        self.client.base_url = base_url
        self.model = model

    def chat(self, messages: list, stream: bool = False, response_format={'type': 'json_object'}, **kwargs):
        """Sends a message to the DeepSeek LLM."""
        try:
            # 使用传入的 messages 参数
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=stream,
                response_format=response_format,
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
    
    def chat(self, messages: list, stream: bool = False, response_format={'type': 'json_object'}, **kwargs):
        """Sends a message to the OpenAI LLM."""
        try:
            # 使用传入的 messages 参数
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=stream,
                response_format=response_format,
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
    def __init__(self, api_key=None, base_url=None, model="claude-3-5-sonnet-20240620", **kwargs):
        super().__init__(**kwargs)
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        self.model = model
        self.system_prompt = ''

    def set_user_template(self, template: str):
        self.system_prompt = template

    def _clean_messages(self, messages: list):
        """
        核心修复逻辑：确保消息完全符合 Claude API 规范
        """
        api_messages = []
        system_content = self.system_prompt
        
        # 1. 提取最新的 system 消息
        for msg in messages:
            if msg.get("role") == "system":
                system_content = msg.get("content", "")

        # 2. 过滤并转换 user/assistant/tool 消息
        raw_msgs = [m for m in messages if m.get("role") != "system"]
        
        for msg in raw_msgs:
            role = msg.get("role")
            content = msg.get("content") or "" # 确保不是 None
            
            # 处理 Assistant 消息 (含工具调用)
            if role == "assistant":
                anthropic_content = []
                if content.strip(): # 只有不为空才添加文本块
                    anthropic_content.append({"type": "text", "text": content})
                
                if "tool_calls" in msg and msg["tool_calls"]:
                    for tc in msg["tool_calls"]:
                        # 转换参数格式
                        t_args = tc.get("function", {}).get("arguments") if "function" in tc else tc.get("input")
                        if isinstance(t_args, str):
                            try: t_args = json.loads(t_args)
                            except: t_args = {}
                        
                        anthropic_content.append({
                            "type": "tool_use",
                            "id": tc.get("id"),
                            "name": tc.get("function", {}).get("name") if "function" in tc else tc.get("name"),
                            "input": t_args
                        })
                
                # 如果既没有文字也没有工具，Claude 会报错，补一个占位符
                if not anthropic_content:
                    anthropic_content.append({"type": "text", "text": "..."})
                    
                api_messages.append({"role": "assistant", "content": anthropic_content})

            # 处理 User 消息
            elif role == "user":
                if content.strip():
                    api_messages.append({"role": "user", "content": content})

            # 处理 Tool 结果 (映射为 User 角色)
            elif role == "tool":
                api_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id"),
                        "content": str(content) if content else "Success"
                    }]
                })

        # 3. 合并连续的同角色消息 (Claude 禁止连续两个 user 或 assistant)
        final_msgs = []
        for m in api_messages:
            if final_msgs and final_msgs[-1]["role"] == m["role"]:
                # 如果角色相同，合并 content
                if isinstance(final_msgs[-1]["content"], str) and isinstance(m["content"], str):
                    final_msgs[-1]["content"] += "\n" + m["content"]
                else:
                    # 如果是列表格式（含工具），合并列表
                    if isinstance(final_msgs[-1]["content"], str):
                        final_msgs[-1]["content"] = [{"type": "text", "text": final_msgs[-1]["content"]}]
                    if isinstance(m["content"], str):
                        m["content"] = [{"type": "text", "text": m["content"]}]
                    final_msgs[-1]["content"].extend(m["content"])
            else:
                final_msgs.append(m)

        return system_content, final_msgs

    def chat(self, messages: list, stream: bool = False, **kwargs):
        try:
            system_msg, cleaned_msgs = self._clean_messages(messages)
            
            # 如果没有消息，Claude 也会报错
            if not cleaned_msgs:
                cleaned_msgs = [{"role": "user", "content": "Hello"}]

            print("Cleaned Messages:", cleaned_msgs)
            # 转换工具定义
            tools = kwargs.get("tools")
            anthropic_tools = []
            if tools:
                for t in tools:
                    f = t.get("function", t)
                    anthropic_tools.append({
                        "name": f["name"],
                        "description": f.get("description", ""),
                        "input_schema": f["parameters"]
                    })

            if stream:
                return self.client.messages.stream(
                    model=self.model,
                    system=system_msg,
                    messages=cleaned_msgs,
                    tools=anthropic_tools if anthropic_tools else None,
                    max_tokens=4096
                )
            else:
                return self.client.messages.create(
                    model=self.model,
                    system=system_msg,
                    messages=cleaned_msgs,
                    tools=anthropic_tools if anthropic_tools else None,
                    max_tokens=4096
                )
        except Exception as e:
            print(f"Claude API Error: {e}")
            return None