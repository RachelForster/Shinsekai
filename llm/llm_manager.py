
from asyncio import Queue
import json
import threading
from datetime import datetime
from threading import Thread
from typing import Any, Dict, Generator, List, Optional, Union

from openai import OpenAI

from core.runtime.app_runtime import try_get_app_runtime
from i18n import tr
from llm.llm_adapter import LLMAdapter, DeepSeekAdapter, OpenAIAdapter, GeminiAdapter, ClaudeAdapter
from llm.compact_manager import CompactManager
from llm.tools.tool_manager import ToolManager
from llm.tools.tool_executor import ToolExecutor
from sdk.logging import get_logger

tool_manager = ToolManager()
tool_executor = ToolExecutor(tool_manager)
logger = get_logger(__name__)

# 模型后台加载完成时：清除冷却 + 推送聊天通知
def _on_tool_ready(group: str, message: str) -> None:
    tool_executor.clear_cooldown(group)
    if message:
        try:
            from core.runtime.app_runtime import try_get_app_runtime, tts_emit_to_ui_queue
            if try_get_app_runtime() is not None:
                tts_emit_to_ui_queue(
                    character_name="",
                    speech=message,
                    sprite="",
                    audio_path="",
                    is_system_message=True,
                )
        except Exception:
            pass

from sdk.tool_registry import set_tool_ready_callback
set_tool_ready_callback(_on_tool_ready)


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


def _extract_tool_call_raw_extras(tc_dict: dict) -> dict:
    """Extract provider-specific fields from a raw tool-call dict that the SDK drops.

    Returns keys ready to merge into the formatted tool call dict.
    Gemini nests thought_signature as ``extra_content.google.thought_signature``,
    and expects it sent back the same way."""
    extras: dict = {}
    ec = tc_dict.get("extra_content")
    if isinstance(ec, str) and ec.strip():
        try:
            import json as _json
            ec = _json.loads(ec)
        except Exception:
            pass
    if isinstance(ec, dict):
        extras["extra_content"] = ec
    return extras


def _tool_call_extras(tc, raw_tc_extra: dict | None = None) -> dict:
    """Extract provider-specific extra fields (e.g. extra_content for Gemini).

    Returns a dict to merge into the formatted call (shallow update)."""
    extras: dict = {}

    if isinstance(tc, dict):
        extras.update(_extract_tool_call_raw_extras(tc))
        if raw_tc_extra:
            extras.update(_extract_tool_call_raw_extras(raw_tc_extra))
        return extras

    # --- object path (OpenAI SDK) ---
    _raw = {}
    try:
        _raw = tc.to_dict() if callable(getattr(tc, "to_dict", None)) else {}
    except Exception:
        pass
    if not _raw:
        try:
            _raw = getattr(tc, "model_extra", None) or {}
        except Exception:
            pass
    if not _raw:
        try:
            _raw = {k: v for k, v in tc.__dict__.items() if not k.startswith("_")}
        except Exception:
            pass
    extras.update(_extract_tool_call_raw_extras(_raw))
    if raw_tc_extra:
        extras.update(_extract_tool_call_raw_extras(raw_tc_extra))
    return extras


def _raw_response_tool_call_extras(response) -> list[dict]:
    """Parse the raw HTTP response body to extract per-tool-call extra fields.

    Returns a list parallel to ``response.choices[0].message.tool_calls``."""
    out: list[dict] = []
    raw_text = ""
    for _meth in ("to_json", "model_dump_json"):
        _fn = getattr(response, _meth, None)
        if callable(_fn):
            try:
                raw_text = _fn()
                if raw_text:
                    break
            except Exception:
                pass
    if not raw_text:
        return out
    try:
        raw_data = json.loads(raw_text)
        for tc in raw_data.get("choices", [{}])[0].get("message", {}).get("tool_calls", []):
            out.append(_extract_tool_call_raw_extras(tc))
        if out and any(e for e in out):
            logger.info(f"_raw_response_tool_call_extras: found extras for {sum(1 for e in out if e)} tool call(s)")
    except Exception as e:
        logger.warning(f"_raw_response_tool_call_extras: failed to parse raw response: {e}")
    return out


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


def strip_orphaned_tool_calls(msgs: list) -> None:
    """纯函数，便于测试。清理不完整的 tool call 对：删孤立的 tool，补缺失的回执。"""
    if not msgs:
        return

    # 1. 找出孤立的 tool 消息（没有紧邻的 assistant 包含其 tool_call_id，或中间有 user 插入）
    orphan_tool_indices: list[int] = []
    for i, m in enumerate(msgs):
        if m.get("role") != "tool":
            continue
        tc_id = m.get("tool_call_id", "")
        ok = False
        for j in range(i - 1, -1, -1):
            r = msgs[j].get("role", "")
            if r == "user":
                break
            if r == "assistant" and msgs[j].get("tool_calls"):
                if any(tc.get("id") == tc_id for tc in msgs[j]["tool_calls"]):
                    ok = True
                break
        if not ok:
            orphan_tool_indices.append(i)

    # 2. 删孤立的 tool 消息（从后往前）
    for i in reversed(orphan_tool_indices):
        del msgs[i]

    # 3. 重建索引，收集 assistant(tool_calls)
    pending_calls: dict[int, list[dict]] = {}
    for i, m in enumerate(msgs):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            pending_calls[i] = [
                {"id": tc.get("id", ""), "name": tc.get("function", {}).get("name", "")}
                for tc in m["tool_calls"]
            ]

    # 4. 补上缺失的 tool 回执
    inserts: list[tuple[int, dict]] = []
    for ai, calls in pending_calls.items():
        seen_ids: set[str] = set()
        insert_at = ai + 1
        for j in range(ai + 1, len(msgs)):
            r = msgs[j].get("role", "")
            if r == "user":
                break
            if r == "tool":
                seen_ids.add(msgs[j].get("tool_call_id", ""))
                insert_at = j + 1
        for tc in calls:
            if tc["id"] not in seen_ids:
                inserts.append((insert_at, {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tc["name"],
                    "content": json.dumps({"error": "工具调用失败，请尝试其他方式"}),
                }))
                insert_at += 1
    for pos, msg in sorted(inserts, key=lambda x: x[0], reverse=True):
        msgs.insert(pos, msg)


class LLMManager:
    def __init__(
        self,
        adapter: LLMAdapter,
        user_template='',
        max_tokens: int = 128000,
        compact_threshold: float = 0.4,
        compact_target_ratio: float = 0.3,
        history_recent_messages: int = 20,
        max_tool_result_chars: int = 6000,
        max_active_tool_groups: int = 3,
        generation_config: Optional[Dict[str, Any]] = None
    ):
        self.llm_adapter = adapter
        self.messages = []
        self.user_template = user_template
        self.max_context_tokens = int(max_tokens)
        self.history_recent_messages = max(1, int(history_recent_messages))
        self.max_tool_result_chars = max(1, int(max_tool_result_chars))
        self.compact_manager = CompactManager(
            adapter,
            self.max_context_tokens,
            compact_threshold,
            compact_target_ratio=compact_target_ratio,
            recent_message_limit=self.history_recent_messages,
        )
        self.generation_config = generation_config or {}
        self.set_user_template(user_template)
        self.tools_definitions = tool_manager.get_definitions(groups="default")  # 初始仅 default 组
        self._active_tool_groups: list = ["default"]  # LRU: most recent first
        self._max_active_groups = max(1, int(max_active_tool_groups))
        self.tools_manager = tool_manager
        self.tool_executor = tool_executor
        self.last_token_estimate = {
            "system_prompt_tokens": 0,
            "history_tokens": 0,
            "tool_definition_tokens": 0,
            "estimated_total_tokens": 0,
        }
        self._chat_depth = 0
        
        # 设置日志
        self.logger = logger

    def _confirm_risky_tool(self, tool_name: str, risk: str, args_str: str) -> bool:
        """Request user confirmation for a risky tool. Returns True if confirmed."""
        if risk == "low":
            return True
        try:
            from core.runtime.app_runtime import try_get_app_runtime
            rt = try_get_app_runtime()
            if rt is None:
                return risk != "high"
            ui = rt.ui_update_manager
            # Parse arguments for a readable summary
            detail = ""
            try:
                args_obj = json.loads(args_str) if isinstance(args_str, str) else args_str
                if isinstance(args_obj, dict):
                    parts = []
                    for k, v in args_obj.items():
                        if k in ("content", "keyword"):
                            s = str(v)[:60]
                            parts.append(f"{k}={s}")
                        else:
                            parts.append(f"{k}={v}")
                    detail = " · ".join(parts[:6])
            except Exception:
                detail = args_str[:120] if args_str else ""
            summary = f"{tool_name}" + (f"\n{detail}" if detail else "")
            event = threading.Event()
            confirm_result: list[bool] = []
            if not hasattr(rt, '_pending_confirm'):
                rt._pending_confirm = {}
            rt._pending_confirm[tool_name] = (event, confirm_result)
            warn = "⚠️" if risk == "high" else "⚡"
            ui.post_options([f"{warn} 确认 {summary}", "取消"])
            resolved = event.wait(timeout=30.0)
            rt._pending_confirm.pop(tool_name, None)
            if not resolved:
                ui.post_notification(f"工具 {tool_name} 超时未确认，已取消")
                return False
            return bool(confirm_result and confirm_result[0])
        except Exception:
            return risk != "high"

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
        if role == "tool":
            content = self._prepare_tool_result_for_history(content)
        msg = {"role": role, "content": content}
        msg.update(kwargs)
        self.messages.append(msg)
        
        # --- Auto-Compact 逻辑 ---
        # 自动调用 compact_manager 检查 token 是否超限并执行压缩
        compacted_messages = self.compact_manager.auto_compact_if_needed(self.messages)
        if compacted_messages is not self.messages:
            before_tokens = self.compact_manager.count_tokens(self.messages)
            after_tokens = self.compact_manager.count_tokens(compacted_messages)
            self.logger.info(
                "Auto-compact triggered: messages %s -> %s, tokens %s -> %s",
                len(self.messages),
                len(compacted_messages),
                before_tokens,
                after_tokens,
            )
            self.messages = compacted_messages

    def clear_messages(self):
        self.messages = [{"role": "system", "content": self.user_template}]

    def _prepare_tool_result_for_history(self, result: Any) -> str:
        """Bound tool output before it becomes permanent prompt history."""
        if result is None:
            text = json.dumps({"status": "success", "result": "no return value"}, ensure_ascii=False)
        elif isinstance(result, str):
            text = result
        else:
            text = json.dumps(result, ensure_ascii=False, default=str)

        if len(text) <= self.max_tool_result_chars:
            return text

        head_chars = max(1, self.max_tool_result_chars // 2)
        tail_chars = max(0, self.max_tool_result_chars - head_chars)
        head = text[:head_chars]
        tail = text[-tail_chars:] if tail_chars else ""
        omitted_chars = max(0, len(text) - len(head) - len(tail))
        return json.dumps(
            {
                "truncated": True,
                "original_chars": len(text),
                "omitted_chars": omitted_chars,
                "head": head,
                "tail": tail,
            },
            ensure_ascii=False,
        )

    def _history_load_budget(self) -> int | None:
        if self.max_context_tokens <= 0:
            return None
        threshold_budget = int(self.max_context_tokens * self.compact_manager.compact_threshold)
        return min(threshold_budget, 50000)

    def _trim_loaded_history_if_needed(self, messages: list[dict]) -> list[dict]:
        budget = self._history_load_budget()
        if budget is None:
            return messages
        if self.compact_manager.count_tokens(messages) <= budget:
            return messages
        return self.compact_manager.trim_messages_to_budget(
            messages,
            token_budget=budget,
            recent_message_limit=self.history_recent_messages,
        )

    def _estimate_context_tokens(self, tools_defs: list[dict] | None) -> dict[str, int]:
        messages = self.get_messages()
        system_messages = [m for m in messages if m.get("role") == "system"]
        history_messages = [m for m in messages if m.get("role") != "system"]
        tool_definition_tokens = 0
        if tools_defs:
            tool_definition_tokens = self.compact_manager.count_text_tokens(
                json.dumps(tools_defs, ensure_ascii=False, separators=(",", ":"), default=str)
            )
        estimate = {
            "system_prompt_tokens": self.compact_manager.count_tokens(system_messages),
            "history_tokens": self.compact_manager.count_tokens(history_messages),
            "tool_definition_tokens": tool_definition_tokens,
        }
        estimate["estimated_total_tokens"] = sum(estimate.values())
        self.last_token_estimate = estimate
        self.logger.info(
            "Context token estimate: system=%s history=%s tools=%s total=%s",
            estimate["system_prompt_tokens"],
            estimate["history_tokens"],
            estimate["tool_definition_tokens"],
            estimate["estimated_total_tokens"],
        )
        self._post_context_token_estimate(estimate)
        return estimate

    def get_context_token_estimate(self) -> dict[str, int]:
        return dict(self.last_token_estimate)

    def _post_context_token_estimate(self, estimate: dict[str, int]) -> None:
        rt = try_get_app_runtime()
        ui = getattr(rt, "ui_update_manager", None) if rt is not None else None
        post = getattr(ui, "post_context_token_estimate", None)
        if post is None:
            return
        try:
            post(estimate)
        except Exception:
            self.logger.debug("Failed to post context token estimate to UI", exc_info=True)

    def _reset_active_tool_groups(self) -> None:
        self._active_tool_groups = ["default"]

    def _activate_tool_group(self, group: str) -> None:
        if not group:
            return
        if group in self._active_tool_groups:
            self._active_tool_groups.remove(group)
        self._active_tool_groups.insert(0, group)
        if "default" not in self._active_tool_groups:
            self._active_tool_groups.append("default")
        if len(self._active_tool_groups) > self._max_active_groups:
            if "default" in self._active_tool_groups and self._max_active_groups > 1:
                non_default = [g for g in self._active_tool_groups if g != "default"]
                self._active_tool_groups = non_default[: self._max_active_groups - 1] + ["default"]
            else:
                self._active_tool_groups = self._active_tool_groups[: self._max_active_groups]

    def _activate_tool_group_from_search(self, func_args: Any) -> None:
        try:
            parsed = json.loads(func_args) if isinstance(func_args, str) else func_args
            kw = (parsed.get("keyword") or "").strip().lower() if isinstance(parsed, dict) else ""
            if not kw:
                return
            for group in tool_manager.get_groups():
                if kw in group.lower():
                    self._activate_tool_group(group)
        except Exception:
            pass

    def _finish_chat_scope(self) -> None:
        self._chat_depth = max(0, self._chat_depth - 1)
        if self._chat_depth == 0:
            self._reset_active_tool_groups()

    def _stream_with_chat_scope(self, stream: Generator[Union[str, dict[str, str]], None, None]):
        try:
            yield from stream
        finally:
            self._finish_chat_scope()

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
            self.messages = list(new_messages)
            self._strip_orphaned_tool_calls()
            self.messages = self._trim_loaded_history_if_needed(self.messages)
            self.compact_manager.set_token_count(self.compact_manager.count_tokens(self.messages))
            print("Chat history has been updated.")
        else:
            print("Error: new_messages must be a list.")
            
    
    def chat(self, user_input: Optional[str], stream: bool = True, **kwargs) -> Union[Generator, str]:
        """
        统一入口：根据 stream 参数决定调用流式还是同步私有方法。

        ``include_local_time``（默认 True）：为本次 user 消息追加本机日期时间前缀，再写入对话历史。
        翻译、设定生成等非聊天调用请传 ``include_local_time=False``。
        """
        self._chat_depth += 1
        # 清理孤立的 tool_calls（必须在加 user 消息之前，否则占位 tool 回执会插在 user 后面）
        self._strip_orphaned_tool_calls()

        try:
            include_local_time = bool(kwargs.pop("include_local_time", True))
            if user_input:
                if include_local_time:
                    user_input = _prefix_user_text_with_local_time(user_input)
                self.add_message("user", user_input)

            if stream:
                return self._stream_with_chat_scope(self._chat_with_tools_stream(**kwargs))
            return self._chat_with_tools_sync(**kwargs)
        finally:
            if not stream:
                self._finish_chat_scope()

    def _strip_orphaned_tool_calls(self) -> None:
        """清理不完整的 tool call 对：删孤立的 tool，补缺失的回执。"""
        strip_orphaned_tool_calls(self.get_messages())

    # llm_manager.py 修正核心片段

    def _chat_with_tools_stream(self, **kwargs) -> Generator[Union[str, dict[str, str]], None, None]:
        tools_defs = tool_manager.get_definitions(groups=self._active_tool_groups)

        # Gemini's OpenAI-compatible streaming endpoint omits thought_signature from
        # tool call deltas. Fall back to non-streaming so the field is preserved.
        from config.config_manager import ConfigManager
        if tools_defs and ConfigManager().config.api_config.llm_provider == "Gemini":
            yield from self._chat_with_tools_sync(**kwargs)
            return

        merged_kwargs = dict(self.generation_config)
        merged_kwargs.update(kwargs)
        self._estimate_context_tokens(tools_defs)
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
                        if tc.index not in full_tool_calls:
                            full_tool_calls[tc.index] = tc
                        elif tc.function and tc.function.arguments:
                            if full_tool_calls[tc.index].function.arguments is None:
                                full_tool_calls[tc.index].arguments = ""
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
                call = {"id": t_id, "type": "function", "function": {"name": t_name, "arguments": t_args}}
                _extra = _tool_call_extras(tc)
                if _extra:
                    call["function"].update(_extra.pop("function", {}))
                    call.update(_extra)
                formatted_calls.append(call)

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
                    result = self.tool_executor.execute(
                        func_name, func_args,
                        risk_confirm=self._confirm_risky_tool,
                    )

                    # 动态扩展工具组：search_tools 被调用后，把匹配的组加入活跃列表
                    if func_name == "search_tools":
                        self._activate_tool_group_from_search(func_args)

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
        tools_defs = tool_manager.get_definitions(groups=self._active_tool_groups)
        merged_kwargs = dict(self.generation_config)
        merged_kwargs.update(kwargs)
        self._estimate_context_tokens(tools_defs)
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
            # Gemini 的 thought_signature 会被 OpenAI SDK Pydantic 模型丢弃，
            # 从原始 HTTP 响应体中捞出补齐
            _raw_extras = _raw_response_tool_call_extras(response)
            formatted_calls = []
            for i, tc in enumerate(tool_calls):
                t_name = tc.function.name if hasattr(tc, 'function') else tc.name
                t_args = tc.function.arguments if hasattr(tc, 'function') else tc.input
                call = {"id": tc.id, "type": "function", "function": {"name": t_name, "arguments": t_args}}
                _raw_extra = _raw_extras[i] if i < len(_raw_extras) else None
                _extra = _tool_call_extras(tc, _raw_extra)
                if _extra:
                    call["function"].update(_extra.pop("function", {}))
                    call.update(_extra)
                formatted_calls.append(call)

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
                    result = self.tool_executor.execute(
                        func_name, func_args,
                        risk_confirm=self._confirm_risky_tool,
                    )

                    # 动态扩展工具组：search_tools 被调用后，把匹配的组加入活跃列表
                    if func_name == "search_tools":
                        self._activate_tool_group_from_search(func_args)

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
