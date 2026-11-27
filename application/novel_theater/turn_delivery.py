"""Delivery, LLM history synchronization, and compaction helpers for Novel Theater."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import copy
import logging
import threading
from typing import Any
import uuid

from ai.llm.speculative_dialog import (
    SpeculativeDialogResult,
    run_speculative_dialog_generation,
)
from application.novel_theater.prepare_launch import resolve_chapter_index_for_chunk
from application.session_behavior.casting import CastingMap
from core.chat_history.identity import CHAT_TURN_ID, DialogIdentities
from core.chat_history.models import CHUNK_FEED_SOURCE
from core.chat_history.storage import (
    chat_history_active_path,
    write_active_history_snapshot,
)
from sdk.messages import LLMDialogMessage, PresentationMessage

logger = logging.getLogger(__name__)


def tr_or(key: str, default: str, *, locale: str = "", **kwargs: Any) -> str:
    """Resolve an i18n bundle key for the requested locale, falling back cleanly."""
    try:
        if locale:
            from i18n import tr_in_bundle

            text = tr_in_bundle(key, locale, **kwargs)
        else:
            from i18n import tr

            text = tr(key, **kwargs)
        return default if text == key else str(text)
    except Exception:
        return default


def build_beat_messages(
    prompt: str,
    raw_text: str,
) -> tuple[str, tuple[dict[str, Any], dict[str, Any]]]:
    """Build correlated user chunk-feed + assistant reply messages with shared turn ID."""
    history_turn_id = uuid.uuid4().hex
    return history_turn_id, (
        {
            "role": "user",
            "source": CHUNK_FEED_SOURCE,
            "content": prompt,
            CHAT_TURN_ID: history_turn_id,
        },
        {
            "role": "assistant",
            "content": raw_text,
            CHAT_TURN_ID: history_turn_id,
        },
    )


def snapshot_messages_with_chunk(
    llm_manager: Any | None,
    chunk_prompt: str,
    *,
    history_lock: threading.RLock,
) -> list[dict[str, Any]]:
    """Copy committed LLM history messages and append an ephemeral chunk feed turn."""
    with history_lock:
        raw = (
            llm_manager.get_messages()
            if llm_manager is not None and hasattr(llm_manager, "get_messages")
            else []
        )
        copied = [copy.deepcopy(dict(m)) for m in raw if isinstance(m, Mapping)]
    copied.append({"role": "user", "source": CHUNK_FEED_SOURCE, "content": chunk_prompt})
    return copied


def run_background_compaction(
    llm_manager: Any | None,
    *,
    history_lock: threading.RLock | None = None,
) -> None:
    """Compact LLM history messages in-place when the compactor threshold is met."""
    lock = history_lock or threading.RLock()
    with lock:
        if llm_manager is None:
            return
        history_obj = getattr(llm_manager, "_history", None)
        compactor = getattr(history_obj, "compact_manager", None) if history_obj else None
        auto_fn = getattr(compactor, "auto_compact_if_needed", None)
        target_list = getattr(history_obj, "messages", None) if history_obj else None
        if not (callable(auto_fn) and isinstance(target_list, list)):
            return
        try:
            compacted = auto_fn(target_list)
            if compacted is not target_list:
                history_obj.messages = compacted
                prune = getattr(history_obj, "_prune_seq_index", None)
                if callable(prune):
                    prune()
        except Exception:
            logger.warning("Novel Theater compaction failed", exc_info=True)


def update_llm_system_prompt(
    llm_manager: Any | None,
    system_prompt: str,
    *,
    history_path: str = "",
    history_lock: threading.RLock | None = None,
) -> None:
    """Refresh active LLMManager system prompt/template in place without clearing turns."""
    clean_prompt = str(system_prompt or "")
    if llm_manager is None or not clean_prompt.strip():
        return
    lock = history_lock or threading.RLock()
    with lock:
        history_obj = getattr(llm_manager, "_history", None)
        if history_obj is not None:
            history_obj.user_template = clean_prompt
        adapter = getattr(llm_manager, "llm_adapter", None)
        set_tpl = getattr(adapter, "set_user_template", None) if adapter is not None else None
        if callable(set_tpl):
            set_tpl(clean_prompt)
        target_list = getattr(history_obj, "messages", None) if history_obj is not None else None
        if isinstance(target_list, list):
            if (
                target_list
                and isinstance(target_list[0], Mapping)
                and target_list[0].get("role") == "system"
            ):
                target_list[0] = {**dict(target_list[0]), "content": clean_prompt}
            else:
                target_list.insert(0, {"role": "system", "content": clean_prompt})
        if history_path and hasattr(llm_manager, "get_messages"):
            try:
                write_active_history_snapshot(
                    chat_history_active_path(history_path), llm_manager.get_messages()
                )
            except OSError:
                logger.debug("Failed to refresh active.json after prompt update", exc_info=True)


def reset_llm_history_to_system_prompt(
    llm_manager: Any | None,
    *,
    history_path: str = "",
    ui_updates: Any | None = None,
    history_lock: threading.RLock | None = None,
) -> None:
    """Clear prior beat turns in memory and active.json while keeping the system prompt."""
    lock = history_lock or threading.RLock()
    with lock:
        if llm_manager is not None:
            history_obj = getattr(llm_manager, "_history", None)
            target_list = getattr(history_obj, "messages", None) if history_obj is not None else None
            user_template = str(
                (getattr(history_obj, "user_template", None) if history_obj is not None else None)
                or getattr(llm_manager, "user_template", "")
                or ""
            )
            if isinstance(target_list, list):
                preserved: list[dict[str, Any]] = []
                if (
                    target_list
                    and isinstance(target_list[0], Mapping)
                    and target_list[0].get("role") == "system"
                ):
                    preserved = [copy.deepcopy(dict(target_list[0]))]
                elif user_template:
                    preserved = [{"role": "system", "content": user_template}]
                target_list[:] = preserved
            seq_map = getattr(history_obj, "_seq_by_msg_id", None) if history_obj is not None else None
            if isinstance(seq_map, dict):
                seq_map.clear()
            if history_path and hasattr(llm_manager, "get_messages"):
                try:
                    write_active_history_snapshot(
                        chat_history_active_path(history_path), llm_manager.get_messages()
                    )
                except OSError:
                    logger.debug("Failed to refresh active.json after history reset", exc_info=True)
    if ui_updates is not None and hasattr(ui_updates, "sync_history_entries"):
        try:
            ui_updates.sync_history_entries()
        except Exception:
            pass


def sync_llm_history(
    llm_manager: Any | None,
    *,
    user_prompt: str = "",
    assistant_content: str = "",
    appended_turn_seqs: tuple[int, ...] = (),
    messages_committed: Sequence[dict[str, Any]] | None = None,
    history_path: str = "",
    history_lock: threading.RLock | None = None,
    compact_now: bool = False,
    should_abort: Callable[[], bool] | None = None,
) -> None:
    """Append newly committed turn messages to LLMManager memory and refresh active.json."""
    if messages_committed is not None:
        batch = [copy.deepcopy(dict(m)) for m in messages_committed]
    else:
        batch = [
            {"role": "user", "source": CHUNK_FEED_SOURCE, "content": user_prompt},
            {"role": "assistant", "content": assistant_content},
        ]

    lock = history_lock or threading.RLock()
    with lock:
        if llm_manager is None or (callable(should_abort) and should_abort()):
            return
        history_obj = getattr(llm_manager, "_history", None)
        target_list = getattr(history_obj, "messages", None)
        if isinstance(target_list, list):
            target_list.extend(batch)
            seq_map = getattr(history_obj, "_seq_by_msg_id", None)
            if isinstance(seq_map, dict) and len(appended_turn_seqs) == len(batch):
                for msg_obj, seq in zip(batch, appended_turn_seqs):
                    seq_map[id(msg_obj)] = int(seq)
        if compact_now:
            run_background_compaction(llm_manager, history_lock=lock)
        if history_path:
            try:
                current_msgs = llm_manager.get_messages()
                write_active_history_snapshot(
                    chat_history_active_path(history_path), current_msgs
                )
            except OSError:
                logger.debug("Failed to refresh active.json snapshot", exc_info=True)


def deliver_dialogs_to_stage(
    dialogs: Sequence[Mapping[str, Any]],
    *,
    dialog_queue: Any | None,
    presentation_queue: Any | None,
    ui_updates: Any | None,
    chat_turn_service: Any | None,
    history_path: str = "",
    casting_map: CastingMap | None = None,
    opencc: Any | None = None,
    history_turn_id: str = "",
    existing_turn: Any | None = None,
) -> None:
    """Enqueue beat dialogs through dialog_queue and signal turn completion for playback."""
    del presentation_queue, history_path, casting_map, opencc
    turn = existing_turn
    if turn is None and chat_turn_service is not None:
        turn = chat_turn_service.begin_turn()
    identities = DialogIdentities(history_turn_id)
    emitted = 0
    try:
        for item in dialogs:
            if not isinstance(item, Mapping):
                continue
            if turn is not None and turn.is_cancelled():
                break
            msg = LLMDialogMessage(**dict(item))
            copied = msg.model_copy(
                update={
                    "turn_id": getattr(turn, "id", None),
                    "dialog_id": identities.next(msg.model_dump(by_alias=True)),
                }
            )
            if dialog_queue is not None:
                dialog_queue.put(copied)
                emitted += 1
    finally:
        if turn is not None and chat_turn_service is not None:
            chat_turn_service.mark_generation_complete(turn)
            if emitted == 0 or dialog_queue is None:
                chat_turn_service.mark_idle(turn)
        if (emitted == 0 or dialog_queue is None) and ui_updates is not None:
            post_finished = getattr(ui_updates, "post_llm_reply_finished", None)
            if callable(post_finished):
                post_finished()
    if ui_updates is not None and hasattr(ui_updates, "sync_history_entries"):
        try:
            ui_updates.sync_history_entries()
        except Exception:
            pass


def abort_pending_turn(turn: Any | None, chat_turn_service: Any | None) -> None:
    """Release an in-flight chat turn back to idle when aborted or failed."""
    if turn is not None and chat_turn_service is not None:
        chat_turn_service.mark_generation_complete(turn)
        chat_turn_service.mark_idle(turn)


def toggle_busy_bar(ui_updates: Any | None, *, visible: bool, locale: str = "") -> None:
    """Best-effort show/hide stage busy bar during beat generation."""
    if ui_updates is None:
        return
    try:
        if visible and hasattr(ui_updates, "post_busy_bar"):
            ui_updates.post_busy_bar(
                tr_or("common.ai_working_title", "Generating...", locale=locale),
                0.0,
            )
        elif not visible and hasattr(ui_updates, "hide_busy_bar"):
            ui_updates.hide_busy_bar()
    except Exception:
        pass


def resolve_casting_policy(
    state_snapshot: Mapping[str, Any],
    opencc_provider: Callable[[], Any | None],
) -> tuple[Callable[[str], bool], tuple[str, ...]]:
    """Build speaker media gating predicate and bound-speaker tuple from state."""
    casting = CastingMap.from_dict(state_snapshot.get("casting") or {})

    def _requires_media(speaker: str) -> bool:
        return casting.speaker_requires_media(speaker, cc=opencc_provider())

    return _requires_media, casting.bound_speaker_names()


def execute_direct_beat_generation(
    *,
    prompt: str,
    payload_messages: list[dict[str, Any]],
    state_snapshot: Mapping[str, Any],
    llm_manager: Any | None,
    create_adapter: Callable[[], Any],
    opencc_provider: Callable[[], Any | None],
    cancel_event: threading.Event,
    media_selection_mode: str,
    locale_provider: Callable[[], str],
) -> tuple[SpeculativeDialogResult, tuple[dict[str, Any], dict[str, Any]], str]:
    """Run direct speculative dialog generation for one chunk and package history turns."""
    requires_media, bound_speakers = resolve_casting_policy(
        state_snapshot, opencc_provider
    )
    gen_cfg = dict(getattr(llm_manager, "generation_config", None) or {})
    result = run_speculative_dialog_generation(
        adapter=create_adapter(),
        messages=payload_messages,
        generation_kwargs=gen_cfg,
        cancel_event=cancel_event,
        media_selection_mode=media_selection_mode,
        speaker_requires_media=requires_media,
        bound_speakers=bound_speakers,
        locale=locale_provider(),
    )
    turn_id, messages_to_commit = build_beat_messages(prompt, result.raw_text)
    return result, messages_to_commit, turn_id


def build_committed_beat_state(
    state_snapshot: Mapping[str, Any],
    *,
    chunk_index: int,
    total_chunks: int,
    toc_entries: Sequence[Mapping[str, Any]],
) -> tuple[int, dict[str, Any]]:
    """Compute next persisted NovelTheater state dict after a beat completes."""
    next_chunk_index = chunk_index + 1
    ended = next_chunk_index >= total_chunks
    chap_idx, _ = resolve_chapter_index_for_chunk(
        max(0, total_chunks - 1) if ended else next_chunk_index,
        toc_entries,
    )
    return next_chunk_index, {
        **dict(state_snapshot),
        "chunkIndex": next_chunk_index,
        "chapterIndex": chap_idx,
        "phase": "ended" if ended else "playing",
        "lastError": "",
    }


def handle_beat_failure(
    *,
    branch_id: str,
    expected_version: int,
    state_snapshot: Mapping[str, Any],
    reason: str,
    commit_async: Callable[..., Any] | None,
    ui_updates: Any | None,
    presentation_queue: Any | None,
    turn: Any | None,
    chat_turn_service: Any | None,
    locale: str = "",
) -> None:
    """Persist ``phase='error'``, notify the stage, and release the chat turn."""
    if callable(commit_async):
        commit_async(
            branch_id,
            expected_version,
            {**dict(state_snapshot), "phase": "error", "lastError": str(reason or "")},
            (),
        )
    notify_beat_error(ui_updates, presentation_queue, str(reason or ""), locale=locale)
    abort_pending_turn(turn, chat_turn_service)


def notify_beat_error(
    ui_updates: Any | None,
    presentation_queue: Any | None,
    error_text: str,
    *,
    locale: str = "",
) -> None:
    """Surface a failed beat on the stage presentation queue without leaking crashes."""
    del ui_updates
    if presentation_queue is None:
        return
    try:
        presentation_queue.put(
            PresentationMessage(
                audio_path="",
                name="system",
                asset_id="-1",
                text=tr_or(
                    "desktop.llm_parse_empty",
                    error_text or "LLM returned no valid response",
                    locale=locale,
                ),
                is_system_message=True,
                effect="",
            )
        )
    except Exception:
        pass


__all__ = [
    "abort_pending_turn",
    "build_beat_messages",
    "build_committed_beat_state",
    "deliver_dialogs_to_stage",
    "execute_direct_beat_generation",
    "handle_beat_failure",
    "notify_beat_error",
    "reset_llm_history_to_system_prompt",
    "resolve_casting_policy",
    "run_background_compaction",
    "snapshot_messages_with_chunk",
    "sync_llm_history",
    "toggle_busy_bar",
    "tr_or",
    "update_llm_system_prompt",
]
