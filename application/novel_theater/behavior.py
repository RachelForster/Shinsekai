"""Novel Theater SessionBehavior implementation driving serialized chunk playback."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ai.llm.template.session.novel_theater import render_novel_compact_instruction
from application.novel_theater.casting import (
    NOVEL_NAME_MODE_STORY,
    casting_map_from_novel_state,
    count_cast_targets,
    effective_cast_display_name,
    normalize_novel_name_mode,
)
from application.novel_theater.prepare_launch import (
    NOVEL_THEATER_BEHAVIOR_ID,
    resolve_chapter_index_for_chunk,
)
from application.novel_theater.turn_runner import NovelTheaterTurnRunner
from application.session_behavior.casting import CastingMap
from application.session_behavior.protocol import (
    BehaviorCommand,
    BehaviorStateEnvelope,
    BehaviorTransition,
    CommandResolution,
    InteractionPolicy,
    SessionBehavior,
)
from core.chat_history.behavior_state_models import BehaviorStateSnapshot
from core.document import ChapterEntry, DocumentChunk, DocumentManifest
from sdk.hooks import BeforeCompactContext

_MAX_INLINE_HUD_CHAPTERS = 500


class NovelTheaterBehavior(SessionBehavior):
    """Streamed visual-novel director driving faithful chunk-by-chunk adaptation."""

    def __init__(
        self,
        *,
        manifest: DocumentManifest,
        chapters: Sequence[ChapterEntry],
        chunks: Sequence[DocumentChunk],
        toc_entries: Sequence[Mapping[str, Any]],
        turn_runner: NovelTheaterTurnRunner,
        locale_provider: Callable[[], str] | None = None,
        rebuild_system_prompt: Callable[[Sequence[Mapping[str, Any]], Sequence[str]], str]
        | None = None,
    ) -> None:
        self._manifest = manifest
        self._chapters = tuple(chapters)
        self._chunks = tuple(chunks)
        self._toc_entries = tuple(dict(item) for item in toc_entries)
        self._turn_runner = turn_runner
        self._locale_provider = locale_provider or (lambda: "zh_CN")
        self._rebuild_system_prompt = rebuild_system_prompt

    @property
    def behavior_id(self) -> str:
        return NOVEL_THEATER_BEHAVIOR_ID

    def build_reset_state(
        self, previous_state: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build fresh chunk-0 initial state preserving current cast after history clear."""
        prev = previous_state if isinstance(previous_state, Mapping) else {}
        chap_idx, _ = resolve_chapter_index_for_chunk(0, self._toc_entries)
        return {
            "docId": str(prev.get("docId") or self._manifest.doc_id),
            "title": str(prev.get("title") or self._manifest.title),
            "chunkIndex": 0,
            "chapterIndex": chap_idx,
            "totalChunks": len(self._chunks),
            "totalChapters": len(self._toc_entries),
            "phase": "ready",
            "casting": dict(prev.get("casting") or {"bindings": []}),
            "castEntries": list(prev.get("castEntries") or []),
            "chapters": list(prev.get("chapters") or self._toc_entries),
            "lastError": "",
        }

    def _chapters_for_hud(self, state: Mapping[str, Any]) -> list[dict[str, Any]]:
        raw = state.get("chapters")
        items = raw if isinstance(raw, list) and raw else self._toc_entries
        return [dict(item) for item in items[:_MAX_INLINE_HUD_CHAPTERS]]

    def describe_state(
        self, state: Mapping[str, Any], state_version: int
    ) -> BehaviorStateEnvelope:
        phase = str(state.get("phase") or "ready")
        chunk_index = max(0, int(state.get("chunkIndex", 0) or 0))
        total_chunks = max(1, int(state.get("totalChunks") or len(self._chunks) or 1))
        toc = state.get("chapters")
        toc_seq = toc if isinstance(toc, list) and toc else self._toc_entries
        probe_idx = min(chunk_index, total_chunks - 1)
        chap_idx, chap_title = resolve_chapter_index_for_chunk(probe_idx, toc_seq)
        total_chapters = int(state.get("totalChapters") or len(toc_seq) or 1)
        end_action = "idle" if phase in {"generating", "ended"} else "auto_advance"
        policy = InteractionPolicy(
            hide_input_layer=True,
            playback_end_action=end_action,
            allow_free_text_interject=False,
            allow_unbound_speakers=True,
        )
        hud = {
            "docId": str(state.get("docId") or self._manifest.doc_id),
            "title": str(state.get("title") or self._manifest.title),
            "chapterIndex": chap_idx,
            "chapterTitle": chap_title,
            "totalChapters": total_chapters,
            "chunkIndex": min(chunk_index, total_chunks),
            "totalChunks": total_chunks,
            "phase": phase,
            "chapters": self._chapters_for_hud(state),
            "chaptersTruncated": len(toc_seq) > _MAX_INLINE_HUD_CHAPTERS,
            "lastError": str(state.get("lastError") or ""),
        }
        return BehaviorStateEnvelope(
            behavior_id=self.behavior_id,
            state_version=state_version,
            stage_policy=policy,
            hud=hud,
            options=(),
            casting=dict(state.get("casting") or {}),
        )

    def handle_command(
        self,
        command: BehaviorCommand,
        *,
        state: Mapping[str, Any],
        state_version: int,
        branch_id: str,
    ) -> BehaviorTransition | CommandResolution:
        action = command.action
        phase = str(state.get("phase") or "ready")
        chunk_index = max(0, int(state.get("chunkIndex", 0) or 0))
        total_chunks = len(self._chunks)

        if action == "advance":
            if phase == "generating":
                return CommandResolution(
                    status="rejected",
                    error_code="behavior.busy",
                    error_message="Novel Theater beat is already generating.",
                )
            if chunk_index >= total_chunks:
                return BehaviorTransition(
                    next_state={**state, "phase": "ended", "lastError": ""},
                    invalidate_prefetch=False,
                )

            hit = self._turn_runner.try_consume_prefetched(
                branch_id=branch_id,
                chunk_index=chunk_index,
                state_version=state_version,
                wait_timeout=0.0,
            )
            if hit is not None:
                res, _prompt, messages_to_commit, history_turn_id = hit
                next_idx = chunk_index + 1
                ended = next_idx >= total_chunks
                probe_idx = max(0, total_chunks - 1) if ended else next_idx
                chap_idx, _ = resolve_chapter_index_for_chunk(probe_idx, self._toc_entries)
                next_state = {
                    **state,
                    "chunkIndex": next_idx,
                    "chapterIndex": chap_idx,
                    "phase": "ended" if ended else "playing",
                    "lastError": "",
                }
                self._turn_runner.queue_committed_sync_beat(
                    branch_id=branch_id,
                    target_state_version=state_version + 1,
                    chunk_index=chunk_index,
                    state_after_commit=next_state,
                    messages_committed=messages_to_commit,
                    dialogs=res.dialogs,
                    history_turn_id=history_turn_id,
                )
                return BehaviorTransition(
                    next_state=next_state,
                    messages_to_commit=messages_to_commit,
                    invalidate_prefetch=False,
                )

            generating_state = {
                **state,
                "phase": "generating",
                "lastError": "",
            }
            self._turn_runner.queue_async_beat(
                branch_id=branch_id,
                expected_committed_version=state_version + 1,
                prefetch_lookup_version=state_version,
                chunk_index=chunk_index,
                state_after_commit=generating_state,
                use_prefetch=True,
            )
            return BehaviorTransition(
                next_state=generating_state,
                messages_to_commit=(),
                invalidate_prefetch=False,
            )

        if action == "jump_chapter":
            raw_chap = command.payload.get("chapterIndex")
            if isinstance(raw_chap, bool) or not isinstance(raw_chap, int):
                return CommandResolution(
                    status="rejected",
                    error_code="novel.invalid_chapter",
                    error_message="chapterIndex must be an integer.",
                )
            if not (0 <= raw_chap < len(self._toc_entries)):
                return CommandResolution(
                    status="rejected",
                    error_code="novel.invalid_chapter",
                    error_message=f"Chapter index out of range: {raw_chap}",
                )
            self._turn_runner.cancel_active()
            start_chunk = int(
                self._toc_entries[raw_chap].get("startChunkIndex", 0) or 0
            )
            start_chunk = max(0, min(start_chunk, max(0, total_chunks - 1)))
            generating_state = {
                **state,
                "chunkIndex": start_chunk,
                "chapterIndex": raw_chap,
                "phase": "generating",
                "lastError": "",
            }
            self._turn_runner.queue_async_beat(
                branch_id=branch_id,
                expected_committed_version=state_version + 1,
                prefetch_lookup_version=state_version,
                chunk_index=start_chunk,
                state_after_commit=generating_state,
                use_prefetch=False,
                interrupt_playback=True,
                reset_history=True,
            )
            return BehaviorTransition(
                next_state=generating_state,
                messages_to_commit=(),
                invalidate_prefetch=True,
                reset_history_context=True,
            )

        if action == "update_casting":
            if phase == "generating":
                return CommandResolution(
                    status="rejected",
                    error_code="behavior.busy",
                    error_message="Cannot update casting while a Novel Theater beat is generating.",
                )
            next_casting = command.payload.get("casting")
            next_entries = command.payload.get("castEntries")
            if not isinstance(next_casting, Mapping):
                return CommandResolution(
                    status="rejected",
                    error_code="behavior.invalid_command",
                    error_message="casting object is required.",
                )
            resolved_entries = (
                list(next_entries)
                if isinstance(next_entries, list)
                else list(state.get("castEntries") or [])
            )
            existing_mode = normalize_novel_name_mode(
                state.get("nameMode"),
                default=NOVEL_NAME_MODE_STORY,
            )
            raw_next_mode = command.payload.get("nameMode")
            next_name_mode = (
                normalize_novel_name_mode(raw_next_mode, default=existing_mode)
                if isinstance(raw_next_mode, str) and raw_next_mode.strip()
                else existing_mode
            )
            system_prompt = str(command.payload.get("systemPrompt") or "").strip()
            if not system_prompt and callable(self._rebuild_system_prompt):
                casting_map = CastingMap.from_dict(next_casting)
                bound_names = [
                    b.character_name
                    for b in casting_map.bindings
                    if str(b.character_name or "").strip()
                ]
                try:
                    rebuilt = self._rebuild_system_prompt(
                        resolved_entries,
                        bound_names,
                        next_name_mode,
                    )
                except TypeError:
                    rebuilt = self._rebuild_system_prompt(resolved_entries, bound_names)
                system_prompt = str(rebuilt or "").strip()
            if system_prompt:
                queue_prompt = getattr(
                    self._turn_runner, "queue_system_prompt_update", None
                )
                if callable(queue_prompt):
                    queue_prompt(
                        branch_id=branch_id,
                        target_state_version=state_version + 1,
                        system_prompt=system_prompt,
                    )
            updated = {
                **state,
                "nameMode": next_name_mode,
                "casting": dict(next_casting),
                "castEntries": resolved_entries,
            }
            return BehaviorTransition(
                next_state=updated,
                messages_to_commit=(
                    ({"role": "system", "content": system_prompt},)
                    if system_prompt
                    else ()
                ),
                invalidate_prefetch=True,
            )

        return CommandResolution(
            status="rejected",
            error_code="behavior.command.rejected",
            error_message=f"Unsupported Novel Theater action: {action}",
        )

    def on_transition_committed(
        self,
        *,
        branch_id: str,
        state_version: int,
        appended_turn_seqs: tuple[int, ...] = (),
    ) -> None:
        self._turn_runner.on_transition_committed(
            branch_id=branch_id,
            state_version=state_version,
            appended_turn_seqs=appended_turn_seqs,
        )

    def on_playback_idle(
        self,
        *,
        state: Mapping[str, Any],
        state_version: int,
        branch_id: str,
    ) -> BehaviorTransition | None:
        phase = str(state.get("phase") or "")
        chunk_index = max(0, int(state.get("chunkIndex", 0) or 0))
        if phase == "playing" and 0 <= chunk_index < len(self._chunks):
            self._turn_runner.ensure_prefetched(
                branch_id=branch_id,
                chunk_index=chunk_index,
                state_version=state_version,
                state_snapshot=state,
            )
        return None

    def on_before_compact(
        self,
        context: BeforeCompactContext,
        *,
        state: Mapping[str, Any],
    ) -> None:
        raw_entries = state.get("castEntries") or ()
        entries_list = [entry for entry in raw_entries if isinstance(entry, Mapping)]
        name_mode = normalize_novel_name_mode(
            state.get("nameMode"),
            default=NOVEL_NAME_MODE_STORY,
        )
        target_counts = count_cast_targets(entries_list)
        parts: list[str] = []
        for entry in entries_list:
            src = str(entry.get("sourceName") or "").strip()
            target = str(entry.get("targetCharacter") or "").strip()
            aliases = [
                str(a).strip()
                for a in (entry.get("aliases") or ())
                if str(a).strip()
            ]
            if not src:
                continue
            display = (
                effective_cast_display_name(
                    src,
                    target,
                    name_mode=name_mode,
                    target_counts=target_counts,
                )
                if target
                else src
            )
            known_aliases = list(
                dict.fromkeys(
                    item
                    for item in ([src, *aliases] if display != src else aliases)
                    if item and item != display
                )
            )
            label = display if not known_aliases else f"{display} ({'/'.join(known_aliases)})"
            parts.append(label)
        cast_summary = "; ".join(parts[:12])
        instruction = render_novel_compact_instruction(
            cast_summary=cast_summary,
            locale=self._locale_provider(),
        )
        context.add_instruction(instruction)

    def get_casting_map(self, state: Mapping[str, Any]) -> CastingMap:
        return casting_map_from_novel_state(state)

    def on_state_restored(
        self,
        snapshot: BehaviorStateSnapshot | None,
    ) -> None:
        if snapshot is None:
            self._turn_runner.cancel_active(interrupt_playback=True)
        else:
            self._turn_runner.cancel_active()

    def shutdown(self) -> None:
        self._turn_runner.shutdown()


__all__ = ["NovelTheaterBehavior"]
