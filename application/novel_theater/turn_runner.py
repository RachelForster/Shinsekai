"""Single-flight asynchronous beat runner and speculative prefetch bridge for Novel Theater."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
import copy
import logging
import threading
from typing import Any

from ai.llm.speculative_dialog import SpeculativeDialogResult
from ai.llm.template.session.novel_theater import render_novel_chunk_feed_prompt
from application.novel_theater.prepare_launch import resolve_chapter_index_for_chunk
from application.novel_theater.turn_delivery import (
    abort_pending_turn,
    build_beat_messages,
    build_committed_beat_state,
    deliver_dialogs_to_stage,
    execute_direct_beat_generation,
    handle_beat_failure,
    reset_llm_history_to_system_prompt,
    resolve_casting_policy,
    run_background_compaction,
    snapshot_messages_with_chunk,
    sync_llm_history,
    toggle_busy_bar,
    update_llm_system_prompt,
)
from application.novel_theater.casting import casting_map_from_novel_state
from application.session_behavior.prefetch import SpeculativePrefetchCoordinator
from core.chat_history.behavior_state_models import BehaviorCommitResult
from core.document import ChapterEntry, DocumentChunk

logger = logging.getLogger(__name__)


class NovelTheaterTurnRunner:
    """Manage single-flight beat execution, history sync, dialog delivery, and prefetch."""

    def __init__(
        self,
        *,
        chunks: Sequence[DocumentChunk],
        chapters: Sequence[ChapterEntry],
        toc_entries: Sequence[Mapping[str, Any]],
        prefetch: SpeculativePrefetchCoordinator,
        create_adapter: Callable[[], Any],
        llm_manager: Any | None,
        dialog_queue: Any | None,
        presentation_queue: Any | None = None,
        ui_updates: Any | None = None,
        chat_turn_service: Any | None = None,
        history_path: str = "",
        media_selection_mode: str = "indexed",
        locale_provider: Callable[[], str] | None = None,
        opencc_provider: Callable[[], Any | None] | None = None,
        commit_async: Callable[
            [str, int, dict[str, Any], tuple[dict[str, Any], ...]],
            BehaviorCommitResult | None,
        ]
        | None = None,
    ) -> None:
        self._chunks = tuple(chunks)
        self._chapters = tuple(chapters)
        self._toc_entries = tuple(dict(item) for item in toc_entries)
        self._prefetch = prefetch
        self._create_adapter = create_adapter
        self._llm_manager = llm_manager
        self._dialog_queue = dialog_queue
        self._presentation_queue = presentation_queue
        self._ui_updates = ui_updates
        self._chat_turn_service = chat_turn_service
        self._history_path = str(history_path or "")
        self._media_selection_mode = (
            "semantic"
            if str(media_selection_mode or "").strip().lower() == "semantic"
            else "indexed"
        )
        self._locale_provider = locale_provider or (lambda: "zh_CN")
        self._opencc_provider = opencc_provider or (lambda: None)
        self._commit_async = commit_async

        self._lock = threading.RLock()
        self._history_lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="novel-theater-beat",
        )
        self._generation = 0
        self._active_cancel: threading.Event | None = None
        self._pending_sync: dict[tuple[str, int], dict[str, Any]] = {}
        self._pending_async: dict[tuple[str, int], dict[str, Any]] = {}
        self._pending_prompt_updates: dict[tuple[str, int], str] = {}
        self._closed = False

    def _locale(self) -> str:
        try:
            return str(self._locale_provider() or "zh_CN")
        except Exception:
            return "zh_CN"

    def build_chunk_prompt(self, chunk_index: int) -> str:
        chunk = self._chunks[chunk_index]
        chap_idx, chap_title = resolve_chapter_index_for_chunk(chunk_index, self._toc_entries)
        return render_novel_chunk_feed_prompt(
            chapter_num=chap_idx + 1,
            total_chapters=max(1, len(self._chapters) or len(self._toc_entries) or 1),
            chapter_title=chap_title,
            chunk_num=chunk_index + 1,
            total_chunks=max(1, len(self._chunks)),
            source_text=chunk.text,
            lookahead_text=chunk.lookahead,
            locale=self._locale(),
        )

    def try_consume_prefetched(
        self, *, branch_id: str, chunk_index: int, state_version: int, wait_timeout: float = 0.0,
    ) -> tuple[SpeculativeDialogResult, str, tuple[dict[str, Any], dict[str, Any]], str] | None:
        """Consume a cached or in-flight prefetch matching ``(branch_id, chunk_id, state_version)``."""
        if not (0 <= chunk_index < len(self._chunks)):
            return None
        chunk = self._chunks[chunk_index]
        res = self._prefetch.consume_if_valid(
            chunk.chunk_id, branch_id=branch_id,
            state_version=state_version, wait_timeout=wait_timeout,
        )
        if res is None or res.cancelled or res.error or not res.dialogs:
            return None
        prompt = self.build_chunk_prompt(chunk_index)
        turn_id, messages = build_beat_messages(prompt, res.raw_text)
        return res, prompt, messages, turn_id

    def queue_committed_sync_beat(
        self, *, branch_id: str, target_state_version: int, chunk_index: int,
        state_after_commit: dict[str, Any], messages_committed: tuple[dict[str, Any], dict[str, Any]],
        dialogs: tuple[dict[str, Any], ...], history_turn_id: str,
    ) -> None:
        with self._lock:
            self._pending_sync[(branch_id, target_state_version)] = {
                "chunk_index": chunk_index, "state": copy.deepcopy(state_after_commit),
                "messages": copy.deepcopy(messages_committed), "dialogs": copy.deepcopy(dialogs),
                "history_turn_id": history_turn_id, "generation": self._generation,
            }

    def queue_system_prompt_update(
        self, *, branch_id: str, target_state_version: int, system_prompt: str
    ) -> None:
        if not str(system_prompt or "").strip():
            return
        with self._lock:
            self._pending_prompt_updates[(branch_id, target_state_version)] = str(system_prompt)

    def queue_async_beat(
        self, *, branch_id: str, expected_committed_version: int, prefetch_lookup_version: int,
        chunk_index: int, state_after_commit: dict[str, Any], use_prefetch: bool = True,
        interrupt_playback: bool = False, reset_history: bool = False,
    ) -> None:
        with self._lock:
            self._pending_async[(branch_id, expected_committed_version)] = {
                "branch_id": branch_id, "expected_version": expected_committed_version,
                "prefetch_version": prefetch_lookup_version, "chunk_index": chunk_index,
                "state": copy.deepcopy(state_after_commit), "use_prefetch": use_prefetch,
                "interrupt_playback": bool(interrupt_playback),
                "reset_history": bool(reset_history), "generation": self._generation,
            }

    def on_transition_committed(
        self, *, branch_id: str, state_version: int, appended_turn_seqs: tuple[int, ...] = ()
    ) -> None:
        """Finalize side-effects strictly after SQLite OCC commit and replace emit."""
        with self._lock:
            if self._closed:
                return
            prompt_update = self._pending_prompt_updates.pop((branch_id, state_version), None)
            sync_job = self._pending_sync.pop((branch_id, state_version), None)
            async_job = self._pending_async.pop((branch_id, state_version), None)
        if prompt_update:
            update_llm_system_prompt(
                self._llm_manager, prompt_update,
                history_path=self._history_path, history_lock=self._history_lock,
            )
        if sync_job is not None:
            self._append_and_deliver_beat(
                branch_id=branch_id, committed_version=state_version,
                next_chunk_index=int(sync_job["chunk_index"]) + 1,
                state_snapshot=sync_job["state"], messages_committed=sync_job["messages"],
                dialogs=sync_job["dialogs"], history_turn_id=sync_job["history_turn_id"],
                appended_turn_seqs=appended_turn_seqs, generation=int(sync_job["generation"]),
                run_compact_inline=False,
            )
        if async_job is not None:
            if async_job.get("interrupt_playback") and self._chat_turn_service is not None:
                self._chat_turn_service.interrupt()
            if async_job.get("reset_history"):
                reset_llm_history_to_system_prompt(
                    self._llm_manager, history_path=self._history_path,
                    ui_updates=self._ui_updates, history_lock=self._history_lock,
                )
            self._submit_async_beat(async_job)

    def _submit_async_beat(self, job: dict[str, Any]) -> None:
        with self._lock:
            if self._closed or int(job["generation"]) != self._generation:
                return
            cancel_event = threading.Event()
            if self._active_cancel is not None:
                self._active_cancel.set()
            self._active_cancel = cancel_event
            gen = self._generation
        try:
            self._executor.submit(self._run_async_beat, job, cancel_event, gen)
        except RuntimeError:
            pass

    def _append_and_deliver_beat(
        self,
        *,
        branch_id: str,
        committed_version: int,
        next_chunk_index: int,
        state_snapshot: dict[str, Any],
        messages_committed: tuple[dict[str, Any], dict[str, Any]],
        dialogs: Sequence[Mapping[str, Any]],
        history_turn_id: str,
        appended_turn_seqs: tuple[int, ...],
        generation: int,
        existing_turn: Any | None = None,
        run_compact_inline: bool = True,
    ) -> None:
        if self._closed or generation != self._generation:
            abort_pending_turn(existing_turn, self._chat_turn_service)
            return
        sync_llm_history(
            self._llm_manager,
            appended_turn_seqs=appended_turn_seqs,
            messages_committed=messages_committed,
            history_path=self._history_path,
            history_lock=self._history_lock,
            compact_now=run_compact_inline,
            should_abort=lambda: self._closed or generation != self._generation,
        )
        if self._closed or generation != self._generation:
            abort_pending_turn(existing_turn, self._chat_turn_service)
            return
        deliver_dialogs_to_stage(
            dialogs,
            dialog_queue=self._dialog_queue,
            presentation_queue=self._presentation_queue,
            ui_updates=self._ui_updates,
            chat_turn_service=self._chat_turn_service,
            history_path=self._history_path,
            casting_map=casting_map_from_novel_state(state_snapshot),
            opencc=self._opencc_provider(),
            history_turn_id=history_turn_id,
            existing_turn=existing_turn,
        )
        if not run_compact_inline:
            try:
                self._executor.submit(
                    self._compact_and_prefetch, branch_id, next_chunk_index,
                    committed_version, copy.deepcopy(state_snapshot), generation,
                )
            except RuntimeError:
                pass
        else:
            self.ensure_prefetched(
                branch_id=branch_id, chunk_index=next_chunk_index,
                state_version=committed_version, state_snapshot=state_snapshot,
            )

    def _compact_and_prefetch(
        self, branch_id: str, next_chunk_index: int,
        committed_version: int, state_snapshot: dict[str, Any], generation: int,
    ) -> None:
        if self._closed or generation != self._generation:
            return
        run_background_compaction(self._llm_manager, history_lock=self._history_lock)
        self.ensure_prefetched(
            branch_id=branch_id, chunk_index=next_chunk_index,
            state_version=committed_version, state_snapshot=state_snapshot,
        )

    def ensure_prefetched(
        self,
        *,
        branch_id: str,
        chunk_index: int,
        state_version: int,
        state_snapshot: Mapping[str, Any],
    ) -> None:
        """Schedule single-slot background prefetch for ``chunk_index`` when available."""
        with self._lock:
            if self._closed or not (0 <= chunk_index < len(self._chunks)):
                return
        if str(state_snapshot.get("phase") or "") in {"generating", "ended"}:
            return
        chunk = self._chunks[chunk_index]
        messages = snapshot_messages_with_chunk(
            self._llm_manager,
            self.build_chunk_prompt(chunk_index),
            history_lock=self._history_lock,
        )
        gen_cfg = dict(getattr(self._llm_manager, "generation_config", None) or {})
        requires_media, bound_speakers = resolve_casting_policy(
            state_snapshot, self._opencc_provider
        )
        try:
            self._prefetch.schedule(
                cache_key=chunk.chunk_id,
                branch_id=branch_id,
                state_version=state_version,
                messages=messages,
                generation_kwargs=gen_cfg,
                media_selection_mode=self._media_selection_mode,
                speaker_requires_media=requires_media,
                bound_speakers=bound_speakers,
            )
        except RuntimeError:
            pass

    def _generate_beat(
        self,
        *,
        branch_id: str,
        prefetch_ver: int,
        chunk_index: int,
        state_snapshot: Mapping[str, Any],
        use_prefetch: bool,
        cancel_event: threading.Event,
        generation: int,
    ) -> tuple[SpeculativeDialogResult | None, tuple[dict[str, Any], dict[str, Any]] | None, str]:
        if use_prefetch:
            hit = self.try_consume_prefetched(
                branch_id=branch_id,
                chunk_index=chunk_index,
                state_version=prefetch_ver,
                wait_timeout=120.0,
            )
            if hit is not None:
                res, _prompt, messages_to_commit, turn_id = hit
                return res, messages_to_commit, turn_id
        if cancel_event.is_set() or generation != self._generation:
            return None, None, ""
        prompt = self.build_chunk_prompt(chunk_index)
        payload_messages = snapshot_messages_with_chunk(
            self._llm_manager,
            prompt,
            history_lock=self._history_lock,
        )
        return execute_direct_beat_generation(
            prompt=prompt,
            payload_messages=payload_messages,
            state_snapshot=state_snapshot,
            llm_manager=self._llm_manager,
            create_adapter=self._create_adapter,
            opencc_provider=self._opencc_provider,
            cancel_event=cancel_event,
            media_selection_mode=self._media_selection_mode,
            locale_provider=self._locale,
        )

    def _run_async_beat(
        self,
        job: dict[str, Any],
        cancel_event: threading.Event,
        generation: int,
    ) -> None:
        branch_id = str(job["branch_id"])
        expected_ver = int(job["expected_version"])
        prefetch_ver = int(job["prefetch_version"])
        chunk_index = int(job["chunk_index"])
        state_snapshot = dict(job["state"])
        if self._closed or cancel_event.is_set() or generation != self._generation:
            return
        if not (0 <= chunk_index < len(self._chunks)):
            return

        turn_service = self._chat_turn_service
        turn = turn_service.begin_turn() if turn_service is not None else None
        toggle_busy_bar(self._ui_updates, visible=True, locale=self._locale())
        result: SpeculativeDialogResult | None = None
        messages_to_commit: tuple[dict[str, Any], dict[str, Any]] | None = None
        history_turn_id = ""
        error_msg = ""
        try:
            result, messages_to_commit, history_turn_id = self._generate_beat(
                branch_id=branch_id,
                prefetch_ver=prefetch_ver,
                chunk_index=chunk_index,
                state_snapshot=state_snapshot,
                use_prefetch=bool(job.get("use_prefetch", True)),
                cancel_event=cancel_event,
                generation=generation,
            )
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception("Novel Theater async beat failed")
        finally:
            toggle_busy_bar(self._ui_updates, visible=False)

        cancelled = (
            self._closed
            or cancel_event.is_set()
            or generation != self._generation
            or (turn is not None and turn.is_cancelled())
            or (result is not None and result.cancelled)
        )
        if cancelled:
            abort_pending_turn(turn, turn_service)
            return

        if error_msg or result is None or result.error or not result.dialogs or messages_to_commit is None:
            reason = error_msg or (result.error if result is not None else "empty_result")
            handle_beat_failure(
                branch_id=branch_id,
                expected_version=expected_ver,
                state_snapshot=state_snapshot,
                reason=str(reason or ""),
                commit_async=self._commit_async,
                ui_updates=self._ui_updates,
                presentation_queue=self._presentation_queue,
                turn=turn,
                chat_turn_service=turn_service,
                locale=self._locale(),
            )
            return

        next_chunk_index, next_state = build_committed_beat_state(
            state_snapshot, chunk_index=chunk_index,
            total_chunks=len(self._chunks), toc_entries=self._toc_entries,
        )
        commit_res = self._commit_async(branch_id, expected_ver, next_state, messages_to_commit) if callable(self._commit_async) else None
        if commit_res is None:
            abort_pending_turn(turn, turn_service)
            return
        self._append_and_deliver_beat(
            branch_id=branch_id, committed_version=commit_res.snapshot.state_version,
            next_chunk_index=next_chunk_index, state_snapshot=commit_res.snapshot.state,
            messages_committed=messages_to_commit, dialogs=result.dialogs,
            history_turn_id=history_turn_id, appended_turn_seqs=commit_res.appended_turn_seqs,
            generation=generation, existing_turn=turn, run_compact_inline=True,
        )

    def cancel_active(self, *, interrupt_playback: bool = False) -> None:
        """Invalidate any in-flight or queued beats safely."""
        with self._lock:
            self._generation += 1
            if self._active_cancel is not None:
                self._active_cancel.set()
            self._active_cancel = None
            self._pending_sync.clear()
            self._pending_async.clear()
            self._pending_prompt_updates.clear()
        if interrupt_playback and self._chat_turn_service is not None:
            try:
                self._chat_turn_service.interrupt()
            except Exception:
                logger.debug("chat_turn_service interrupt failed", exc_info=True)

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.cancel_active()
        self._prefetch.shutdown()
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["NovelTheaterTurnRunner"]
