from asyncio import Queue
import copy
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import time
from datetime import datetime
from threading import RLock, Thread, local
from typing import Any, Dict, Generator, List, Optional, Union

from openai import OpenAI

from ai.llm.dialog_repair import repair_dialog_output
from core.messaging.dialog_output import has_valid_dialog_output
from core.messaging.stream_events import (
    STREAM_DIALOG_REPAIR_KEY,
    STREAM_REASONING_DELTA_KEY,
)
from ai.llm.llm_adapter import (
    ClaudeAdapter,
    DeepSeekAdapter,
    GeminiAdapter,
    LLMAdapter,
    OpenAIAdapter,
)
from ai.llm.compact_manager import CompactManager
from ai.llm.message_sanitizer import (
    filter_unpaired_tool_messages_for_request,
    strip_orphaned_tool_calls,
)
from ai.tools.tool_executor import ToolExecutor
from ai.tools.tool_manager import ToolManager
from sdk.exception.types import HTTP_REASON_UNPAIRED_TOOL_MESSAGES, classify_exception
from sdk.hooks import BeforeChatContext, MessageAddedContext, PluginHookDispatcher, PluginHookEvent
from sdk.llm_runtime import get_llm_host_runtime
from sdk.logging import get_logger

tool_manager = ToolManager()
tool_executor = ToolExecutor(tool_manager)
logger = get_logger(__name__)

# 模型后台加载完成时：清除冷却 + 推送聊天通知
def _on_tool_ready(group: str, message: str) -> None:
    tool_executor.clear_cooldown(group)
    get_llm_host_runtime().notify_tool_ready(group, message)

from sdk.tool_registry import set_tool_ready_callback
set_tool_ready_callback(_on_tool_ready)

FIRST_USER_TURN_TOOL_CALL_LIMIT = 1

@dataclass
class _ChatTurnState:
    started_at: float
    first_user_turn: bool
    first_turn_tool_call_limit: int
    llm_rounds: int = 0
    tool_call_attempts: int = 0
    tool_calls_executed: int = 0
    tool_calls_skipped: int = 0
    tool_failures: dict[str, str] = field(default_factory=dict)

    def tool_budget_exhausted(self) -> bool:
        return (
            self.first_user_turn
            and self.first_turn_tool_call_limit >= 0
            and self.tool_call_attempts >= self.first_turn_tool_call_limit
        )


@dataclass
class _HistoryScopeState:
    """Thread-local view of one version of the conversation history.

    A chat worker holds this view for its entire turn.  Replacing or clearing
    history swaps the global list and advances its epoch, so an older worker
    keeps operating on its detached list instead of appending a late result to
    the newly selected conversation.
    """

    epoch: int
    messages: list[dict]
    stale_on_enter: bool = False


_history_state_init_lock = RLock()


def _tool_result_status(result: str) -> str:
    if not result:
        return "empty"
    try:
        parsed = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return "raw"
    if not isinstance(parsed, dict):
        return "success"
    if parsed.get("status") == "loading":
        return "loading"
    if parsed.get("cancelled") is True:
        return "cancelled"
    if "error" in parsed:
        return "error"
    return str(parsed.get("status") or "success")

def _prefix_user_text_with_local_time(text: Any) -> Any:
    """为发送给模型的用户正文加上本机本地时间（供模型感知「何时」发送）。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = f"[本地时间 {ts}]"
    if not isinstance(text, list):
        return f"{prefix}\n{text}"
    content = copy.deepcopy(text)
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            block["text"] = f"{prefix}\n{str(block.get('text') or '')}"
            return content
    content.insert(0, {"type": "text", "text": prefix})
    return content


def _notify_tool_call_hint(tool_name: str) -> None:
    """Ask the injected host to surface the active tool call."""
    try:
        get_llm_host_runtime().notify_tool_call(tool_name)
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
        "Ollama": OpenAIAdapter
    }

    @staticmethod
    def create_adapter(llm_provider: str, **kwargs) -> LLMAdapter:
        """Creates and returns an LLMAdapter instance based on the given name."""
        adapter_class = LLMAdapterFactory._adapters.get(llm_provider)

        if not adapter_class:
            raise ValueError(f"Unsupported LLM adapter: '{llm_provider}'. Supported adapters are: {list(LLMAdapterFactory._adapters.keys())}")

        try:
            from config.adapter_extra_kwargs import filter_kwargs_for_ctor

            return adapter_class(**filter_kwargs_for_ctor(adapter_class, kwargs))
        except TypeError as e:
            print(f"Error creating adapter '{llm_provider}'. Check the required arguments.")
            raise e



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
        first_turn_tool_call_limit: int = FIRST_USER_TURN_TOOL_CALL_LIMIT,
        generation_config: Optional[Dict[str, Any]] = None,
        history_file: str = "",
        hook_dispatcher: PluginHookDispatcher | None = None,
    ):
        # Keep the backing list separate from the public ``messages`` property.
        # The property can then return a worker's thread-local history view
        # while an old turn is being cancelled during a history replacement.
        self._history_local = local()
        self._history_epoch = 0
        self._messages: list[dict] = []
        self._history_cancel_requested = False
        self._history_lock = RLock()
        self.llm_adapter = adapter
        self.user_template = user_template
        self.hook_dispatcher = hook_dispatcher
        self.max_context_tokens = int(max_tokens)
        self.history_recent_messages = max(1, int(history_recent_messages))
        self.max_tool_result_chars = max(1, int(max_tool_result_chars))
        self.first_turn_tool_call_limit = max(0, int(first_turn_tool_call_limit))
        self.compact_manager = CompactManager(
            adapter,
            self.max_context_tokens,
            compact_threshold,
            compact_target_ratio=compact_target_ratio,
            recent_message_limit=self.history_recent_messages,
            hook_dispatcher=self.hook_dispatcher,
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
        self._turn_state: Optional[_ChatTurnState] = None
        self._history_file = history_file

        # 设置日志
        self.logger = logger

    # ``LLMManager`` is occasionally constructed by lightweight test doubles
    # with ``__new__``.  Keep the epoch machinery lazy so those callers remain
    # compatible instead of requiring every fixture to know these internals.
    def _ensure_history_state(self) -> None:
        if "_history_lock" in self.__dict__:
            return
        with _history_state_init_lock:
            if "_history_lock" in self.__dict__:
                return
            legacy_messages = self.__dict__.pop("messages", [])
            legacy_cancel = self.__dict__.pop("_cancel_requested", False)
            history_lock = RLock()
            self.__dict__["_history_local"] = local()
            self.__dict__["_history_epoch"] = 0
            self.__dict__["_messages"] = (
                legacy_messages if isinstance(legacy_messages, list) else []
            )
            self.__dict__["_history_cancel_requested"] = bool(legacy_cancel)
            # Publish the lock last: another thread uses its presence as the
            # signal that every companion state field is ready.
            self.__dict__["_history_lock"] = history_lock

    def _history_scope_stack(self) -> list[_HistoryScopeState]:
        self._ensure_history_state()
        history_local = self.__dict__["_history_local"]
        stack = getattr(history_local, "scope_stack", None)
        if stack is None:
            stack = []
            history_local.scope_stack = stack
        return stack

    def _active_history_scope(self) -> _HistoryScopeState | None:
        stack = self._history_scope_stack()
        return stack[-1] if stack else None

    def _scope_is_current_locked(
        self, scope: _HistoryScopeState | None
    ) -> bool:
        if scope is None:
            return True
        return (
            not scope.stale_on_enter
            and scope.epoch == self.__dict__["_history_epoch"]
            and scope.messages is self.__dict__["_messages"]
        )

    def _target_is_current_locked(
        self,
        scope: _HistoryScopeState | None,
        target_messages: list[dict],
        captured_epoch: int,
    ) -> bool:
        if scope is not None:
            return self._scope_is_current_locked(scope)
        return (
            captured_epoch == self.__dict__["_history_epoch"]
            and target_messages is self.__dict__["_messages"]
        )

    def _replace_scoped_messages_locked(
        self, scope: _HistoryScopeState, replacement: list[dict]
    ) -> None:
        """Replace a live scoped list without invalidating its outer scopes."""
        previous = scope.messages
        self.__dict__["_messages"] = replacement
        for active_scope in self._history_scope_stack():
            if (
                not active_scope.stale_on_enter
                and active_scope.epoch == scope.epoch
                and active_scope.messages is previous
            ):
                active_scope.messages = replacement

    def _history_scope_is_stale(self) -> bool:
        self._ensure_history_state()
        scope = self._active_history_scope()
        if scope is None:
            return False
        with self.__dict__["_history_lock"]:
            return not self._scope_is_current_locked(scope)

    @property
    def history_epoch(self) -> int:
        """Monotonically increasing identity of the globally selected history."""
        self._ensure_history_state()
        with self.__dict__["_history_lock"]:
            return int(self.__dict__["_history_epoch"])

    @contextmanager
    def history_scope(self, expected_epoch: int | None = None):
        """Bind this thread to one immutable *history identity* for a turn.

        A mismatched expected epoch is deliberately a stale scope from the
        outset.  It exposes only a detached list and makes cancellation reads
        true, so a queue item taken immediately before a history switch cannot
        start a request against the newly selected history.
        """
        self._ensure_history_state()
        with self.__dict__["_history_lock"]:
            parent_scope = self._active_history_scope()
            if parent_scope is not None:
                # A nested scope is part of the same turn.  It must inherit a
                # stale outer identity rather than capture the replacement
                # history and accidentally make that turn live again.
                epoch = parent_scope.epoch
                stale_on_enter = (
                    not self._scope_is_current_locked(parent_scope)
                    or (
                        expected_epoch is not None
                        and expected_epoch != parent_scope.epoch
                    )
                )
                messages = (
                    copy.deepcopy(parent_scope.messages)
                    if stale_on_enter
                    else parent_scope.messages
                )
            else:
                epoch = int(self.__dict__["_history_epoch"])
                stale_on_enter = (
                    expected_epoch is not None and expected_epoch != epoch
                )
                messages = (
                    copy.deepcopy(self.__dict__["_messages"])
                    if stale_on_enter
                    else self.__dict__["_messages"]
                )
            scope = _HistoryScopeState(
                epoch=epoch,
                messages=messages,
                stale_on_enter=stale_on_enter,
            )
        stack = self._history_scope_stack()
        stack.append(scope)
        try:
            yield scope
        finally:
            # Nested scopes are supported.  Normal context-manager use exits
            # in LIFO order; keep a defensive fallback for unusual teardown.
            if stack and stack[-1] is scope:
                stack.pop()
            else:
                try:
                    stack.remove(scope)
                except ValueError:
                    pass

    def invalidate_history(self) -> int:
        """Fence active turns before a history file/UI transition.

        The content is retained, but copied into a new backing list.  Existing
        scopes still point at the old list and observe a stale epoch.  The
        caller can therefore delete or replace temporary history storage after
        this method returns without a late stream recreating it.
        """
        self._ensure_history_state()
        with self.__dict__["_history_lock"]:
            try:
                detached_messages = copy.deepcopy(self.__dict__["_messages"])
            except Exception:
                # A malformed plugin payload should not prevent the history
                # boundary itself.  A list copy still fences normal append/
                # replacement mutations.
                detached_messages = list(self.__dict__["_messages"])
            self.__dict__["_messages"] = detached_messages
            self.__dict__["_history_epoch"] += 1
            return int(self.__dict__["_history_epoch"])

    def _replace_global_history(self, messages: list[dict], *, bump_epoch: bool) -> int:
        """Atomically install a new backing list without running callbacks."""
        self._ensure_history_state()
        with self.__dict__["_history_lock"]:
            self.__dict__["_messages"] = messages
            if bump_epoch:
                self.__dict__["_history_epoch"] += 1
            return int(self.__dict__["_history_epoch"])

    @property
    def messages(self) -> list[dict]:
        """Current thread's scoped messages, or the globally selected history."""
        self._ensure_history_state()
        scope = self._active_history_scope()
        if scope is not None:
            return scope.messages
        with self.__dict__["_history_lock"]:
            return self.__dict__["_messages"]

    @messages.setter
    def messages(self, value: list[dict]) -> None:
        """Preserve direct legacy assignments without letting stale turns win.

        A direct assignment in a live scope is a same-turn replacement (for
        example auto-compaction).  In a stale scope it changes only the local
        detached view.  Outside a scope it is a new global history identity.
        """
        self._ensure_history_state()
        replacement = value if isinstance(value, list) else []
        scope = self._active_history_scope()
        with self.__dict__["_history_lock"]:
            if scope is not None:
                if self._scope_is_current_locked(scope):
                    self._replace_scoped_messages_locked(scope, replacement)
                else:
                    scope.messages = replacement
                return
            self.__dict__["_messages"] = replacement
            self.__dict__["_history_epoch"] += 1

    @property
    def _cancel_requested(self) -> bool:
        self._ensure_history_state()
        scope = self._active_history_scope()
        with self.__dict__["_history_lock"]:
            if not self._scope_is_current_locked(scope):
                return True
            return bool(self.__dict__["_history_cancel_requested"])

    @_cancel_requested.setter
    def _cancel_requested(self, value: bool) -> None:
        self._ensure_history_state()
        scope = self._active_history_scope()
        with self.__dict__["_history_lock"]:
            # ``chat`` starts by clearing this flag.  An old scope must never
            # turn a cancellation back off after a replacement history wins.
            if not self._scope_is_current_locked(scope):
                return
            self.__dict__["_history_cancel_requested"] = bool(value)

    def cancel_current_chat(self) -> None:
        """Request cancellation of the current :meth:`chat` call.

        Sets the internal flag so stream loops exit early, and calls the
        adapter's ``cancel()`` to close the underlying HTTP connection.
        """
        # Do not let a stale worker cancel a newer request that was started
        # after the user selected another history.
        if self._history_scope_is_stale():
            return
        self._cancel_requested = True
        if self.llm_adapter is not None:
            try:
                self.llm_adapter.cancel()
            except Exception:
                pass

    def _confirm_risky_tool(self, tool_name: str, risk: str, args_str: str) -> bool:
        """Request user confirmation for a risky tool. Returns True if confirmed."""
        if risk == "low":
            return True
        try:
            return get_llm_host_runtime().confirm_risky_tool(
                tool_name,
                risk,
                args_str,
            )
        except Exception:
            return risk != "high"

    def set_adapter(self, adapter: LLMAdapter):
        """
        Sets the current LLM adapter. This is how you switch providers.
        """
        self.llm_adapter = adapter
        self.compact_manager.llm_adapter = adapter
        print(f"LLM adapter switched to {type(self.llm_adapter).__name__}.")
        self._replace_global_history([], bump_epoch=True)

    def set_user_template(self, template: str):
        """Sets the system prompt/user template and resets the messages list."""
        self.user_template = template
        self._replace_global_history(
            [{"role": "system", "content": template}], bump_epoch=True
        )
        self.llm_adapter.set_user_template(template)

    def add_message(self, role: str, content: Optional[str], **kwargs) -> bool:
        """
        通用消息添加方法。
        集成了 Auto-Compact 逻辑：每当消息增加，自动检查并压缩。
        """
        if role == "tool":
            content = self._prepare_tool_result_for_history(content)
        msg = {"role": role, "content": content}
        msg.update(kwargs)
        self._ensure_history_state()
        scope = self._active_history_scope()
        hook_dispatcher = getattr(self, "hook_dispatcher", None)
        hook_enabled = bool(
            hook_dispatcher is not None
            and hook_dispatcher.has_hooks(PluginHookEvent.MESSAGE_ADDED)
        )

        # The append and its crash-recovery record are one history-version
        # operation.  A history boundary waits on this short lock, then fences
        # every old scope before deleting/replacing its temporary storage.
        with self.__dict__["_history_lock"]:
            if not self._scope_is_current_locked(scope):
                return False
            target_messages = (
                scope.messages if scope is not None else self.__dict__["_messages"]
            )
            captured_epoch = int(self.__dict__["_history_epoch"])
            target_messages.append(msg)
            history_file = getattr(self, "_history_file", "")
            if history_file:
                from ai.llm.history_manager import HistoryManager

                HistoryManager.append_message_to_tmp(history_file, msg)

        # Plugin callbacks and compaction may run arbitrary or network-backed
        # work.  They must stay outside the history lock; a version/identity
        # check below prevents their late result from replacing new history.
        if hook_enabled:
            self.hook_dispatcher.dispatch_message_added(
                MessageAddedContext(
                    role=role,
                    message=copy.deepcopy(msg),
                    messages=copy.deepcopy(target_messages),
                )
            )

        # --- Auto-Compact 逻辑 ---
        # 自动调用 compact_manager 检查 token 是否超限并执行压缩
        compacted_messages = self.compact_manager.auto_compact_if_needed(target_messages)
        if compacted_messages is not target_messages:
            before_tokens = self.compact_manager.count_tokens(target_messages)
            after_tokens = self.compact_manager.count_tokens(compacted_messages)
            self.logger.info(
                "Auto-compact triggered: messages %s -> %s, tokens %s -> %s",
                len(self.messages),
                len(compacted_messages),
                before_tokens,
                after_tokens,
            )
            with self.__dict__["_history_lock"]:
                if not self._target_is_current_locked(
                    scope, target_messages, captured_epoch
                ):
                    return False
                if scope is not None:
                    self._replace_scoped_messages_locked(scope, compacted_messages)
                else:
                    self.__dict__["_messages"] = compacted_messages
        return True

    def clear_messages(self):
        self._replace_global_history(
            [{"role": "system", "content": self.user_template}], bump_epoch=True
        )

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

    def _before_chat_context(
        self,
        *,
        stream: bool,
        tools_defs: list[dict] | None,
        generation_kwargs: dict[str, Any],
    ) -> BeforeChatContext:
        if (
            self.hook_dispatcher is None
            or not self.hook_dispatcher.has_hooks(PluginHookEvent.BEFORE_CHAT)
        ):
            return BeforeChatContext(
                messages=self.get_messages(),
                tools=tools_defs,
                generation_kwargs=generation_kwargs,
                stream=stream,
            )

        context = BeforeChatContext(
            messages=copy.deepcopy(self.get_messages()),
            tools=copy.deepcopy(tools_defs) if tools_defs else None,
            generation_kwargs=copy.deepcopy(generation_kwargs),
            stream=stream,
        )
        self.hook_dispatcher.dispatch_before_chat(context)
        return context

    def _estimate_context_tokens(
        self,
        tools_defs: list[dict] | None,
        messages: list[dict] | None = None,
    ) -> dict[str, int]:
        messages = self.get_messages() if messages is None else messages
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
        try:
            get_llm_host_runtime().post_context_token_estimate(estimate)
        except Exception:
            self.logger.debug("Failed to post context token estimate to UI", exc_info=True)

    def _has_conversation_history(self) -> bool:
        return any(m.get("role") != "system" for m in self.messages)

    def _begin_chat_turn(self, *, first_user_turn: bool) -> None:
        self._turn_state = _ChatTurnState(
            started_at=time.perf_counter(),
            first_user_turn=first_user_turn,
            first_turn_tool_call_limit=self.first_turn_tool_call_limit,
        )
        self.logger.info(
            "Chat turn profile started",
            extra={
                "event": "chat.turn.profile.started",
                "first_user_turn": first_user_turn,
                "first_turn_tool_call_limit": self.first_turn_tool_call_limit,
            },
        )

    def _next_llm_round(self) -> int:
        if self._turn_state is None:
            return 1
        self._turn_state.llm_rounds += 1
        return self._turn_state.llm_rounds

    def _adapter_profile(self) -> dict[str, str]:
        return {
            "adapter": type(self.llm_adapter).__name__,
            "model": str(getattr(self.llm_adapter, "model", "") or ""),
        }

    def _current_tool_definitions(self) -> list[dict]:
        state = self._turn_state
        if state is not None and state.tool_budget_exhausted():
            self.logger.info(
                "LLM tools disabled by first-turn tool budget",
                extra={
                    "event": "ai.tools.disabled",
                    "reason": "first_turn_tool_budget_exhausted",
                    "tool_call_attempts": state.tool_call_attempts,
                    "first_turn_tool_call_limit": state.first_turn_tool_call_limit,
                },
            )
            return []

        defs = tool_manager.get_definitions(groups=self._active_tool_groups)
        available: list[dict] = []
        filtered: list[dict[str, str]] = []
        for definition in defs:
            func = definition.get("function", {})
            name = str(func.get("name") or "")
            group = tool_manager.get_tool_group(name)
            if self.tool_executor.is_in_cooldown(group):
                filtered.append({"name": name, "group": group})
                continue
            available.append(definition)

        if filtered:
            self.logger.info(
                "Filtered tool definitions in cooldown",
                extra={
                    "event": "ai.tools.filtered",
                    "filtered_tool_count": len(filtered),
                    "filtered_groups": sorted({item["group"] for item in filtered}),
                    "filtered_tools": [item["name"] for item in filtered],
                },
            )
        return available

    def _log_llm_request_started(
        self,
        *,
        round_index: int,
        stream: bool,
        tools_defs: list[dict],
        estimate: dict[str, int],
        message_count: int | None = None,
    ) -> None:
        self.logger.info(
            "LLM request started",
            extra={
                "event": "llm.request.started",
                "llm_round": round_index,
                "stream": stream,
                "message_count": len(self.get_messages()) if message_count is None else message_count,
                "active_tool_groups": list(self._active_tool_groups),
                "tool_count": len(tools_defs or []),
                "tool_names": [
                    str(d.get("function", {}).get("name") or "")
                    for d in (tools_defs or [])
                ],
                **self._adapter_profile(),
                **estimate,
            },
        )

    def _log_llm_request_completed(
        self,
        *,
        round_index: int,
        stream: bool,
        started: float,
        outcome: str,
        content_chars: int = 0,
        reasoning_chars: int = 0,
        tool_call_count: int = 0,
    ) -> None:
        self.logger.info(
            "LLM request completed",
            extra={
                "event": "llm.request.completed",
                "llm_round": round_index,
                "stream": stream,
                "outcome": outcome,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "content_chars": content_chars,
                "reasoning_chars": reasoning_chars,
                "tool_call_count": tool_call_count,
                **self._adapter_profile(),
            },
        )

    def _log_llm_request_failed(
        self,
        *,
        round_index: int,
        stream: bool,
        started: float,
        exc: Exception,
    ) -> None:
        self.logger.exception(
            "LLM request failed",
            extra={
                "event": "llm.request.failed",
                "llm_round": round_index,
                "stream": stream,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error_type": type(exc).__name__,
                **self._adapter_profile(),
            },
        )

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
            state = self._turn_state
            if state is not None:
                self.logger.info(
                    "Chat turn profile completed",
                    extra={
                        "event": "chat.turn.profile.completed",
                        "duration_ms": round((time.perf_counter() - state.started_at) * 1000, 2),
                        "first_user_turn": state.first_user_turn,
                        "llm_rounds": state.llm_rounds,
                        "tool_call_attempts": state.tool_call_attempts,
                        "tool_calls_executed": state.tool_calls_executed,
                        "tool_calls_skipped": state.tool_calls_skipped,
                        "tool_failures": dict(state.tool_failures),
                    },
                )
            self._turn_state = None
            self._reset_active_tool_groups()

    def _stream_with_chat_scope(self, stream: Generator[Union[str, dict[str, str]], None, None]):
        def scoped_stream():
            try:
                # Arm the finally block without consuming the provider stream.
                # A worker can cancel between chat() and its first iteration;
                # closing an entirely unstarted generator skips its finally.
                yield None
                yield from stream
            finally:
                self._finish_chat_scope()

        result = scoped_stream()
        next(result)
        return result

    def _empty_chat_stream(self) -> Generator[Union[str, dict[str, str]], None, None]:
        """A real generator used when a stale history scope is suppressed."""
        if False:  # pragma: no cover - keeps the function a generator
            yield ""

    def _persist_plain_assistant_turn(self, content: str, reasoning: str) -> bool:
        """无 tool_calls 的一轮：把 assistant 正文与（若存在）思考写入历史，供下游 API 与存档。"""
        if self._cancel_requested:
            return False
        extra = _deepseek_reasoning_message_kwargs(self.llm_adapter, reasoning)
        if not (content or "").strip() and not extra:
            return False
        return self.add_message("assistant", content or "", **extra)

    def get_messages(self):
        """Returns the current list of messages."""
        return self.messages

    def set_messages(self, new_messages: list):
        """Sets the conversation history to a new list of messages."""
        if isinstance(new_messages, list):
            # The caller commonly passes a list it still holds for UI/history
            # bookkeeping.  Detach nested message dicts too, otherwise an old
            # retained reference can mutate the newly installed history.
            replacement = copy.deepcopy(new_messages)
            # These are deterministic in-memory transforms.  Do them before
            # the short atomic replacement so plugin/network work cannot hold
            # the history lock.
            strip_orphaned_tool_calls(replacement)
            replacement = self._trim_loaded_history_if_needed(replacement)
            token_count = self.compact_manager.count_tokens(replacement)
            self._replace_global_history(replacement, bump_epoch=True)
            self.compact_manager.set_token_count(token_count)
            print("Chat history has been updated.")
        else:
            print("Error: new_messages must be a list.")


    def chat(
        self,
        user_input: Optional[Any],
        stream: bool = True,
        dialog_output_required: bool = False,
        **kwargs,
    ) -> Union[Generator, str]:
        """
        统一入口：根据 stream 参数决定调用流式还是同步私有方法。

        ``include_local_time``（默认 True）：为本次 user 消息追加本机日期时间前缀，再写入对话历史。
        翻译、设定生成等非聊天调用请传 ``include_local_time=False``。

        ``dialog_output_required`` is enabled by the chat runtime only. Generic
        callers keep their provider response unchanged.
        """
        # A queue item may have been dequeued just before history replacement.
        # Do not even enter the chat bookkeeping/request path for that stale
        # scope; the worker can safely consume this empty result.
        if self._history_scope_is_stale():
            return self._empty_chat_stream() if stream else ""

        outer_chat = self._chat_depth == 0
        first_user_turn = outer_chat and user_input is not None and not self._has_conversation_history()
        if outer_chat:
            self._begin_chat_turn(first_user_turn=first_user_turn)
        self._chat_depth += 1
        self._cancel_requested = False
        if self._cancel_requested:
            if stream:
                return self._stream_with_chat_scope(self._empty_chat_stream())
            self._finish_chat_scope()
            return ""
        # 清理孤立的 tool_calls（必须在加 user 消息之前，否则占位 tool 回执会插在 user 后面）
        self._strip_orphaned_tool_calls()

        try:
            include_local_time = bool(kwargs.pop("include_local_time", True))
            user_display_text = str(kwargs.pop("user_display_text", "") or "").strip()
            user_input_text = kwargs.pop("user_input_text", None)
            user_attachments = kwargs.pop("user_attachments", None)
            requested_tool_groups = kwargs.pop("tool_groups", ())
            if isinstance(requested_tool_groups, str):
                requested_tool_groups = (requested_tool_groups,)
            for group in requested_tool_groups:
                self._activate_tool_group(str(group or "").strip())
            if user_input:
                if include_local_time:
                    user_input = _prefix_user_text_with_local_time(user_input)
                user_metadata: dict[str, Any] = {}
                if user_display_text:
                    user_metadata["display_content"] = user_display_text
                if user_input_text is not None:
                    user_metadata["input_text"] = str(user_input_text or "")
                if isinstance(user_attachments, list):
                    user_metadata["attachments"] = copy.deepcopy(user_attachments)
                if not self.add_message(
                    "user",
                    user_input,
                    **user_metadata,
                ):
                    if stream:
                        return self._stream_with_chat_scope(
                            self._empty_chat_stream()
                        )
                    return ""

            if stream:
                return self._stream_with_chat_scope(
                    self._chat_with_tools_stream(
                        _dialog_output_required=dialog_output_required,
                        **kwargs,
                    )
                )
            return self._chat_with_tools_sync(
                _dialog_output_required=dialog_output_required,
                **kwargs,
            )
        finally:
            if not stream:
                self._finish_chat_scope()

    def _strip_orphaned_tool_calls(self) -> None:
        """清理不完整的 tool call 对：删孤立的 tool，补缺失的回执。"""
        strip_orphaned_tool_calls(self.get_messages())

    def _recover_request_tool_pairs(self, exc: Exception, messages: list[dict]) -> list[dict] | None:
        error_info = classify_exception(exc)
        if (
            not error_info
            or error_info.get("kind") != "http_client"
            or error_info.get("reason") != HTTP_REASON_UNPAIRED_TOOL_MESSAGES
        ):
            return None
        filtered = filter_unpaired_tool_messages_for_request(messages)
        if filtered is messages:
            return None
        self.logger.warning(
            "Recovering LLM request by filtering unpaired tool messages",
            extra={
                "event": "llm.request.tool_pairs.recovered",
                "before_count": len(messages),
                "after_count": len(filtered),
                "error_type": type(exc).__name__,
            },
        )
        return filtered

    def _send_llm_request_with_recovery(
        self,
        *,
        messages: list[dict],
        stream: bool,
        tools_defs: list[dict],
        generation_kwargs: dict[str, Any],
    ) -> tuple[Any, list[dict]]:
        try:
            response = self.llm_adapter.chat(
                messages=messages,
                stream=stream,
                tools=tools_defs if tools_defs else None,
                **generation_kwargs,
            )
            return response, messages
        except Exception as exc:
            recovered_messages = self._recover_request_tool_pairs(exc, messages)
            if recovered_messages is None:
                raise
            response = self.llm_adapter.chat(
                messages=recovered_messages,
                stream=stream,
                tools=tools_defs if tools_defs else None,
                **generation_kwargs,
            )
            return response, recovered_messages

    def _budget_exhausted_tool_result(self, tool_name: str) -> str:
        return json.dumps(
            {
                "status": "skipped",
                "reason": "first_turn_tool_budget_exhausted",
                "message": (
                    f"首轮工具调用预算已用完，已跳过 {tool_name}。"
                    "请基于已有信息直接回复用户，不要继续调用工具。"
                ),
            },
            ensure_ascii=False,
        )

    def _cooldown_skipped_tool_result(self, tool_name: str, cooldown_message: str) -> str:
        try:
            parsed = json.loads(cooldown_message)
        except (json.JSONDecodeError, TypeError):
            parsed = {"status": "loading", "message": str(cooldown_message or "")}
        if isinstance(parsed, dict):
            parsed.setdefault("status", "skipped")
            parsed["tool"] = tool_name
            parsed["reason"] = "tool_group_in_cooldown"
            parsed["message"] = (
                str(parsed.get("message") or "")
                + " 请基于已有信息直接回复用户，不要继续调用这个工具组。"
            ).strip()
        return json.dumps(parsed, ensure_ascii=False)

    def _repeated_failure_tool_result(self, tool_name: str, previous_status: str) -> str:
        return json.dumps(
            {
                "status": "skipped",
                "reason": "tool_failed_earlier_in_turn",
                "tool": tool_name,
                "previous_status": previous_status,
                "message": (
                    f"{tool_name} 已在本轮失败或不可用，已跳过重复调用。"
                    "请基于已有信息直接回复用户。"
                ),
            },
            ensure_ascii=False,
        )

    def _execute_formatted_tool_call(self, call: dict) -> tuple[str, str]:
        func_name = call["function"]["name"]
        func_args = call["function"]["arguments"]
        if isinstance(func_args, str) and not func_args.strip():
            func_args = "{}"

        state = self._turn_state
        if state is not None and state.tool_budget_exhausted():
            state.tool_calls_skipped += 1
            result = self._budget_exhausted_tool_result(func_name)
            self.logger.info(
                "Tool call skipped by first-turn budget",
                extra={
                    "event": "tool.call.skipped",
                    "tool_name": func_name,
                    "reason": "first_turn_tool_budget_exhausted",
                    "tool_call_attempts": state.tool_call_attempts,
                    "first_turn_tool_call_limit": state.first_turn_tool_call_limit,
                },
            )
            return func_name, result

        if state is not None:
            state.tool_call_attempts += 1
            previous_failure = state.tool_failures.get(func_name)
            if previous_failure:
                state.tool_calls_skipped += 1
                result = self._repeated_failure_tool_result(func_name, previous_failure)
                self.logger.info(
                    "Tool call skipped after previous failure in same turn",
                    extra={
                        "event": "tool.call.skipped",
                        "tool_name": func_name,
                        "reason": "tool_failed_earlier_in_turn",
                        "previous_status": previous_failure,
                    },
                )
                return func_name, result

        cooldown_message = self.tool_executor.cooldown_message_for_tool(func_name)
        if cooldown_message is not None:
            if state is not None:
                state.tool_calls_skipped += 1
            result = self._cooldown_skipped_tool_result(func_name, cooldown_message)
            self.logger.info(
                "Tool call skipped because group is in cooldown",
                extra={
                    "event": "tool.call.skipped",
                    "tool_name": func_name,
                    "tool_group": tool_manager.get_tool_group(func_name),
                    "reason": "tool_group_in_cooldown",
                },
            )
            return func_name, result

        _notify_tool_call_hint(func_name)
        result = self.tool_executor.execute(
            func_name,
            func_args,
            risk_confirm=self._confirm_risky_tool,
        )

        if func_name == "search_tools":
            self._activate_tool_group_from_search(func_args)

        if result is None:
            result = json.dumps({"status": "success", "result": "no return value"})
        elif not isinstance(result, str):
            result = json.dumps(result)

        status = _tool_result_status(result)
        if state is not None:
            state.tool_calls_executed += 1
            if status in {"error", "loading", "cancelled"}:
                state.tool_failures[func_name] = status
        self.logger.info(
            "Tool call handled",
            extra={
                "event": "tool.call.handled",
                "tool_name": func_name,
                "tool_group": tool_manager.get_tool_group(func_name),
                "status": status,
                "result_chars": len(result or ""),
            },
        )
        return func_name, result

    # llm_manager.py 修正核心片段

    def _chat_with_tools_stream(self, **kwargs) -> Generator[Union[str, dict[str, str]], None, None]:
        if self._cancel_requested:
            return
        dialog_output_required = bool(kwargs.pop("_dialog_output_required", False))
        tools_defs = self._current_tool_definitions()

        # Gemini's OpenAI-compatible streaming endpoint omits thought_signature from
        # tool call deltas. Fall back to non-streaming so the field is preserved.
        from config.config_manager import ConfigManager
        if tools_defs and ConfigManager().config.api_config.llm_provider == "Gemini":
            yield from self._chat_with_tools_sync(
                _dialog_output_required=dialog_output_required,
                **kwargs,
            )
            return

        merged_kwargs = dict(self.generation_config)
        merged_kwargs.update(kwargs)
        chat_context = self._before_chat_context(
            stream=True,
            tools_defs=tools_defs,
            generation_kwargs=merged_kwargs,
        )
        tools_defs = chat_context.tools or []
        merged_kwargs = chat_context.generation_kwargs
        estimate = self._estimate_context_tokens(tools_defs, chat_context.messages)
        round_index = self._next_llm_round()
        request_started = time.perf_counter()
        self._log_llm_request_started(
            round_index=round_index,
            stream=True,
            tools_defs=tools_defs,
            estimate=estimate,
            message_count=len(chat_context.messages),
        )
        try:
            response_stream, chat_context.messages = self._send_llm_request_with_recovery(
                messages=chat_context.messages, stream=True,
                tools_defs=tools_defs,
                generation_kwargs=merged_kwargs,
            )
        except Exception as exc:
            self._log_llm_request_failed(
                round_index=round_index,
                stream=True,
                started=request_started,
                exc=exc,
            )
            raise
        if response_stream is None:
            self._log_llm_request_completed(
                round_index=round_index,
                stream=True,
                started=request_started,
                outcome="no_response",
            )
            return

        # self.logger.info(f"Tools definitions: {tools_defs}")

        full_tool_calls = {}
        has_tool_use = False
        collected_content = ""
        collected_reasoning = ""
        stream_failed = False
        stream_cancelled = False

        try:
            if isinstance(self.llm_adapter, ClaudeAdapter):
                with response_stream as stream:
                    for event in stream:
                        if self._cancel_requested:
                            stream_cancelled = True
                            break
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
                    if self._cancel_requested:
                        stream_cancelled = True
                        break
                    if not chunk or not chunk.choices: continue
                    delta = chunk.choices[0].delta
                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        has_tool_use = True
                        for tc in delta.tool_calls:
                            if tc.index not in full_tool_calls:
                                full_tool_calls[tc.index] = tc
                            elif tc.function and tc.function.arguments:
                                if full_tool_calls[tc.index].function.arguments is None:
                                    full_tool_calls[tc.index].function.arguments = ""
                                full_tool_calls[tc.index].function.arguments += tc.function.arguments
                    r_part = getattr(delta, "reasoning_content", None)
                    if r_part:
                        collected_reasoning += r_part
                        yield {STREAM_REASONING_DELTA_KEY: r_part}
                    if hasattr(delta, 'content') and delta.content:
                        yield delta.content
                        collected_content += delta.content
        except Exception as exc:
            if self._cancel_requested:
                stream_cancelled = True
                return
            stream_failed = True
            self._log_llm_request_failed(
                round_index=round_index,
                stream=True,
                started=request_started,
                exc=exc,
            )
            raise
        finally:
            if not stream_failed:
                outcome = "cancelled" if stream_cancelled or self._cancel_requested else (
                    "tool_calls" if has_tool_use else "content"
                )
                self._log_llm_request_completed(
                    round_index=round_index,
                    stream=True,
                    started=request_started,
                    outcome=outcome,
                    content_chars=len(collected_content),
                    reasoning_chars=len(collected_reasoning),
                    tool_call_count=len(full_tool_calls),
                )

        if self._cancel_requested or stream_cancelled:
            return

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
            if not self.add_message(
                "assistant", collected_content, tool_calls=formatted_calls, **assistant_kw
            ):
                return

            # --- 然后添加 Tool 结果消息 ---
            for call in formatted_calls:
                if self._cancel_requested:
                    return
                try:
                    func_name, result = self._execute_formatted_tool_call(call)
                except Exception as e:
                    self.logger.error(f"Tool execution failed: {e}")
                    result = json.dumps({"error": str(e)})
                    func_name = call['function']['name']
                if not self.add_message(
                    "tool", result, tool_call_id=call['id'], name=func_name
                ):
                    return

            if self._cancel_requested:
                return
            yield from self._chat_with_tools_stream(
                _dialog_output_required=dialog_output_required,
                **kwargs,
            )
        else:
            needs_repair = dialog_output_required and not has_valid_dialog_output(collected_content)
            if needs_repair:
                collected_content = repair_dialog_output(
                    self.llm_adapter,
                    collected_content,
                    chat_context.messages,
                    merged_kwargs,
                    cancelled=lambda: self._cancel_requested,
                    event_logger=self.logger,
                )
            if self._cancel_requested:
                return
            persisted = self._persist_plain_assistant_turn(collected_content, collected_reasoning)
            # Mark repaired content separately so the worker can append only
            # dialogue items that were not already emitted from the live stream.
            if persisted and needs_repair and has_valid_dialog_output(collected_content):
                yield {STREAM_DIALOG_REPAIR_KEY: collected_content}

    def _chat_with_tools_sync(self, **kwargs) -> str:
        if self._cancel_requested:
            return ""
        dialog_output_required = bool(kwargs.pop("_dialog_output_required", False))
        tools_defs = self._current_tool_definitions()
        merged_kwargs = dict(self.generation_config)
        merged_kwargs.update(kwargs)
        chat_context = self._before_chat_context(
            stream=False,
            tools_defs=tools_defs,
            generation_kwargs=merged_kwargs,
        )
        tools_defs = chat_context.tools or []
        merged_kwargs = chat_context.generation_kwargs
        estimate = self._estimate_context_tokens(tools_defs, chat_context.messages)
        round_index = self._next_llm_round()
        request_started = time.perf_counter()
        self._log_llm_request_started(
            round_index=round_index,
            stream=False,
            tools_defs=tools_defs,
            estimate=estimate,
            message_count=len(chat_context.messages),
        )
        try:
            response, chat_context.messages = self._send_llm_request_with_recovery(
                messages=chat_context.messages, stream=False,
                tools_defs=tools_defs,
                generation_kwargs=merged_kwargs,
            )
        except Exception as exc:
            self._log_llm_request_failed(
                round_index=round_index,
                stream=False,
                started=request_started,
                exc=exc,
            )
            raise
        if not response:
            self._log_llm_request_completed(
                round_index=round_index,
                stream=False,
                started=request_started,
                outcome="no_response",
            )
            return ""

        if self._cancel_requested:
            return ""

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

        self._log_llm_request_completed(
            round_index=round_index,
            stream=False,
            started=request_started,
            outcome="tool_calls" if tool_calls else "content",
            content_chars=len(content or ""),
            reasoning_chars=len(reasoning or ""),
            tool_call_count=len(tool_calls or []),
        )

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
            if not self.add_message(
                "assistant", content, tool_calls=formatted_calls, **assistant_sync_kw
            ):
                return ""
            for call in formatted_calls:
                if self._cancel_requested:
                    return ""
                try:
                    func_name, result = self._execute_formatted_tool_call(call)
                except Exception as e:
                    self.logger.error(f"Tool execution failed: {e}")
                    result = json.dumps({"error": str(e)})
                    func_name = call['function']['name']
                if not self.add_message(
                    "tool", result, tool_call_id=call['id'], name=func_name
                ):
                    return ""

            if self._cancel_requested:
                return ""
            return self._chat_with_tools_sync(
                _dialog_output_required=dialog_output_required,
                **kwargs,
            )
        else:
            if dialog_output_required:
                content = repair_dialog_output(
                    self.llm_adapter,
                    content,
                    chat_context.messages,
                    merged_kwargs,
                    cancelled=lambda: self._cancel_requested,
                    event_logger=self.logger,
                )
            if self._cancel_requested:
                return ""
            self._persist_plain_assistant_turn(content, reasoning)
            return content
