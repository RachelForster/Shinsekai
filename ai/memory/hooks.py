"""Built-in chat hooks for automatic long-term memory recall and extraction."""

from __future__ import annotations

from collections import deque
from datetime import datetime
import inspect
import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from ai.llm.template.integrations.localization import LocaleInput, resolve_dynamic_locale
from ai.llm.template.session import (
    ALL_MEMORY_CONTEXT_MARKERS,
    MEMORY_CONTEXT_MARKER,
    MEMORY_CONTEXT_SPEC,
    MemoryContextPromptContext,
    contains_any_context_marker,
)
from ai.memory.chunking import DEFAULT_DIALOGUE_CHUNK_TOKENS
from ai.memory.extraction import MemoryExtractor
from ai.memory.operations import (
    memory_recall_turn,
    memory_search,
    memory_service_status,
)
from ai.memory.queue import MemoryWriteQueue
from ai.memory.rule_recall_planner import RuleRecallPlanner
from core.chat_history.models import is_compact_summary_message
from core.chat_history.text import (
    history_payload_to_plain_text,
    parse_assistant_dialog_content,
    strip_local_time_prefix,
)
from sdk.adapters.memory import ExtractionWindow, MemoryDraft, TurnRecallInput
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
DEFAULT_INJECTION_COOLDOWN_TURNS = 3
DEFAULT_INIT_POLL_INTERVAL_SECONDS = 0.45
DEFAULT_INIT_TIMEOUT_SECONDS = 600.0
MEMORY_BEFORE_CHAT_PRIORITY = 150
_INJECTION_MARKER = MEMORY_CONTEXT_MARKER
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


def _memory_rows(
    result: dict[str, Any],
    *,
    excluded_ids: frozenset[str] = frozenset(),
) -> tuple[list[str], frozenset[str]]:
    rows = result.get("memories") or result.get("results") or []
    if not isinstance(rows, list):
        return [], frozenset()
    memories: list[str] = []
    injected_ids: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            rid = _clean_text(row.get("id"), max_chars=128)
            if rid and rid in excluded_ids:
                continue
            text = _clean_text(
                row.get("rendered") or row.get("memory") or row.get("content") or row.get("text"),
                max_chars=600,
            )
            if text:
                memories.append(text)
                if rid:
                    injected_ids.append(rid)
        else:
            text = _clean_text(row, max_chars=600)
            if text:
                memories.append(text)
    return memories, frozenset(injected_ids)


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
    """Owns automatic hybrid recall injection, 3-turn dedup cooldown, and periodic extraction."""

    def __init__(
        self,
        *,
        llm_adapter: Any,
        character_names: list[str] | None = None,
        session_id: str = "",
        memory_mode: str = "",
        player_character: str = "",
        queue: MemoryWriteQueue | None = None,
        search_func=memory_search,
        recall_func=None,
        extract_interval_turns: int = DEFAULT_EXTRACT_INTERVAL_TURNS,
        search_limit: int = DEFAULT_SEARCH_LIMIT,
        recent_buffer_messages: int = DEFAULT_RECENT_BUFFER_MESSAGES,
        extraction_chunk_tokens: int = DEFAULT_DIALOGUE_CHUNK_TOKENS,
        cooldown_turns: int = DEFAULT_INJECTION_COOLDOWN_TURNS,
        memory_status_func=memory_service_status,
        init_poll_interval_seconds: float = DEFAULT_INIT_POLL_INTERVAL_SECONDS,
        init_timeout_seconds: float = DEFAULT_INIT_TIMEOUT_SECONDS,
        sleep_func=time.sleep,
        monotonic_func=time.monotonic,
        clock_func=time.time,
        last_turn_at: Callable[[], float] | None = None,
        memory_mode_start_seq: int | None = None,
        locale: LocaleInput = None,
    ) -> None:
        self.llm_adapter = llm_adapter
        self.character_names = [
            name.strip() for name in (character_names or []) if str(name or "").strip()
        ]
        self._active_character_name = self.character_names[0] if self.character_names else "user"
        self.session_id = str(session_id or "").strip()
        self.memory_mode = str(memory_mode or "").strip()
        self.player_character = str(player_character or "").strip()
        self.queue = queue if queue is not None else MemoryWriteQueue()
        self.search_func = search_func
        self._uses_custom_search = (search_func is not memory_search) and (recall_func is None)
        self.recall_func = recall_func if recall_func is not None else memory_recall_turn
        self.extract_interval_turns = max(1, int(extract_interval_turns))
        self.search_limit = max(1, int(search_limit))
        self.recent_buffer_messages = max(2, int(recent_buffer_messages))
        self.extraction_chunk_tokens = max(256, int(extraction_chunk_tokens))
        self.cooldown_turns = max(1, int(cooldown_turns))
        self.memory_status_func = memory_status_func
        self.init_poll_interval_seconds = max(0.01, float(init_poll_interval_seconds))
        self.init_timeout_seconds = max(0.01, float(init_timeout_seconds))
        self._sleep = sleep_func
        self._monotonic = monotonic_func
        self._clock = clock_func
        self._lock = threading.RLock()
        self._summary_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._rollback_epoch = 0
        self._buffer: list[dict[str, Any]] = []
        self._user_turns = 0
        self._last_extract_turn = 0
        self._last_extracted_seq = 0
        self._memory_mode_start_seq = memory_mode_start_seq
        self._last_seen_seq = 0
        self._last_injected_user = ""
        self._read_last_turn_at = last_turn_at
        self._last_turn_ts = last_turn_at() if last_turn_at is not None else 0.0
        self._recent_injected_window: deque[frozenset[str]] = deque(
            maxlen=self.cooldown_turns
        )
        self._workers: list[threading.Thread] = []
        self.locale = locale
        self._extractor = MemoryExtractor(llm_adapter, locale=locale)
        self._planner = RuleRecallPlanner(default_limit=self.search_limit)

    @property
    def primary_character_name(self) -> str:
        with self._lock:
            return self._active_character_name or (
                self.character_names[0] if self.character_names else "user"
            )

    def register(self, dispatcher: PluginHookDispatcher) -> None:
        dispatcher.register_init_chat(
            self.init_chat,
            label="memory",
            weight=3.0,
            critical=False,
        )
        # Priority > 100 ensures PerceptionAutoHooks (priority=100) attaches screen/game
        # observations BEFORE MemoryAutoHooks extracts recall clauses on proactive turns.
        dispatcher.register_before_chat(
            self.before_chat,
            label="memory_auto_before_chat",
            priority=MEMORY_BEFORE_CHAT_PRIORITY,
        )
        dispatcher.register_before_compact(
            self.before_compact,
            label="memory_auto_before_compact",
        )
        dispatcher.register_message_added(
            self.message_added,
            label="memory_auto_message_added",
        )

    def init_chat(self, context: InitChatContext) -> None:
        """Warm the bridge-owned memory service and forward its task progress."""
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
                    str(
                        task.get("message")
                        or result.get("message")
                        or "Loading long-term memory."
                    ),
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
        turn_meta = self._inspect_fresh_turn(context.messages)
        if turn_meta is None:
            return
        user_text, source, prev_assistant_text, in_window_seqs = turn_meta
        if not user_text:
            return
        if contains_any_context_marker(context.messages, ALL_MEMORY_CONTEXT_MARKERS):
            return

        now_ts = float(self._clock())
        with self._lock:
            seconds_since_last = (
                max(0.0, now_ts - self._last_turn_ts) if self._last_turn_ts > 0.0 else 0.0
            )
            cooldown_ids: frozenset[str] = (
                frozenset().union(*self._recent_injected_window)
                if self._recent_injected_window
                else frozenset()
            )
            active_char = self.primary_character_name
            ordered_scene = [
                name
                for name in dict.fromkeys([active_char, *self.character_names])
                if name and name.casefold() != "user"
            ]
            active_chars = tuple(ordered_scene)
            effective_session = self.session_id
            effective_mode = self.memory_mode

        turn_input = TurnRecallInput(
            user_text=user_text,
            previous_assistant_text=prev_assistant_text,
            active_character_names=active_chars,
            session_id=effective_session,
            memory_mode=effective_mode,
            source=source,
            now_ts=now_ts,
            seconds_since_last_turn=seconds_since_last,
            in_window_turn_seqs=in_window_seqs,
            recently_injected_ids=cooldown_ids,
        )
        plan = self._planner.plan(turn_input)
        if not plan.should_recall:
            if source != "perception":
                with self._lock:
                    self._last_turn_ts = now_ts
            return

        stripped_query = (
            strip_local_time_prefix(user_text)
            if source != "perception"
            else (" ".join(plan.query_clauses) if plan.query_clauses else "")
        )
        if not stripped_query and not plan.is_session_wakeup:
            return

        dedupe_key = f"{source}:{stripped_query.casefold()}"
        with self._lock:
            if self._last_injected_user == dedupe_key:
                return
            self._last_injected_user = dedupe_key
            if source != "perception":
                self._last_turn_ts = now_ts

        if self._uses_custom_search:
            search_query = stripped_query or (
                plan.query_clauses[0] if plan.query_clauses else user_text
            )
            try:
                result = self.search_func(
                    search_query,
                    character_name=active_char,
                    limit=self.search_limit,
                )
            except Exception:
                logger.exception("automatic memory search failed")
                return
            if (
                not isinstance(result, dict)
                or result.get("error")
                or result.get("status") == "loading"
            ):
                return
            memories, injected_ids = _memory_rows(result, excluded_ids=cooldown_ids)
            with self._lock:
                self._recent_injected_window.append(injected_ids)
            if not memories:
                return
            context.messages.append(
                {
                    "role": "system",
                    "content": self._format_memory_context(memories),
                }
            )
            return

        try:
            recall_kwargs: dict[str, Any] = {}
            if self.locale is not None:
                try:
                    params = inspect.signature(self.recall_func).parameters
                    if "locale" in params or any(
                        p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
                    ):
                        recall_kwargs["locale"] = resolve_dynamic_locale(self.locale)
                except (TypeError, ValueError):
                    pass
            recall_result = self.recall_func(turn_input, **recall_kwargs)
        except Exception:
            logger.exception("automatic memory turn recall failed")
            return
        if (
            not isinstance(recall_result, dict)
            or recall_result.get("error")
            or recall_result.get("status") == "loading"
        ):
            return

        rendered = str(recall_result.get("rendered") or "").strip()
        raw_recalled = recall_result.get("recalled_ids") or ()
        recalled_ids = frozenset(str(x).strip() for x in raw_recalled if str(x).strip())
        with self._lock:
            self._recent_injected_window.append(recalled_ids)

        if not rendered:
            return
        context.messages.append(
            {
                "role": "system",
                "content": rendered,
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
        now_ts = float(self._clock())
        with self._lock:
            if effective_session and not self.session_id:
                self.session_id = effective_session
            if turn_seq is not None:
                if self._memory_mode_start_seq is not None and int(turn_seq) <= self._memory_mode_start_seq:
                    return
                self._last_seen_seq = max(self._last_seen_seq, int(turn_seq))
            if role == "user":
                self._user_turns += 1
                self._last_injected_user = ""
                if self._last_turn_ts <= 0.0:
                    self._last_turn_ts = now_ts
            elif role == "assistant":
                self._last_turn_ts = now_ts
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
                epoch = self._rollback_epoch
                seqs = [
                    int(item["turn_seq"])
                    for item in snapshot
                    if item.get("turn_seq") is not None
                ]
                extract_seq = (
                    max(seqs) if seqs else (int(turn_seq) if turn_seq is not None else None)
                )
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
                epoch=epoch,
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
                msg_seq = message.get("_turn_seq")
                if self._memory_mode_start_seq is not None and (
                    msg_seq is None or int(msg_seq) <= self._memory_mode_start_seq
                ):
                    continue
                if msg_seq is None:
                    msg_seq = anchor_seq
                snapshot.append(
                    {
                        "role": role,
                        "content": content,
                        "turn_seq": None if msg_seq is None else int(msg_seq),
                    }
                )

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
            epoch = self._rollback_epoch

        self._extract_enqueue_and_flush(
            snapshot,
            source=f"before_compact:{anchor_seq if anchor_seq is not None else self._user_turns}",
            session_id=effective_session,
            turn_seq=anchor_seq,
            epoch=epoch,
        )

    def set_memory_mode(self, mode: str, *, up_to_seq: int = 0) -> None:
        with self._write_lock, self._lock:
            if mode == self.memory_mode:
                return
            self._memory_mode = mode
            # Older dialogue belongs to the previous memory scope.
            self._memory_mode_start_seq = max(up_to_seq, self._last_seen_seq, self._memory_mode_start_seq or 0)
            self._buffer.clear()
            self._last_extract_turn = self._user_turns
            self._last_injected_user = ""
            self._recent_injected_window.clear()
            self._rollback_epoch += 1

    def rollback_after_turn(
        self, session_id: str, turn_seq: int, *, protected_turn_seqs: Sequence[int] = (),
    ) -> int:
        """Synchronize buffered hook state and pending write queue on session revert/reroll."""
        sid = str(session_id or "").strip()
        cutoff = max(0, int(turn_seq))
        with self._write_lock:
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
                    self._recent_injected_window.clear()
                    if self._read_last_turn_at is not None:
                        self._last_turn_ts = self._read_last_turn_at()
                    self._rollback_epoch += 1
            return self.queue.rollback_after_turn(
                sid, cutoff, protected_turn_seqs=protected_turn_seqs
            )

    def shutdown(self, *, wait_timeout: float = 3.0) -> dict[str, Any]:
        tail_snapshot, tail_turn, tail_seq, tail_session, epoch = self._shutdown_tail_snapshot()
        if tail_snapshot:
            self._extract_enqueue_and_flush(
                tail_snapshot,
                source=f"shutdown:{tail_turn}",
                session_id=tail_session,
                turn_seq=tail_seq,
                epoch=epoch,
            )
        for worker in self._live_workers():
            worker.join(timeout=max(0.0, wait_timeout))
        with self._write_lock:
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
        epoch: int,
    ) -> None:
        worker = threading.Thread(
            target=self._extract_enqueue_and_flush,
            args=(messages, source, session_id, turn_seq, epoch),
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
        session_id: str,
        turn_seq: int | None,
        epoch: int,
    ) -> None:
        with self._summary_lock:
            try:
                resolved_session = str(session_id or self.session_id or "").strip()
                drafts = self._extract_drafts(
                    messages,
                    session_id=resolved_session,
                    turn_seq=turn_seq,
                )
                with self._write_lock:
                    with self._lock:
                        if epoch != self._rollback_epoch:
                            return
                    for draft in drafts:
                        char_target = (
                            "user"
                            if draft.owner_id in {"__self__", "user", ""}
                            else draft.owner_id
                        )
                        self.queue.enqueue(
                            draft.detail_text,
                            character_name=char_target,
                            source=source,
                            confidence=float(draft.importance),
                            gist_text=draft.gist_text,
                            slot_key=draft.slot_key,
                            kind=draft.kind,
                            topic_tags=draft.topic_tags,
                            entities=draft.entities,
                            importance=draft.importance,
                            event_at=draft.event_at,
                            memory_mode=self.memory_mode,
                            player_character=self.player_character,
                            source_session_id=resolved_session,
                            source_turn_seq=turn_seq,
                        )
                    self.queue.flush()
            except Exception:
                logger.exception("automatic memory extraction failed")

    def _shutdown_tail_snapshot(self) -> tuple[list[dict[str, Any]], int, int | None, str, int]:
        with self._lock:
            if not self._buffer or self._user_turns <= self._last_extract_turn:
                return [], self._user_turns, None, self.session_id, self._rollback_epoch
            self._last_extract_turn = self._user_turns
            snapshot = list(self._buffer)
            seqs = [
                int(item["turn_seq"])
                for item in snapshot
                if item.get("turn_seq") is not None
            ]
            tail_seq = (
                max(seqs) if seqs else (self._last_seen_seq if self._last_seen_seq > 0 else None)
            )
            return snapshot, self._user_turns, tail_seq, self.session_id, self._rollback_epoch

    def _extract_drafts(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str = "",
        turn_seq: int | None = None,
    ) -> list[MemoryDraft]:
        with self._lock:
            scene_chars = (
                tuple(self.character_names)
                if self.character_names
                else (self.primary_character_name,)
            )
        now_iso = datetime.fromtimestamp(float(self._clock())).astimezone().isoformat(
            timespec="seconds"
        )
        window = ExtractionWindow(
            messages=tuple(messages),
            character_names=scene_chars,
            now_iso=now_iso,
            session_id=session_id,
            turn_seq=turn_seq,
        )
        return list(
            self._extractor.extract(
                window,
                max_chunk_tokens=self.extraction_chunk_tokens,
            )
        )

    def _inspect_fresh_turn(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[str, str, str, frozenset[int]] | None:
        """Locate fresh user/perception turn, preceding assistant utterance, and window seqs."""
        target_idx = -1
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            role = msg.get("role")
            if role == "system":
                continue
            if role == "user":
                if is_compact_summary_message(msg):
                    return None
                target_idx = idx
                break
            return None

        if target_idx < 0:
            return None

        target_msg = messages[target_idx]
        source = str(target_msg.get("source") or "user").strip() or "user"
        raw_content = target_msg.get("content")
        if isinstance(raw_content, list):
            parts = [
                str(part.get("text") or "")
                for part in raw_content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            user_text = _clean_text("\n".join(p for p in parts if p), max_chars=3000)
        else:
            user_text = _clean_text(raw_content, max_chars=3000)

        prev_assistant = ""
        for idx in range(target_idx - 1, -1, -1):
            msg = messages[idx]
            if msg.get("role") == "assistant" and not msg.get("tool_calls"):
                prev_assistant = _clean_text(
                    history_payload_to_plain_text([msg], user_display_name="user"),
                    max_chars=400,
                )
                break

        window_seqs: set[int] = set()
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            raw_seq = msg.get("_turn_seq")
            if raw_seq is not None:
                try:
                    window_seqs.add(int(raw_seq))
                except (TypeError, ValueError):
                    pass

        return (user_text, source, prev_assistant, frozenset(window_seqs))

    def _format_memory_context(self, memories: list[str]) -> str:
        active_locale = resolve_dynamic_locale(self.locale)
        return MEMORY_CONTEXT_SPEC.render_system(
            MemoryContextPromptContext(
                items=tuple(memories[: self.search_limit]),
                tiered=False,
                locale=active_locale,
            )
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
    memory_mode: str = "",
    player_character: str = "",
    queue: MemoryWriteQueue | None = None,
    last_turn_at: Callable[[], float] | None = None,
    memory_mode_start_seq: int | None = None,
    locale: LocaleInput = None,
) -> MemoryAutoHooks | None:
    if dispatcher is None or not _env_enabled("SHINSEKAI_MEMORY_AUTO_ENABLED", True):
        return None
    hooks = MemoryAutoHooks(
        llm_adapter=llm_adapter,
        character_names=character_names,
        session_id=session_id,
        memory_mode=memory_mode,
        player_character=player_character,
        queue=queue,
        last_turn_at=last_turn_at,
        memory_mode_start_seq=memory_mode_start_seq,
        locale=locale,
        extract_interval_turns=_env_int(
            "SHINSEKAI_MEMORY_EXTRACT_INTERVAL_TURNS",
            DEFAULT_EXTRACT_INTERVAL_TURNS,
        ),
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
