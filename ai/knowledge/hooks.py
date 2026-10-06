"""Automatic knowledge retrieval before an LLM request."""

from __future__ import annotations

import logging
import os
import time

from typing import Any

from ai.knowledge.operations import search_knowledge
from ai.knowledge.service import knowledge_service_status
from sdk.chat_init import InitChatContext
from sdk.hooks import BeforeChatContext, PluginHookDispatcher

logger = logging.getLogger(__name__)

DEFAULT_SEARCH_LIMIT = 5
DEFAULT_INIT_POLL_INTERVAL_SECONDS = 0.45
DEFAULT_INIT_TIMEOUT_SECONDS = 600.0
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


def _env_enabled(name: str, default: bool = True) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off"}


class KnowledgeHooks:
    def __init__(
        self,
        character_names: list[str] | None = None,
        *,
        search_func=search_knowledge,
        search_limit: int = DEFAULT_SEARCH_LIMIT,
        knowledge_status_func=knowledge_service_status,
        init_poll_interval_seconds: float = DEFAULT_INIT_POLL_INTERVAL_SECONDS,
        init_timeout_seconds: float = DEFAULT_INIT_TIMEOUT_SECONDS,
        sleep_func=time.sleep,
        monotonic_func=time.monotonic,
    ) -> None:
        self.character_names = [
            str(name or "").strip()
            for name in (character_names or [])
            if str(name or "").strip()
        ]
        self.search_func = search_func
        self.search_limit = max(1, int(search_limit))
        self.knowledge_status_func = knowledge_status_func
        self.init_poll_interval_seconds = max(0.01, float(init_poll_interval_seconds))
        self.init_timeout_seconds = max(0.01, float(init_timeout_seconds))
        self._sleep = sleep_func
        self._monotonic = monotonic_func

    def register(self, dispatcher: PluginHookDispatcher) -> None:
        dispatcher.register_init_chat(
            self.init_chat, label="knowledge", weight=3.0, critical=False,
        )
        dispatcher.register_before_chat(
            self.before_chat,
            label="knowledge_before_chat",
        )

    def init_chat(self, context: InitChatContext) -> None:
        """Warm the bridge-owned knowledge service before chat becomes interactive."""
        deadline = self._monotonic() + self.init_timeout_seconds
        start_loading = True
        forwarded_log_count = 0
        while True:
            context.raise_if_cancelled()
            result = self.knowledge_status_func(start_loading=start_loading)
            start_loading = False
            if result is None:
                context.report(
                    1.0, "Knowledge service is unavailable; continuing without knowledge.",
                    phase="knowledge",
                    log="Knowledge warm-up skipped because no bridge knowledge service is configured.",
                )
                return
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
                return
            if status in {"loading", "not_started"}:
                if self._monotonic() >= deadline:
                    raise TimeoutError("knowledge initialization timed out")
                self._sleep(self.init_poll_interval_seconds)
                continue
            if status == "missing_dependency":
                module_name = str(result.get("moduleName") or "mem0")
                raise RuntimeError(f"Knowledge dependency is unavailable: {module_name}.")
            error = str(
                result.get("errorUserMessage") or result.get("message") or result.get("error") or ""
            ).strip()
            raise RuntimeError(error or f"unexpected knowledge service status: {status or 'unknown'}")

    def before_chat(self, context: BeforeChatContext) -> None:
        if any(_MARKER in str(message.get("content") or "") for message in context.messages):
            return
        query = ""
        for message in reversed(context.messages):
            if message.get("role") == "system":
                continue
            if message.get("role") == "user":
                query = str(message.get("content") or "").strip()
            break
        if not query or not self.character_names:
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
) -> KnowledgeHooks | None:
    if dispatcher is None or not _env_enabled("SHINSEKAI_KNOWLEDGE_ENABLED", False):
        return None
    hooks = KnowledgeHooks(
        character_names=character_names,
        search_limit=min(20, _env_int("SHINSEKAI_KNOWLEDGE_SEARCH_LIMIT", DEFAULT_SEARCH_LIMIT)),
    )
    hooks.register(dispatcher)
    return hooks
