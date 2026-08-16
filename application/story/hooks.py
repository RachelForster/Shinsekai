"""Inject bound-story scene context through the existing before_chat hook."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core.sprite.chat_branch_storage import chat_history_session_dir
from sdk.chat_init import InitChatContext
from sdk.hooks import BeforeChatContext, PluginHookDispatcher

logger = logging.getLogger(__name__)

STORY_CHAT_PROMPT_FILENAME = "story-chat-prompt.json"
_LEGACY_STORY_CHAT_PROMPT_FILENAME = "story-chat-prompt.txt"
_PLAYER_MESSAGE_MARKER = "[用户消息]"


@dataclass(frozen=True, slots=True)
class StoryChatPrompt:
    user: str = ""
    system: str = ""

    @property
    def available(self) -> bool:
        return bool(str(self.user or "").strip() or str(self.system or "").strip())


def story_chat_prompt_path(history_path: str | Path | None) -> Path | None:
    raw = str(history_path or "").strip()
    if not raw:
        return None
    return chat_history_session_dir(raw) / STORY_CHAT_PROMPT_FILENAME


def story_chat_prompt_available(history_path: str | Path | None) -> bool:
    return read_story_chat_prompt(history_path).available


def write_story_chat_prompt(
    history_path: str | Path | None,
    prompt: StoryChatPrompt | str,
    *,
    system: str = "",
) -> None:
    path = story_chat_prompt_path(history_path)
    if path is None:
        return
    payload = _as_prompt(prompt, system=system)
    if not payload.available:
        discard_story_chat_prompt(history_path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"user": payload.user, "system": payload.system}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    legacy = path.with_name(_LEGACY_STORY_CHAT_PROMPT_FILENAME)
    legacy.unlink(missing_ok=True)


def read_story_chat_prompt(history_path: str | Path | None) -> StoryChatPrompt:
    path = story_chat_prompt_path(history_path)
    if path is not None and path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("story chat prompt is unreadable", exc_info=True)
            return StoryChatPrompt()
        if isinstance(raw, dict):
            return StoryChatPrompt(
                user=str(raw.get("user") or "").strip(),
                system=str(raw.get("system") or "").strip(),
            )
        if isinstance(raw, str):
            return StoryChatPrompt(user=raw.strip())
        return StoryChatPrompt()
    if path is None:
        return StoryChatPrompt()
    legacy = path.with_name(_LEGACY_STORY_CHAT_PROMPT_FILENAME)
    if not legacy.is_file():
        return StoryChatPrompt()
    try:
        return StoryChatPrompt(user=legacy.read_text(encoding="utf-8").strip())
    except OSError:
        logger.warning("story chat prompt is unreadable", exc_info=True)
        return StoryChatPrompt()


def discard_story_chat_prompt(history_path: str | Path | None) -> None:
    path = story_chat_prompt_path(history_path)
    if path is None:
        return
    path.unlink(missing_ok=True)
    path.with_name(_LEGACY_STORY_CHAT_PROMPT_FILENAME).unlink(missing_ok=True)


class StoryChatHooks:
    """Apply the story system at chat start; splice scene context into user turns."""

    def __init__(
        self,
        *,
        prompt_loader: Callable[[], StoryChatPrompt | str],
        llm_manager: Any | None = None,
    ) -> None:
        self._prompt_loader = prompt_loader
        self._llm_manager = llm_manager

    def register(self, dispatcher: PluginHookDispatcher) -> None:
        dispatcher.register_init_chat(self.init_chat, label="story", weight=0.5)
        dispatcher.register_before_chat(self.before_chat, label="story_scene_before_chat")

    def init_chat(self, context: InitChatContext) -> None:
        context.report(0.0, "Applying the story system prompt.", phase="story")
        self.apply_system()
        context.report(1.0, "Story system prompt is ready.", phase="story")

    def apply_system(self) -> None:
        prompt = _as_prompt(self._prompt_loader())
        apply_story_system(self._llm_manager, prompt.system)

    def before_chat(self, context: BeforeChatContext) -> None:
        if not _should_inject_story_prompt(context.messages):
            return
        prompt = _as_prompt(self._prompt_loader())
        _splice_user_scene(context.messages, prompt.user)


def install_story_hooks(
    dispatcher: PluginHookDispatcher | None,
    *,
    history_path: str | Path | None = "",
    llm_manager: Any | None = None,
    prompt_loader: Callable[[], StoryChatPrompt | str] | None = None,
) -> StoryChatHooks | None:
    if dispatcher is None:
        return None
    loader = prompt_loader or (lambda: read_story_chat_prompt(history_path))
    hooks = StoryChatHooks(prompt_loader=loader, llm_manager=llm_manager)
    hooks.register(dispatcher)
    logger.info(
        "story chat hooks installed",
        extra={"event": "story.chat_hooks.installed"},
    )
    return hooks


def _as_prompt(prompt: StoryChatPrompt | str, *, system: str = "") -> StoryChatPrompt:
    if isinstance(prompt, StoryChatPrompt):
        return StoryChatPrompt(
            user=str(prompt.user or "").strip(),
            system=str(prompt.system or system or "").strip(),
        )
    return StoryChatPrompt(user=str(prompt or "").strip(), system=str(system or "").strip())


def apply_story_system(llm_manager: Any | None, extra: str) -> None:
    text = str(extra or "").strip()
    if llm_manager is None or not text:
        return
    template = str(getattr(llm_manager, "user_template", "") or "")
    if text not in template:
        merged = f"{template.rstrip()}\n\n{text}".strip() if template.strip() else text
        llm_manager.user_template = merged
        adapter = getattr(llm_manager, "llm_adapter", None)
        setter = getattr(adapter, "set_user_template", None)
        if callable(setter):
            setter(merged)
    messages = getattr(llm_manager, "messages", None)
    if not isinstance(messages, list):
        return
    _merge_leading_system(messages, text)


def _should_inject_story_prompt(messages: list[dict[str, Any]]) -> bool:
    for message in reversed(messages):
        role = str(message.get("role") or "")
        if role == "system":
            continue
        return role == "user"
    return True


def _merge_leading_system(messages: list[dict[str, Any]], extra: str) -> None:
    text = str(extra or "").strip()
    if not text:
        return
    if messages and str(messages[0].get("role") or "") == "system":
        content = str(messages[0].get("content") or "")
        if text in content:
            return
        prefix = content.rstrip()
        messages[0] = {
            **messages[0],
            "content": f"{prefix}\n\n{text}".strip() if prefix else text,
        }
        return
    messages.insert(0, {"role": "system", "content": text})


def _splice_user_scene(messages: list[dict[str, Any]], extra: str) -> None:
    text = str(extra or "").strip()
    if not text:
        return
    for index in range(len(messages) - 1, -1, -1):
        if str(messages[index].get("role") or "") != "user":
            continue
        content = str(messages[index].get("content") or "")
        if text in content:
            return
        player = content.strip()
        player_block = f"{_PLAYER_MESSAGE_MARKER}\n{player}" if player else ""
        messages[index] = {
            **messages[index],
            "content": f"{text}\n\n{player_block}".strip() if player_block else text,
        }
        return
    messages.append({"role": "user", "content": text})
