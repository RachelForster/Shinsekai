"""Automatic knowledge retrieval before an LLM request."""

from __future__ import annotations

import logging
import os

from application.knowledge.manage_knowledge import search_knowledge
from sdk.hooks import BeforeChatContext, PluginHookDispatcher

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
    ) -> None:
        self.character_names = [
            str(name or "").strip()
            for name in (character_names or [])
            if str(name or "").strip()
        ]
        self.search_func = search_func
        self.search_limit = max(1, int(search_limit))
        self.enabled = True

    def register(self, dispatcher: PluginHookDispatcher) -> None:
        dispatcher.register_before_chat(
            self.before_chat,
            label="knowledge_before_chat",
        )

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
                query = str(message.get("content") or "").strip()
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
    search_func=search_knowledge,
) -> KnowledgeHooks | None:
    if dispatcher is None or not _env_enabled("SHINSEKAI_KNOWLEDGE_ENABLED", False):
        return None
    hooks = KnowledgeHooks(
        character_names=character_names,
        search_func=search_func,
        search_limit=min(20, _env_int("SHINSEKAI_KNOWLEDGE_SEARCH_LIMIT", DEFAULT_SEARCH_LIMIT)),
    )
    hooks.register(dispatcher)
    return hooks
