"""Built-in chat hooks for automatic long-term memory use."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import Any

from ai.memory.operations import memory_search
from ai.memory.queue import MemoryWriteQueue
from sdk.hooks import BeforeChatContext, MessageAddedContext, PluginHookDispatcher

logger = logging.getLogger(__name__)

DEFAULT_EXTRACT_INTERVAL_TURNS = 5
DEFAULT_SEARCH_LIMIT = 5
DEFAULT_RECENT_BUFFER_MESSAGES = 16
_INJECTION_MARKER = "[Shinsekai long-term memory context]"
_SYSTEM_CHARACTER_NAMES = {"cot", "narr", "choice", "stat", "scene", "bgm", "cg"}


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


def _clean_text(value: Any, *, max_chars: int = 4000) -> str:
    text = str(value or "").strip()
    if len(text) > max_chars:
        return text[:max_chars].rstrip()
    return text


def _strip_local_time_prefix(text: str) -> str:
    return re.sub(r"^\[[^\]\n]*(?:本地时间|Local time)[^\]\n]*\]\s*", "", text).strip()


def _extract_response_text(response: Any) -> str:
    if response is None:
        return ""
    try:
        if hasattr(response, "choices") and response.choices:
            message = response.choices[0].message
            return str(getattr(message, "content", "") or "")
        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, list) and content:
                return str(getattr(content[0], "text", "") or content[0])
            return str(content or "")
        if hasattr(response, "text"):
            return str(response.text or "")
    except Exception:
        logger.exception("failed to extract memory summary response")
    return str(response)


def _parse_json_payload(text: str) -> Any:
    raw = _clean_text(text, max_chars=20000)
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _memory_rows(result: dict[str, Any]) -> list[str]:
    rows = result.get("memories") or result.get("results") or []
    if not isinstance(rows, list):
        return []
    memories: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            text = _clean_text(row.get("memory") or row.get("content") or row.get("text"), max_chars=600)
        else:
            text = _clean_text(row, max_chars=600)
        if text:
            memories.append(text)
    return memories


def _dialog_speaker_names(content: Any) -> list[str]:
    parsed = _parse_json_payload(_clean_text(content, max_chars=20000))
    if not isinstance(parsed, dict):
        return []
    dialog = parsed.get("dialog")
    if not isinstance(dialog, list):
        return []
    names: list[str] = []
    for item in dialog:
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("character_name") or item.get("name"), max_chars=120)
        if not name or name.casefold() in _SYSTEM_CHARACTER_NAMES:
            continue
        names.append(name)
    return names


class MemoryAutoHooks:
    """Owns automatic retrieval injection and periodic extraction."""

    def __init__(
        self,
        *,
        llm_adapter: Any,
        character_names: list[str] | None = None,
        queue: MemoryWriteQueue | None = None,
        search_func=memory_search,
        extract_interval_turns: int = DEFAULT_EXTRACT_INTERVAL_TURNS,
        search_limit: int = DEFAULT_SEARCH_LIMIT,
        recent_buffer_messages: int = DEFAULT_RECENT_BUFFER_MESSAGES,
    ) -> None:
        self.llm_adapter = llm_adapter
        self.character_names = [name.strip() for name in (character_names or []) if str(name or "").strip()]
        self._active_character_name = self.character_names[0] if self.character_names else "user"
        self.queue = queue if queue is not None else MemoryWriteQueue()
        self.search_func = search_func
        self.extract_interval_turns = max(1, int(extract_interval_turns))
        self.search_limit = max(1, int(search_limit))
        self.recent_buffer_messages = max(2, int(recent_buffer_messages))
        self._lock = threading.RLock()
        self._summary_lock = threading.Lock()
        self._buffer: list[dict[str, str]] = []
        self._user_turns = 0
        self._last_extract_turn = 0
        self._last_injected_user = ""
        self._workers: list[threading.Thread] = []

    @property
    def primary_character_name(self) -> str:
        with self._lock:
            return self._active_character_name or (self.character_names[0] if self.character_names else "user")

    def register(self, dispatcher: PluginHookDispatcher) -> None:
        dispatcher.register_before_chat(self.before_chat, label="memory_auto_before_chat")
        dispatcher.register_message_added(self.message_added, label="memory_auto_message_added")

    def before_chat(self, context: BeforeChatContext) -> None:
        user_text = self._latest_user_text_for_fresh_turn(context.messages)
        if not user_text:
            return
        if any(_INJECTION_MARKER in str(message.get("content") or "") for message in context.messages):
            return
        query = _strip_local_time_prefix(user_text)
        if not query:
            return
        key = query.casefold()
        with self._lock:
            if self._last_injected_user == key:
                return
            self._last_injected_user = key
        try:
            result = self.search_func(query, character_name=self.primary_character_name, limit=self.search_limit)
        except Exception:
            logger.exception("automatic memory search failed")
            return
        if not isinstance(result, dict) or result.get("error") or result.get("status") == "loading":
            return
        memories = _memory_rows(result)
        if not memories:
            return
        context.messages.append(
            {
                "role": "system",
                "content": self._format_memory_context(memories),
            }
        )

    def message_added(self, context: MessageAddedContext) -> None:
        role = str(context.role or "")
        if role not in {"user", "assistant"}:
            return
        message = context.message or {}
        if role == "assistant" and message.get("tool_calls"):
            return
        content = _clean_text(message.get("content"), max_chars=4000)
        if not content:
            return
        should_extract = False
        with self._lock:
            if role == "user":
                self._user_turns += 1
                self._last_injected_user = ""
            elif role == "assistant":
                speaker_names = _dialog_speaker_names(content)
                if speaker_names:
                    self._active_character_name = speaker_names[-1]
            self._buffer.append({"role": role, "content": content})
            self._buffer = self._buffer[-self.recent_buffer_messages :]
            if (
                role == "assistant"
                and self._user_turns >= self._last_extract_turn + self.extract_interval_turns
            ):
                self._last_extract_turn = self._user_turns
                snapshot = list(self._buffer)
                turn = self._user_turns
                should_extract = True
            else:
                snapshot = []
                turn = self._user_turns
        if should_extract:
            self._start_extraction(snapshot, source=f"periodic:{turn}")

    def shutdown(self, *, wait_timeout: float = 3.0) -> dict[str, Any]:
        for worker in self._live_workers():
            worker.join(timeout=max(0.0, wait_timeout))
        return self.queue.flush()

    def wait_for_idle(self, timeout: float = 3.0) -> None:
        for worker in self._live_workers():
            worker.join(timeout=timeout)

    def _start_extraction(self, messages: list[dict[str, str]], *, source: str) -> None:
        worker = threading.Thread(
            target=self._extract_enqueue_and_flush,
            args=(messages, source),
            name="memory-auto-extractor",
            daemon=True,
        )
        with self._lock:
            self._workers = self._live_workers_locked()
            self._workers.append(worker)
        worker.start()

    def _extract_enqueue_and_flush(self, messages: list[dict[str, str]], source: str) -> None:
        with self._summary_lock:
            try:
                extracted = self._extract_memories(messages)
                for item in extracted:
                    self.queue.enqueue(
                        item["memory"],
                        character_name=item.get("character_name") or self.primary_character_name,
                        source=source,
                        confidence=float(item.get("confidence", 1.0)),
                    )
                self.queue.flush()
            except Exception:
                logger.exception("automatic memory extraction failed")

    def _extract_memories(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        prompt = self._build_extraction_prompt(messages)
        response = self.llm_adapter.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You extract durable long-term memories from roleplay chat. "
                        "Return only JSON. Do not include prose."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            stream=False,
            response_format={"type": "text"},
        )
        parsed = _parse_json_payload(_extract_response_text(response))
        if isinstance(parsed, dict):
            parsed = parsed.get("memories") or parsed.get("items") or []
        if not isinstance(parsed, list):
            return []
        out: list[dict[str, Any]] = []
        for row in parsed:
            if not isinstance(row, dict):
                continue
            memory = _clean_text(row.get("memory") or row.get("content"), max_chars=800)
            if not memory:
                continue
            try:
                confidence = float(row.get("confidence", 1.0))
            except (TypeError, ValueError):
                confidence = 1.0
            out.append(
                {
                    "character_name": _clean_text(row.get("character_name") or row.get("characterName"))
                    or self.primary_character_name,
                    "memory": memory,
                    "confidence": max(0.0, min(1.0, confidence)),
                }
            )
        return out[:8]

    def _latest_user_text_for_fresh_turn(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            role = message.get("role")
            if role == "system":
                continue
            if role == "user":
                return _clean_text(message.get("content"), max_chars=2000)
            return ""
        return ""

    def _format_memory_context(self, memories: list[str]) -> str:
        body = "\n".join(f"- {memory}" for memory in memories[: self.search_limit])
        return (
            f"{_INJECTION_MARKER}\n"
            "Relevant long-term memories for this turn. Use them only as background; "
            "do not mention the retrieval process unless the user asks.\n"
            f"{body}"
        )

    def _build_extraction_prompt(self, messages: list[dict[str, str]]) -> str:
        rows = "\n".join(f"{item['role']}: {item['content']}" for item in messages)
        return (
            "Extract stable, useful long-term memories from the chat below.\n"
            "Keep only durable facts, preferences, relationships, promises, goals, or character-relevant state.\n"
            "Ignore temporary emotions, filler, one-off phrasing, and duplicates.\n"
            f"Default character_name is {self.primary_character_name!r}.\n"
            "Return JSON array only, each item like:\n"
            '[{"character_name":"Name","memory":"fact to save","confidence":0.85}]\n\n'
            f"Chat:\n{rows}"
        )

    def _live_workers(self) -> list[threading.Thread]:
        with self._lock:
            self._workers = self._live_workers_locked()
            return list(self._workers)

    def _live_workers_locked(self) -> list[threading.Thread]:
        return [worker for worker in self._workers if worker.is_alive()]


def install_memory_hooks(
    dispatcher: PluginHookDispatcher | None,
    *,
    llm_adapter: Any,
    character_names: list[str] | None = None,
    queue: MemoryWriteQueue | None = None,
) -> MemoryAutoHooks | None:
    if dispatcher is None or not _env_enabled("SHINSEKAI_MEMORY_AUTO_ENABLED", True):
        return None
    hooks = MemoryAutoHooks(
        llm_adapter=llm_adapter,
        character_names=character_names,
        queue=queue,
        extract_interval_turns=_env_int("SHINSEKAI_MEMORY_EXTRACT_INTERVAL_TURNS", DEFAULT_EXTRACT_INTERVAL_TURNS),
        search_limit=_env_int("SHINSEKAI_MEMORY_SEARCH_LIMIT", DEFAULT_SEARCH_LIMIT),
        recent_buffer_messages=_env_int(
            "SHINSEKAI_MEMORY_RECENT_BUFFER_MESSAGES",
            DEFAULT_RECENT_BUFFER_MESSAGES,
            minimum=2,
        ),
    )
    hooks.register(dispatcher)
    try:
        from sdk.hooks import register_shutdown_hook

        register_shutdown_hook(hooks.shutdown, label="memory_shutdown")
    except Exception:
        logger.exception("failed to register memory shutdown hook")
    logger.info(
        "automatic memory hooks installed",
        extra={
            "event": "memory.auto_hooks.installed",
            "character_names": hooks.character_names,
            "extract_interval_turns": hooks.extract_interval_turns,
        },
    )
    return hooks
