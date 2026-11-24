"""LLM context compaction."""
from collections.abc import Callable, Mapping
import copy
import json
import math
import tiktoken
from typing import List, Dict, Any
import logging

from ai.llm.template.core import TemplateContext
from ai.llm.template.integrations.localization import LocaleInput, resolve_dynamic_locale
from ai.llm.template.session import (
    COMPACT_PROMPT_SPEC,
    CompactPromptContext,
    CompactTranscriptTurn,
    render_compact_failure_fallback,
    render_omitted_history_notice,
)
from config.schema import clamp_compact_target_ratio
from core.chat_history.models import (
    COMPACT_SUMMARY_SOURCE,
    COMPACT_UP_TO_SEQ_KEY,
    SUMMARY_MARKERS as _HISTORY_SUMMARY_MARKERS,
    build_compact_summary_message,
    is_compact_summary_message,
)
from sdk.hooks import BeforeCompactContext, PluginHookDispatcher, PluginHookEvent
from sdk.lang import LocaleCode

logger = logging.getLogger(__name__)

class CompactManager:
    """管理记忆压缩的类"""

    SUMMARY_MARKERS = _HISTORY_SUMMARY_MARKERS

    def __init__(
        self,
        llm_adapter,
        max_tokens: int = 128000,
        compact_threshold: float = 0.4,
        compact_target_ratio: float = 0.3,
        recent_message_limit: int = 20,
        compact_summary_max_tokens: int = 2048,
        hook_dispatcher: PluginHookDispatcher | None = None,
        *,
        session_id: str = "",
        resolve_message_seq: Callable[[Mapping[str, Any]], int | None] | None = None,
        on_checkpoint: Callable[[int, str], None] | None = None,
        locale: LocaleInput = None,
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
        self.session_id = str(session_id or "")
        self.resolve_message_seq = resolve_message_seq
        self.on_checkpoint = on_checkpoint
        self.locale = locale
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
        def scrub(value: Any) -> Any:
            if isinstance(value, dict):
                if value.get("type") == "local_image":
                    return {
                        key: "[embedded image data omitted]" if key == "data" else scrub(item)
                        for key, item in value.items()
                    }
                return {key: scrub(item) for key, item in value.items()}
            if isinstance(value, list):
                return [scrub(item) for item in value]
            return value

        try:
            return json.dumps(scrub(message), ensure_ascii=False, separators=(",", ":"), default=str)
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
        return is_compact_summary_message(message)

    def _max_seq_for_messages(self, messages: List[Dict[str, Any]]) -> int | None:
        seqs: list[int] = []
        for msg in messages:
            if not isinstance(msg, Mapping):
                continue
            resolved = (
                self.resolve_message_seq(msg)
                if callable(self.resolve_message_seq)
                else None
            )
            if resolved is None:
                raw_seq = msg.get("_turn_seq")
                if raw_seq is None:
                    raw_seq = msg.get(COMPACT_UP_TO_SEQ_KEY)
                if raw_seq is not None:
                    try:
                        resolved = int(raw_seq)
                    except (TypeError, ValueError):
                        resolved = None
            if resolved is not None and int(resolved) > 0:
                seqs.append(int(resolved))
        return max(seqs) if seqs else None

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

    def _active_locale(self) -> LocaleCode:
        return resolve_dynamic_locale(self.locale)

    def _omitted_history_message(self, *, up_to_seq: int | None = None) -> Dict[str, Any]:
        msg: Dict[str, Any] = {
            "role": "user",
            "source": COMPACT_SUMMARY_SOURCE,
            "content": render_omitted_history_notice(locale=self._active_locale()),
        }
        if up_to_seq is not None:
            msg[COMPACT_UP_TO_SEQ_KEY] = int(up_to_seq)
        return msg

    def _summary_message(self, content: str, *, up_to_seq: int | None = None) -> Dict[str, Any]:
        return build_compact_summary_message(
            content,
            up_to_seq=up_to_seq,
            locale=self._active_locale(),
        )

    def _limit_summary(self, content: str) -> str:
        if self.count_text_tokens(content) <= self.compact_summary_max_tokens:
            return content
        # Conservative char-level fallback keeps this deterministic and provider-neutral.
        approx_chars = max(200, self.compact_summary_max_tokens * 2)
        return content[:approx_chars].rstrip() + "\n...[summary truncated]"

    @staticmethod
    def _oldest_unit_length(recent_messages: List[Dict[str, Any]]) -> int:
        if not recent_messages:
            return 0
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
        return drop_count

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
            drop_count = self._oldest_unit_length(recent_messages)
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

        system_message, messages_to_compact = self._split_system(messages)

        if len(messages_to_compact) <= 1:
            return messages

        recent_start = self._recent_slice_start(messages_to_compact)
        older_messages = list(messages_to_compact[:recent_start])
        recent_messages = list(messages_to_compact[recent_start:])
        over_threshold = self.needs_compaction(messages)
        target_budget = (
            max(1, math.floor(self.max_tokens * self.compact_target_ratio))
            if self.max_tokens > 0
            else None
        )

        # Ensure older_messages folds at least one real non-summary message and
        # pre-shifts messages that cannot fit into target_budget so BEFORE_COMPACT
        # and LLM summarization cover every evicted turn without sequence gaps.
        if over_threshold:
            while len(recent_messages) > 1:
                step = self._oldest_unit_length(recent_messages)
                if step <= 0 or step >= len(recent_messages):
                    break
                only_summaries = (
                    not older_messages
                    or all(self._is_summary_message(m) for m in older_messages)
                )
                base_window = (
                    ([system_message] if system_message else [])
                    + [self._summary_message("摘要", up_to_seq=self._max_seq_for_messages(older_messages))]
                    + recent_messages
                )
                over_target = (
                    target_budget is not None
                    and self.count_tokens(base_window) > target_budget
                )
                if not only_summaries and not over_target:
                    break
                older_messages.extend(recent_messages[:step])
                recent_messages = recent_messages[step:]

        if not older_messages or all(self._is_summary_message(m) for m in older_messages):
            return messages

        up_to_seq = self._max_seq_for_messages(older_messages)

        extra_instructions: tuple[str, ...] = ()
        if (
            self.hook_dispatcher is not None
            and self.hook_dispatcher.has_hooks(PluginHookEvent.BEFORE_COMPACT)
        ):
            before_ctx = BeforeCompactContext(
                messages=copy.deepcopy(messages),
                older_messages=copy.deepcopy(older_messages),
                recent_messages=copy.deepcopy(recent_messages),
                session_id=self.session_id,
                up_to_seq=up_to_seq,
            )
            self.hook_dispatcher.dispatch_before_compact(before_ctx)
            extra_instructions = tuple(before_ctx.extra_instructions)

        # 准备压缩提示
        compact_prompt = self._create_compact_prompt(
            older_messages,
            extra_instructions=extra_instructions,
        )

        try:
            # 使用LLM进行压缩
            compacted_content = self._limit_summary(self._call_llm_for_compaction(compact_prompt))

            def window(summary: str) -> List[Dict[str, Any]]:
                return (
                    ([system_message] if system_message else [])
                    + [self._summary_message(summary, up_to_seq=up_to_seq)]
                    + recent_messages
                )

            if target_budget is not None and self.count_tokens(window(compacted_content)) > target_budget:
                # Fit the generated summary around the chosen recent window.
                # Advancing the anchor after dropping an unsummarized message
                # would hide that message from every future prompt.
                low, high = 1, len(compacted_content)
                best = ""
                while low <= high:
                    mid = (low + high) // 2
                    candidate = compacted_content[:mid].rstrip()
                    if self.count_tokens(window(candidate)) <= target_budget:
                        best = candidate
                        low = mid + 1
                    else:
                        high = mid - 1
                if best:
                    compacted_content = best

            if not compacted_content.strip():
                return messages
            compacted_messages = window(compacted_content)
            if up_to_seq is not None and callable(self.on_checkpoint):
                self.on_checkpoint(up_to_seq, compacted_content)

            self.num_tokens = self.count_tokens(compacted_messages)
            return compacted_messages

        except Exception as e:
            logger.error(f"Compaction failed: {e}")
            if up_to_seq is not None:
                # Try again on a future turn rather than hide journaled
                # messages behind an omission marker without an anchor.
                return messages
            token_budget = None
            if self.max_tokens > 0:
                token_budget = max(1, math.floor(self.max_tokens * self.compact_target_ratio))
            fallback = self.trim_messages_to_budget(messages, token_budget=token_budget)
            self.num_tokens = self.count_tokens(fallback)
            return fallback

    def _create_compact_prompt(
        self,
        messages: List[Dict[str, Any]],
        *,
        extra_instructions: tuple[str, ...] = (),
    ) -> str:
        """创建压缩提示"""
        turns: list[CompactTranscriptTurn] = []
        for message in messages:
            role = str(message.get("role", "") or "")
            content = message.get("display_content") or message.get("content", "")
            if isinstance(content, (dict, list)):
                content = self._message_token_text({"content": content})
            turns.append(
                CompactTranscriptTurn(
                    role=role,
                    content=str(content or ""),
                    tool_name=str(message.get("name", "") or ""),
                )
            )
        return COMPACT_PROMPT_SPEC.render_user(
            CompactPromptContext(
                turns=tuple(turns),
                extra_instructions=tuple(extra_instructions),
                locale=self._active_locale(),
            )
        )

    def _call_llm_for_compaction(self, prompt: str) -> str:
        """调用LLM进行压缩"""
        active_locale = self._active_locale()
        system_content = COMPACT_PROMPT_SPEC.render_system(
            TemplateContext(locale=active_locale)
        )
        compact_messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ]

        # 调用LLM
        response = self.llm_adapter.chat(compact_messages, stream=False, response_format={'type': 'text'})

        if response:
            try:
                decode = getattr(self.llm_adapter, "decode_response", None)
                if callable(decode):
                    try:
                        decoded_content = decode(response).content
                    except (AttributeError, IndexError, KeyError, TypeError):
                        pass  # Preserve legacy text-only response objects.
                    else:
                        if isinstance(decoded_content, str):
                            return decoded_content
                if hasattr(response, 'choices') and hasattr(response.choices[0], 'message'):
                    return response.choices[0].message.content
                elif hasattr(response, 'text'):
                    return response.text
                elif isinstance(getattr(response, 'content', None), str):
                    return response.content
                elif hasattr(response, 'content'):
                    return response.content[0].text
                else:
                    return str(response)
            except Exception as e:
                logger.error(f"Failed to extract response content: {e}")
                return render_compact_failure_fallback(locale=active_locale)

        return render_compact_failure_fallback(locale=active_locale)

    def auto_compact_if_needed(self, messages: List[Dict[str, str]], token_usage: int = 0) -> List[Dict[str, str]]:
        """自动检查并压缩消息（如果需要）"""
        # logger.info("num tokens before compaction check: {}".format(self.num_tokens))
        if self.needs_compaction(messages, token_usage):
            logger.info("Token limit approaching, performing automatic compaction...")
            return self.compact_messages(messages)
        return messages
