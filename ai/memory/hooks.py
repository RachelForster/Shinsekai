"""Built-in chat hooks for automatic long-term memory use."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from ai.memory.chunking import DEFAULT_DIALOGUE_CHUNK_TOKENS
from ai.memory.extraction import MemoryExtractor
from ai.memory.operations import memory_search, memory_service_status
from ai.memory.queue import MemoryWriteQueue
from core.chat_history.models import is_compact_summary_message
from core.chat_history.text import (
    history_payload_to_plain_text,
    parse_assistant_dialog_content,
    strip_local_time_prefix,
)
from sdk.chat_init import InitChatContext
from sdk.hooks import (
    BeforeChatContext,
    BeforeCompactContext,
    MessageAddedContext,
    PluginHookDispatcher,
)

logger = logging.getLogger(__name__)

DEFAULT_EXTRACT_INTERVAL_TURNS = 5
DEFAULT_SEARCH_LIMIT = 5
DEFAULT_RECENT_BUFFER_MESSAGES = 16
DEFAULT_INIT_POLL_INTERVAL_SECONDS = 0.45
DEFAULT_INIT_TIMEOUT_SECONDS = 600.0
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
    dialog = parse_assistant_dialog_content(content)
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
        session_id: str = "",
        queue: MemoryWriteQueue | None = None,
        search_func=memory_search,
        extract_interval_turns: int = DEFAULT_EXTRACT_INTERVAL_TURNS,
        search_limit: int = DEFAULT_SEARCH_LIMIT,
        recent_buffer_messages: int = DEFAULT_RECENT_BUFFER_MESSAGES,
        extraction_chunk_tokens: int = DEFAULT_DIALOGUE_CHUNK_TOKENS,
        memory_status_func=memory_service_status,
        init_poll_interval_seconds: float = DEFAULT_INIT_POLL_INTERVAL_SECONDS,
        init_timeout_seconds: float = DEFAULT_INIT_TIMEOUT_SECONDS,
        sleep_func=time.sleep,
        monotonic_func=time.monotonic,
    ) -> None:
        self.llm_adapter = llm_adapter
        self.character_names = [name.strip() for name in (character_names or []) if str(name or "").strip()]
        self._active_character_name = self.character_names[0] if self.character_names else "user"
        self.session_id = str(session_id or "").strip()
        self.queue = queue if queue is not None else MemoryWriteQueue()
        self.search_func = search_func
        self.extract_interval_turns = max(1, int(extract_interval_turns))
        self.search_limit = max(1, int(search_limit))
        self.recent_buffer_messages = max(2, int(recent_buffer_messages))
        self.extraction_chunk_tokens = max(256, int(extraction_chunk_tokens))
        self.memory_status_func = memory_status_func
        self.init_poll_interval_seconds = max(0.01, float(init_poll_interval_seconds))
        self.init_timeout_seconds = max(0.01, float(init_timeout_seconds))
        self._sleep = sleep_func
        self._monotonic = monotonic_func
        self._lock = threading.RLock()
        self._summary_lock = threading.Lock()
        self._buffer: list[dict[str, Any]] = []
        self._user_turns = 0
        self._last_extract_turn = 0
        self._last_extracted_seq = 0
        self._last_seen_seq = 0
        self._last_injected_user = ""
        self._workers: list[threading.Thread] = []
        self._extractor = MemoryExtractor(llm_adapter)

    @property
    def primary_character_name(self) -> str:
        with self._lock:
            return self._active_character_name or (self.character_names[0] if self.character_names else "user")

    def register(self, dispatcher: PluginHookDispatcher) -> None:
        dispatcher.register_init_chat(
            self.init_chat,
            label="memory",
            weight=3.0,
            critical=False,
        )
        dispatcher.register_before_chat(self.before_chat, label="memory_auto_before_chat")
        dispatcher.register_before_compact(self.before_compact, label="memory_auto_before_compact")
        dispatcher.register_message_added(self.message_added, label="memory_auto_message_added")

    def init_chat(self, context: InitChatContext) -> None:
        """Warm the bridge-owned memory service and forward its task progress.

        The chat child must not instantiate mem0 itself. Its bridge URL is
        configured through ``SHINSEKAI_MEMORY_SERVICE_URL``; when no service is
        available we keep chat usable without silently installing anything.
        """

        if not context.memory_enabled:
            context.report(1.0, "Long-term memory is disabled.", phase="memory")
            return

        deadline = self._monotonic() + self.init_timeout_seconds
        start_loading = True
        forwarded_log_count = 0
        while True:
            context.raise_if_cancelled()
            result = self.memory_status_func(
                start_loading=start_loading,
                monitor_ready=False,
            )
            start_loading = False
            if result is None:
                context.report(
                    1.0,
                    "Long-term memory service is unavailable; continuing without memory.",
                    phase="memory",
                    log="Memory warm-up skipped because no bridge memory service is configured.",
                )
                return
            if not isinstance(result, dict):
                raise RuntimeError("memory service returned an invalid status response")

            task = result.get("task")
            if isinstance(task, dict):
                task_logs = [str(line) for line in (task.get("logs") or []) if str(line).strip()]
                if forwarded_log_count > len(task_logs):
                    forwarded_log_count = 0
                new_logs = task_logs[forwarded_log_count:]
                forwarded_log_count = len(task_logs)
                raw_progress = task.get("progress")
                try:
                    progress = None if raw_progress is None else float(raw_progress)
                except (TypeError, ValueError):
                    progress = None
                context.report(
                    progress,
                    str(task.get("message") or result.get("message") or "Loading long-term memory."),
                    phase=f"memory.{str(task.get('phase') or 'loading')}",
                    logs=new_logs,
                )

            status = str(result.get("status") or "").strip().lower()
            if status == "ready":
                context.report(1.0, "Long-term memory is ready.", phase="memory")
                return
            if status in {"loading", "not_started"}:
                if self._monotonic() >= deadline:
                    raise TimeoutError("long-term memory initialization timed out")
                self._sleep(self.init_poll_interval_seconds)
                continue
            if status == "missing_dependency":
                module_name = str(result.get("moduleName") or "mem0")
                raise RuntimeError(
                    f"Long-term memory dependency is unavailable: {module_name}. "
                    "Chat will continue without memory."
                )
            error = str(
                result.get("errorUserMessage")
                or result.get("message")
                or result.get("error")
                or ""
            ).strip()
            if status == "error" or error:
                raise RuntimeError(error or "long-term memory initialization failed")
            raise RuntimeError(f"unexpected memory service status: {status or 'unknown'}")

    def before_chat(self, context: BeforeChatContext) -> None:
        user_text = self._latest_user_text_for_fresh_turn(context.messages)
        if not user_text:
            return
        if any(_INJECTION_MARKER in str(message.get("content") or "") for message in context.messages):
            return
        query = strip_local_time_prefix(user_text)
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
        if is_compact_summary_message(message) or message.get("source") == "perception":
            return
        if role == "assistant" and message.get("tool_calls"):
            return
        raw_content = message.get("content")
        content = _clean_text(
            history_payload_to_plain_text([message], user_display_name="user"),
            max_chars=20000,
        )
        if not content:
            return
        turn_seq = context.turn_seq
        effective_session = str(context.session_id or self.session_id or "").strip()
        should_extract = False
        extract_seq: int | None = None
        with self._lock:
            if effective_session and not self.session_id:
                self.session_id = effective_session
            if turn_seq is not None and int(turn_seq) > self._last_seen_seq:
                self._last_seen_seq = int(turn_seq)
            if role == "user":
                self._user_turns += 1
                self._last_injected_user = ""
            elif role == "assistant":
                speaker_names = _dialog_speaker_names(raw_content)
                if speaker_names:
                    self._active_character_name = speaker_names[-1]
            self._buffer.append(
                {
                    "role": role,
                    "content": content,
                    "turn_seq": None if turn_seq is None else int(turn_seq),
                }
            )
            self._buffer = self._buffer[-self.recent_buffer_messages :]
            if (
                role == "assistant"
                and self._user_turns >= self._last_extract_turn + self.extract_interval_turns
            ):
                self._last_extract_turn = self._user_turns
                snapshot = list(self._buffer)
                turn = self._user_turns
                seqs = [int(item["turn_seq"]) for item in snapshot if item.get("turn_seq") is not None]
                extract_seq = max(seqs) if seqs else (int(turn_seq) if turn_seq is not None else None)
                if extract_seq is not None and extract_seq > self._last_extracted_seq:
                    self._last_extracted_seq = extract_seq
                should_extract = True
            else:
                snapshot = []
                turn = self._user_turns
        if should_extract:
            self._start_extraction(
                snapshot,
                source=f"periodic:{turn}",
                session_id=effective_session,
                turn_seq=extract_seq,
            )

    def before_compact(self, context: BeforeCompactContext) -> None:
        """Extract unpersisted memories from older_messages before compaction summarizes them."""
        older = list(context.older_messages or [])
        if not older:
            return
        effective_session = str(context.session_id or self.session_id or "").strip()
        anchor_seq = context.up_to_seq

        snapshot: list[dict[str, Any]] = []
        with self._lock:
            if effective_session and not self.session_id:
                self.session_id = effective_session
            if (
                anchor_seq is not None
                and self._last_extracted_seq > 0
                and int(anchor_seq) <= self._last_extracted_seq
            ):
                return

            for message in older:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role") or "")
                if role not in {"user", "assistant"}:
                    continue
                if is_compact_summary_message(message) or message.get("source") == "perception":
                    continue
                if role == "assistant" and message.get("tool_calls"):
                    continue
                content = _clean_text(
                    history_payload_to_plain_text([message], user_display_name="user"),
                    max_chars=20000,
                )
                if not content:
                    continue
                if role == "assistant":
                    speaker_names = _dialog_speaker_names(message.get("content"))
                    if speaker_names:
                        self._active_character_name = speaker_names[-1]
                snapshot.append({"role": role, "content": content, "turn_seq": anchor_seq})

            if not snapshot:
                return
            if anchor_seq is not None:
                self._last_extracted_seq = max(self._last_extracted_seq, int(anchor_seq))
                self._buffer = [
                    item
                    for item in self._buffer
                    if item.get("turn_seq") is not None and int(item["turn_seq"]) > int(anchor_seq)
                ]
            else:
                self._buffer.clear()
            self._last_extract_turn = self._user_turns

        self._extract_enqueue_and_flush(
            snapshot,
            source=f"before_compact:{anchor_seq if anchor_seq is not None else self._user_turns}",
            session_id=effective_session,
            turn_seq=anchor_seq,
        )

    def rollback_after_turn(self, session_id: str, turn_seq: int) -> int:
        """Synchronize buffered hook state and pending write queue on session revert/reroll."""
        sid = str(session_id or "").strip()
        cutoff = max(0, int(turn_seq))
        with self._lock:
            if not sid or not self.session_id or sid == self.session_id:
                self._buffer = [
                    item
                    for item in self._buffer
                    if item.get("turn_seq") is not None and int(item["turn_seq"]) <= cutoff
                ]
                self._last_extracted_seq = min(self._last_extracted_seq, cutoff)
                self._last_seen_seq = min(self._last_seen_seq, cutoff)
                self._last_injected_user = ""
        return self.queue.rollback_after_turn(sid, cutoff)

    def shutdown(self, *, wait_timeout: float = 3.0) -> dict[str, Any]:
        tail_snapshot, tail_turn, tail_seq, tail_session = self._shutdown_tail_snapshot()
        if tail_snapshot:
            self._extract_enqueue_and_flush(
                tail_snapshot,
                source=f"shutdown:{tail_turn}",
                session_id=tail_session,
                turn_seq=tail_seq,
            )
        for worker in self._live_workers():
            worker.join(timeout=max(0.0, wait_timeout))
        return self.queue.flush()

    def wait_for_idle(self, timeout: float = 3.0) -> None:
        for worker in self._live_workers():
            worker.join(timeout=timeout)

    def _start_extraction(
        self,
        messages: list[dict[str, Any]],
        *,
        source: str,
        session_id: str = "",
        turn_seq: int | None = None,
    ) -> None:
        worker = threading.Thread(
            target=self._extract_enqueue_and_flush,
            args=(messages, source, session_id, turn_seq),
            name="memory-auto-extractor",
            daemon=True,
        )
        with self._lock:
            self._workers = self._live_workers_locked()
            self._workers.append(worker)
        worker.start()

    def _extract_enqueue_and_flush(
        self,
        messages: list[dict[str, Any]],
        source: str,
        session_id: str = "",
        turn_seq: int | None = None,
    ) -> None:
        with self._summary_lock:
            try:
                extracted = self._extract_memories(messages)
                resolved_session = str(session_id or self.session_id or "").strip()
                if resolved_session and turn_seq is not None:
                    with self._lock:
                        if self._last_seen_seq > 0 and int(turn_seq) > self._last_seen_seq:
                            return
                for item in extracted:
                    self.queue.enqueue(
                        item["memory"],
                        character_name=item.get("character_name") or self.primary_character_name,
                        source=source,
                        confidence=float(item.get("confidence", 1.0)),
                        slot_key=str(item.get("slot_key") or ""),
                        kind=str(item.get("kind") or "episodic"),
                        source_session_id=resolved_session,
                        source_turn_seq=turn_seq,
                    )
                self.queue.flush()
            except Exception:
                logger.exception("automatic memory extraction failed")

    def _shutdown_tail_snapshot(self) -> tuple[list[dict[str, Any]], int, int | None, str]:
        with self._lock:
            if not self._buffer or self._user_turns <= self._last_extract_turn:
                return [], self._user_turns, None, self.session_id
            self._last_extract_turn = self._user_turns
            snapshot = list(self._buffer)
            seqs = [int(item["turn_seq"]) for item in snapshot if item.get("turn_seq") is not None]
            tail_seq = max(seqs) if seqs else (self._last_seen_seq if self._last_seen_seq > 0 else None)
            return snapshot, self._user_turns, tail_seq, self.session_id

    def _extract_memories(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        dialogue = "\n".join(
            _clean_text(item.get("content"), max_chars=20000)
            for item in messages
            if _clean_text(item.get("content"), max_chars=20000)
        )
        if not dialogue:
            return []
        extracted, _duplicates, _chunk_count = self._extractor.extract_dialogue(
            dialogue,
            default_character_name=self.primary_character_name,
            max_chunk_tokens=self.extraction_chunk_tokens,
        )
        return extracted

    def _latest_user_text_for_fresh_turn(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            role = message.get("role")
            if role == "system":
                continue
            if role == "user":
                if is_compact_summary_message(message) or message.get("source") == "perception":
                    return ""
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
    session_id: str = "",
    queue: MemoryWriteQueue | None = None,
) -> MemoryAutoHooks | None:
    if dispatcher is None or not _env_enabled("SHINSEKAI_MEMORY_AUTO_ENABLED", True):
        return None
    hooks = MemoryAutoHooks(
        llm_adapter=llm_adapter,
        character_names=character_names,
        session_id=session_id,
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
