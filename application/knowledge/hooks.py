"""Automatic knowledge retrieval before an LLM request."""

from __future__ import annotations

import logging
import os
import time

from core.chat_history.text import strip_local_time_prefix
from sdk.hooks import BeforeChatContext, PluginHookDispatcher
from sdk.chat_init import InitChatCancelled, InitChatContext

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_LIMIT = 5
_MARKER = "[Shinsekai knowledge context]"


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("invalid %s=%r; using %s", name, raw, default)
        return default
    return max(minimum, value)


class KnowledgeHooks:
    def __init__(
        self,
        character_names: list[str] | None = None,
        *,
        search_func=None,
        status_func=None,
        search_limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> None:
        self.character_names = [
            str(name or "").strip()
            for name in (character_names or [])
            if str(name or "").strip()
        ]
        self.search_func = search_func
        self.status_func = status_func
        self.search_limit = max(1, int(search_limit))
        self.enabled = False

    def register(self, dispatcher: PluginHookDispatcher) -> None:
        dispatcher.register_init_chat(
            self.init_chat,
            label="knowledge_init_chat",
        )
        dispatcher.register_before_chat(
            self.before_chat,
            label="knowledge_before_chat",
        )

    def init_chat(self, context: InitChatContext) -> None:
        self.enabled = False
        self.character_names = list(context.character_names)
        if not self.character_names or self.status_func is None:
            return
        self.enabled = prepare_knowledge(context, knowledge_status_func=self.status_func)

    def before_chat(self, context: BeforeChatContext) -> None:
        if not self.enabled:
            return
        if any(_MARKER in str(message.get("content") or "") for message in context.messages):
            return
        query = ""
        for message in reversed(context.messages):
            if message.get("role") == "system":
                continue
            if message.get("role") == "user":
                query = strip_local_time_prefix(str(message.get("content") or "").strip())
            break
        if not query or not self.character_names or self.search_func is None:
            return
        try:
            result = self.search_func(
                query,
                character_names=self.character_names,
                limit=self.search_limit,
            )
        except Exception:
            logger.exception("Automatic knowledge search failed")
            return
        if isinstance(result, dict) and (result.get("error") or result.get("status") in {"error", "missing_dependency"}):
            logger.warning("Knowledge unavailable: %s", result.get("message") or result.get("error"))
            return
        rows = result.get("memories") if isinstance(result, dict) else []
        if not isinstance(rows, list) or not rows:
            return
        texts: list[str] = []
        for row in rows:
            text = str(
                (row.get("memory") or row.get("content") or "") if isinstance(row, dict) else row
            ).strip()
            if text:
                texts.append(text)
        if texts:
            context.messages.append(
                {
                    "role": "system",
                    "content": f"{_MARKER}\n" + "\n".join(
                        f"- {text}" for text in texts[: self.search_limit]
                    ),
                }
            )


def install_knowledge_hooks(
    dispatcher: PluginHookDispatcher | None,
    *,
    character_names: list[str] | None = None,
    search_func=None,
    status_func=None,
) -> KnowledgeHooks | None:
    if dispatcher is None or search_func is None or status_func is None:
        return None
    hooks = KnowledgeHooks(
        character_names=character_names,
        search_func=search_func,
        status_func=status_func,
        search_limit=min(20, _env_int("SHINSEKAI_KNOWLEDGE_SEARCH_LIMIT", DEFAULT_SEARCH_LIMIT)),
    )
    hooks.register(dispatcher)
    return hooks


def prepare_knowledge(
    context: InitChatContext,
    *,
    knowledge_status_func,
    timeout: float = 600.0,
    poll_interval: float = 0.45,
    sleep_func=time.sleep,
    monotonic_func=time.monotonic,
) -> bool:
    """Return whether retrieval is ready; cancellation always aborts startup."""
    try:
        return _wait_for_knowledge(
            context, knowledge_status_func=knowledge_status_func, timeout=timeout,
            poll_interval=poll_interval, sleep_func=sleep_func, monotonic_func=monotonic_func,
        )
    except InitChatCancelled:
        raise
    except Exception as exc:
        context.raise_if_cancelled()
        logger.warning("Knowledge warm-up failed; continuing without retrieval: %s", exc)
        context.report(
            1.0, "Knowledge is unavailable; continuing without knowledge.",
            phase="knowledge.degraded", log=f"Knowledge warm-up failed: {exc}",
        )
        return False


def _wait_for_knowledge(
    context, *, knowledge_status_func, timeout, poll_interval, sleep_func, monotonic_func,
) -> bool:
    deadline = monotonic_func() + max(0.01, float(timeout))
    start_loading = True
    forwarded_log_count = 0
    while True:
        context.raise_if_cancelled()
        result = knowledge_status_func(start_loading=start_loading)
        start_loading = False
        context.raise_if_cancelled()
        if result is None:
            context.report(
                1.0, "Knowledge service is unavailable; continuing without knowledge.",
                phase="knowledge",
                log="Knowledge warm-up skipped because no knowledge service is configured.",
            )
            return False
        if not isinstance(result, dict):
            raise RuntimeError("knowledge service returned an invalid status response")
        task = result.get("task")
        if isinstance(task, dict):
            task_logs = [str(line) for line in (task.get("logs") or []) if str(line).strip()]
            if forwarded_log_count > len(task_logs):
                forwarded_log_count = 0
            new_logs = task_logs[forwarded_log_count:]
            forwarded_log_count = len(task_logs)
            try:
                progress = None if task.get("progress") is None else float(task["progress"])
            except (TypeError, ValueError):
                progress = None
            context.report(
                progress,
                str(task.get("message") or result.get("message") or "Loading knowledge."),
                phase=f"knowledge.{str(task.get('phase') or 'loading')}",
                logs=new_logs,
            )
        status = str(result.get("status") or "").strip().lower()
        if status == "ready":
            context.report(1.0, "Knowledge is ready.", phase="knowledge")
            return True
        if status in {"loading", "not_started"}:
            if monotonic_func() >= deadline:
                raise TimeoutError("knowledge initialization timed out")
            sleep_func(min(max(0.01, float(poll_interval)), max(0.0, deadline - monotonic_func())))
            continue
        if status == "missing_dependency":
            module_name = str(result.get("moduleName") or "mem0")
            raise RuntimeError(f"Knowledge dependency is unavailable: {module_name}.")
        error = str(
            result.get("errorUserMessage") or result.get("message") or result.get("error") or ""
        ).strip()
        raise RuntimeError(error or f"unexpected knowledge service status: {status or 'unknown'}")
