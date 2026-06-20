# compact_manager.py
import copy
import json
import math
import tiktoken
from typing import List, Dict, Any
import logging

from config.schema import clamp_compact_target_ratio
from sdk.hooks import BeforeCompactContext, PluginHookDispatcher, PluginHookEvent

logger = logging.getLogger(__name__)

class CompactManager:
    """管理记忆压缩的类"""
    
    SUMMARY_MARKERS = ("历史对话总结", "历史摘要", "较早历史已省略")

    def __init__(
        self,
        llm_adapter,
        max_tokens: int = 128000,
        compact_threshold: float = 0.4,
        compact_target_ratio: float = 0.3,
        recent_message_limit: int = 20,
        compact_summary_max_tokens: int = 2048,
        hook_dispatcher: PluginHookDispatcher | None = None,
    ):
        """
        初始化CompactManager
        
        Args:
            llm_adapter: LLM适配器实例
            max_tokens: 模型最大token数
            compact_threshold: 触发压缩的阈值（0.4表示达到40%时触发）
            compact_target_ratio: 压缩后目标上下文占比
            recent_message_limit: 压缩/截断时保留的最近消息数量
            compact_summary_max_tokens: 历史总结自身的最大 token 预算
        """
        self.llm_adapter = llm_adapter
        self.max_tokens = max_tokens
        self.compact_threshold = compact_threshold
        self.compact_target_ratio = clamp_compact_target_ratio(
            self.compact_threshold,
            compact_target_ratio,
        )
        self.recent_message_limit = max(1, int(recent_message_limit))
        self.compact_summary_max_tokens = max(128, int(compact_summary_max_tokens))
        self.hook_dispatcher = hook_dispatcher
        self.num_tokens = 0
        
        # 尝试使用tiktoken进行token计数
        try:
            # 对于DeepSeek，使用cl100k_base编码
            self.encoder = tiktoken.get_encoding("cl100k_base")
        except:
            self.encoder = None
            logger.warning("tiktoken not available, using approximate token counting")
    

    def set_token_count(self, token_count: int):
        """直接设置当前token计数"""
        self.num_tokens = token_count

    def count_text_tokens(self, text: str) -> int:
        """计算任意文本的估算 token 数。"""
        text = text or ""
        if self.encoder:
            return len(self.encoder.encode(text))
        return int(len(text) / 1.5)

    def _message_token_text(self, message: Dict[str, Any]) -> str:
        """把完整消息结构转成稳定文本，避免漏算 tool_calls 等字段。"""
        try:
            return json.dumps(message, ensure_ascii=False, separators=(",", ":"), default=str)
        except Exception:
            return str(message)

    def count_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """计算消息列表的token数量"""
        total_tokens = 0
        for message in messages:
            total_tokens += self.count_text_tokens(self._message_token_text(message)) + 4
        return total_tokens
    
    def increase_token_count(self, new_messages: List[Dict[str, Any]], token_usage: int = 0):
        """增加当前token计数"""
        if token_usage > 0:
            self.num_tokens = token_usage
        else:
            self.num_tokens += self.count_tokens(new_messages)
        return self.num_tokens

    def needs_compaction(self, messages: List[Dict[str, Any]], token_usage: int = 0) -> bool:
        """检查是否需要压缩记忆"""
        if self.max_tokens <= 0:
            self.num_tokens = self.count_tokens(messages)
            return False
        # 每次按完整消息重算，避免增量统计在工具调用和历史替换后漂移。
        self.num_tokens = token_usage if token_usage > 0 else self.count_tokens(messages)
        token_count = self.num_tokens
        threshold_tokens = self.max_tokens * self.compact_threshold

        return token_count > threshold_tokens

    def _is_summary_message(self, message: Dict[str, Any]) -> bool:
        content = str(message.get("content") or "")
        return any(marker in content for marker in self.SUMMARY_MARKERS)

    def _split_system(self, messages: List[Dict[str, Any]]) -> tuple[Dict[str, Any] | None, List[Dict[str, Any]]]:
        if messages and messages[0].get("role") == "system":
            return messages[0], messages[1:]
        return None, list(messages)

    def _recent_slice_start(self, messages: List[Dict[str, Any]], limit: int | None = None) -> int:
        if not messages:
            return 0
        limit = self.recent_message_limit if limit is None else max(1, int(limit))
        start = max(0, len(messages) - limit)
        # Do not start on a tool result without its assistant tool_call owner.
        while start > 0 and messages[start].get("role") == "tool":
            tc_id = messages[start].get("tool_call_id")
            owner = None
            for idx in range(start - 1, -1, -1):
                msg = messages[idx]
                if msg.get("role") == "user":
                    break
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    if any(tc.get("id") == tc_id for tc in msg.get("tool_calls", [])):
                        owner = idx
                    break
            if owner is None:
                start += 1
                if start >= len(messages):
                    return len(messages)
                continue
            start = owner
        return start

    def _latest_summary(self, messages: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        for message in reversed(messages):
            if self._is_summary_message(message):
                return message
        return None

    def _omitted_history_message(self) -> Dict[str, str]:
        return {
            "role": "user",
            "content": "【历史摘要】较早历史已省略。请基于保留的系统设定、历史摘要和最近对话继续。",
        }

    def _summary_message(self, content: str) -> Dict[str, str]:
        return {
            "role": "user",
            "content": f"【历史对话总结】以下是之前对话的压缩总结：\n{content}\n\n请基于这个上下文继续对话。",
        }

    def _limit_summary(self, content: str) -> str:
        if self.count_text_tokens(content) <= self.compact_summary_max_tokens:
            return content
        # Conservative char-level fallback keeps this deterministic and provider-neutral.
        approx_chars = max(200, self.compact_summary_max_tokens * 2)
        return content[:approx_chars].rstrip() + "\n...[summary truncated]"

    def trim_messages_to_budget(
        self,
        messages: List[Dict[str, Any]],
        token_budget: int | None = None,
        recent_message_limit: int | None = None,
        summary_message: Dict[str, Any] | None = None,
    ) -> List[Dict[str, Any]]:
        """确定性裁剪历史，不调用 LLM。"""
        if not messages:
            return messages

        system_message, body = self._split_system(messages)
        if not body:
            return messages

        start = self._recent_slice_start(body, recent_message_limit)
        recent_messages = body[start:]
        latest_summary = summary_message or self._latest_summary(body[:start])
        if summary_message is not None:
            recent_messages = [m for m in recent_messages if m is not summary_message]
        compacted: List[Dict[str, Any]] = []
        if system_message:
            compacted.append(system_message)
        compacted.append(latest_summary or self._omitted_history_message())
        compacted.extend(recent_messages)

        if token_budget is None or token_budget <= 0:
            return compacted

        # If still over budget, drop complete old recent units until bounded.
        while len(recent_messages) > 1 and self.count_tokens(compacted) > token_budget:
            drop_count = 1
            if recent_messages[0].get("role") == "assistant" and recent_messages[0].get("tool_calls"):
                expected_ids = {tc.get("id") for tc in recent_messages[0].get("tool_calls", [])}
                for msg in recent_messages[1:]:
                    if msg.get("role") != "tool":
                        break
                    drop_count += 1
                    expected_ids.discard(msg.get("tool_call_id"))
                    if not expected_ids:
                        break
            recent_messages = recent_messages[drop_count:]
            compacted = ([] if system_message is None else [system_message])
            compacted.append(latest_summary or self._omitted_history_message())
            compacted.extend(recent_messages)

        return compacted
    
    def compact_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        压缩消息历史
        
        Args:
            messages: 原始消息列表
            
        Returns:
            压缩后的消息列表
        """
        if len(messages) <= 2:  # 只有system消息和少量对话，不需要压缩
            return messages
        
        # logger.info(f"Starting compaction of {len(messages)} messages")
        
        system_message, messages_to_compact = self._split_system(messages)
        
        if len(messages_to_compact) <= 1:
            return messages

        recent_start = self._recent_slice_start(messages_to_compact)
        older_messages = messages_to_compact[:recent_start]
        recent_messages = messages_to_compact[recent_start:]
        if not older_messages and self.needs_compaction(messages):
            recent_start = max(1, len(messages_to_compact) - 1)
            older_messages = messages_to_compact[:recent_start]
            recent_messages = messages_to_compact[recent_start:]
        if not older_messages:
            return messages

        if (
            self.hook_dispatcher is not None
            and self.hook_dispatcher.has_hooks(PluginHookEvent.BEFORE_COMPACT)
        ):
            self.hook_dispatcher.dispatch_before_compact(
                BeforeCompactContext(
                    messages=copy.deepcopy(messages),
                    older_messages=copy.deepcopy(older_messages),
                    recent_messages=copy.deepcopy(recent_messages),
                )
            )
        
        # 准备压缩提示
        compact_prompt = self._create_compact_prompt(older_messages)
        
        try:
            # 使用LLM进行压缩
            compacted_content = self._limit_summary(self._call_llm_for_compaction(compact_prompt))
            
            # 构建压缩后的消息列表
            compacted_messages = []
            if system_message:
                compacted_messages.append(system_message)
            
            # 添加压缩后的总结消息
            compacted_messages.append(self._summary_message(compacted_content))
            
            # 保留最后几条消息以保持对话连续性
            compacted_messages.extend(recent_messages)

            if self.max_tokens > 0:
                target_budget = max(1, math.floor(self.max_tokens * self.compact_target_ratio))
                compacted_messages = self.trim_messages_to_budget(
                    compacted_messages,
                    token_budget=target_budget,
                    recent_message_limit=self.recent_message_limit,
                    summary_message=compacted_messages[1 if system_message else 0],
                )
            
            # logger.info(f"Compaction completed. Original: {len(messages)} messages, Compacted: {len(compacted_messages)} messages")
            self.num_tokens = self.count_tokens(compacted_messages)
            return compacted_messages
            
        except Exception as e:
            logger.error(f"Compaction failed: {e}")
            token_budget = None
            if self.max_tokens > 0:
                token_budget = max(1, math.floor(self.max_tokens * self.compact_target_ratio))
            fallback = self.trim_messages_to_budget(messages, token_budget=token_budget)
            self.num_tokens = self.count_tokens(fallback)
            return fallback
    
    def _create_compact_prompt(self, messages: List[Dict[str, Any]]) -> str:
        """创建压缩提示"""
        prompt = """请将以下对话历史压缩成一个简洁的总结。总结应该：
1. 保留关键信息、重要决定和主要话题
2. 忽略无关紧要的细节和重复内容
3. 保持时间顺序和逻辑连贯性
4. 用中文总结，保持客观准确

对话历史：
"""
        
        for i, message in enumerate(messages):
            role = message.get("role", "")
            if role == "user":
                role = "用户"
            elif role == "assistant":
                role = "助手"
            elif role == "tool":
                role = f"工具:{message.get('name', '')}"
            content = message.get('content', '')
            prompt += f"\n{role}: {content}"
        
        prompt += "\n\n请提供对话总结："
        
        return prompt
    
    def _call_llm_for_compaction(self, prompt: str) -> str:
        """调用LLM进行压缩"""
        # 创建压缩专用的消息列表
        compact_messages = [
            {'role': 'system', 'content': '你是一个专业的对话总结助手，擅长将长对话压缩成简洁准确的总结。请保留用户的重要信息和目前的对话话题。'},
            {'role': 'user', 'content': prompt}
        ]
        
        # 调用LLM
        response = self.llm_adapter.chat(compact_messages, stream=False, response_format={'type': 'text'})
        
        if response:
            try:
                if hasattr(response, 'choices') and hasattr(response.choices[0], 'message'):
                    return response.choices[0].message.content
                elif hasattr(response, 'text'):
                    return response.text
                elif hasattr(response, 'content'):
                    return response.content[0].text
                else:
                    return str(response)
            except Exception as e:
                logger.error(f"Failed to extract response content: {e}")
                return "压缩失败，请参考原始对话历史。"
        
        return "压缩失败，请参考原始对话历史。"
    
    def auto_compact_if_needed(self, messages: List[Dict[str, str]], token_usage: int = 0) -> List[Dict[str, str]]:
        """自动检查并压缩消息（如果需要）"""
        # logger.info("num tokens before compaction check: {}".format(self.num_tokens))
        if self.needs_compaction(messages, token_usage):
            logger.info("Token limit approaching, performing automatic compaction...")
            return self.compact_messages(messages)
        return messages
