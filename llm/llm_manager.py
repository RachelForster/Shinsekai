
from asyncio import Queue
import json
import logging
from datetime import datetime
from threading import Thread
from typing import Any, Dict, Generator, List, Optional, Union

from openai import OpenAI

from core.runtime.app_runtime import try_get_app_runtime
from i18n import tr
from llm.llm_adapter import LLMAdapter, DeepSeekAdapter, OpenAIAdapter, GeminiAdapter, ClaudeAdapter
from llm.compact_manager import CompactManager
from llm.tools.tool_manager import ToolManager

tool_manager = ToolManager()
logger = logging.getLogger(__name__)


# 流式输出中非正文的片段（供 LLMWorker 显示思考过程，且不混入 JSON 解析缓冲区）
STREAM_REASONING_DELTA_KEY = "reasoning_delta"

def _prefix_user_text_with_local_time(text: str) -> str:
    """为发送给模型的用户正文加上本机本地时间（供模型感知「何时」发送）。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"[本地时间 {ts}]\n{text}"


def _notify_tool_call_hint(tool_name: str) -> None:
    """桌面主程序已注册 AppRuntime 时，将当前调用的工具名显示在输入框占位提示上。"""
    rt = try_get_app_runtime()
    if rt is None:
        return
    try:
        rt.ui_update_manager.post_busy_bar(
            tr("main.notify_tool_calling", name=tool_name),
            4.0
        )
    except Exception:
        pass


def _deepseek_reasoning_message_kwargs(adapter: LLMAdapter, reasoning_text: str) -> dict[str, str]:
    """DeepSeek 思考模式 + 含 tool_calls 的 assistant 轮次必须把 reasoning_content 一并写回消息。"""
    if not (reasoning_text or "").strip():
        return {}
    if not isinstance(adapter, DeepSeekAdapter):
        return {}
    if not getattr(adapter, "thinking_enabled", False):
        return {}
    return {"reasoning_content": reasoning_text}


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
    def __init__(
        self,
        adapter: LLMAdapter,
        user_template='',
        max_tokens: int = 128000,
        compact_threshold: float = 0.9,
        generation_config: Optional[Dict[str, Any]] = None
    ):
        self.llm_adapter = adapter
        self.messages = []
        self.user_template = user_template
        self.compact_manager = CompactManager(adapter, max_tokens, compact_threshold)
        self.generation_config = generation_config or {}
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

    def _persist_plain_assistant_turn(self, content: str, reasoning: str) -> None:
        """无 tool_calls 的一轮：把 assistant 正文与（若存在）思考写入历史，供下游 API 与存档。"""
        extra = _deepseek_reasoning_message_kwargs(self.llm_adapter, reasoning)
        if not (content or "").strip() and not extra:
            return
        self.add_message("assistant", content or "", **extra)

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
            
    
    def chat(self, user_input: Optional[str], stream: bool = True, **kwargs) -> Union[Generator, str]:
        """
        统一入口：根据 stream 参数决定调用流式还是同步私有方法。

        ``include_local_time``（默认 True）：为本次 user 消息追加本机日期时间前缀，再写入对话历史。
        翻译、设定生成等非聊天调用请传 ``include_local_time=False``。
        """
        include_local_time = bool(kwargs.pop("include_local_time", True))
        if user_input:
            if include_local_time:
                user_input = _prefix_user_text_with_local_time(user_input)
            self.add_message("user", user_input)

        if stream:
            return self._chat_with_tools_stream(**kwargs)
        else:
            return self._chat_with_tools_sync(**kwargs)

    # llm_manager.py 修正核心片段

    def _chat_with_tools_stream(self, **kwargs) -> Generator[Union[str, dict[str, str]], None, None]:
        tools_defs = tool_manager.get_definitions()
        merged_kwargs = dict(self.generation_config)
        merged_kwargs.update(kwargs)
        response_stream = self.llm_adapter.chat(
            messages=self.get_messages(), stream=True, 
            tools=tools_defs if tools_defs else None, **merged_kwargs
        )
        if response_stream is None: return

        # self.logger.info(f"Tools definitions: {tools_defs}")
        
        full_tool_calls = {}
        has_tool_use = False
        collected_content = ""
        collected_reasoning = ""

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
                r_part = getattr(delta, "reasoning_content", None)
                if r_part:
                    collected_reasoning += r_part
                    yield {STREAM_REASONING_DELTA_KEY: r_part}
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

            # --- 关键：必须先添加 Assistant 消息（DeepSeek 思考模式须含 reasoning_content） ---
            assistant_kw = _deepseek_reasoning_message_kwargs(self.llm_adapter, collected_reasoning)
            self.add_message("assistant", collected_content, tool_calls=formatted_calls, **assistant_kw)

            # --- 然后添加 Tool 结果消息 ---
            for call in formatted_calls:
                try:
                    func_name = call['function']['name']
                    func_args = call['function']['arguments']
                    if isinstance(func_args, str):
                        if not func_args.strip():
                            func_args = "{}"  # 修正为空 JSON 对象字符串

                    _notify_tool_call_hint(func_name)
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
        else:
            self._persist_plain_assistant_turn(collected_content, collected_reasoning)

    def _chat_with_tools_sync(self, **kwargs) -> str:
        tools_defs = tool_manager.get_definitions()
        merged_kwargs = dict(self.generation_config)
        merged_kwargs.update(kwargs)
        response = self.llm_adapter.chat(
            messages=self.get_messages(), stream=False,
            tools=tools_defs if tools_defs else None, **merged_kwargs
        )
        if not response: return ""

        content = ""
        tool_calls = []
        reasoning = ""

        if isinstance(self.llm_adapter, ClaudeAdapter):
            for block in response.content:
                if block.type == 'text': content += block.text
                elif block.type == 'tool_use': tool_calls.append(block)
        else:
            message = response.choices[0].message
            content = message.content or ""
            tool_calls = getattr(message, 'tool_calls', []) or []
            reasoning = getattr(message, "reasoning_content", None) or ""

        if tool_calls:
            formatted_calls = []
            for tc in tool_calls:
                t_name = tc.function.name if hasattr(tc, 'function') else tc.name
                t_args = tc.function.arguments if hasattr(tc, 'function') else tc.input
                formatted_calls.append({"id": tc.id, "type": "function", "function": {"name": t_name, "arguments": t_args}})

            # --- 关键：先 Assistant 再 Tool ---
            assistant_sync_kw = _deepseek_reasoning_message_kwargs(self.llm_adapter, reasoning)
            self.add_message("assistant", content, tool_calls=formatted_calls, **assistant_sync_kw)
            for call in formatted_calls:
                try:
                    func_name = call['function']['name']
                    func_args = call['function']['arguments']
                    if isinstance(func_args, str):
                        if not func_args.strip():
                            func_args = "{}"  # 修正为空 JSON 对象字符串

                    _notify_tool_call_hint(func_name)
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
            self._persist_plain_assistant_turn(content, reasoning)
            return content