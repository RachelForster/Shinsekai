"""Pure in-memory implementation of ConversationSessionPort for contract tests and sandboxes."""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from core.chat_history.models import (
    COMPACT_UP_TO_SEQ_KEY,
    CompactCheckpoint,
    MEMORY_MODE_SHARED,
    MemoryMode,
    OutfitState,
    TruncateReport,
    TurnNode,
    build_compact_summary_message,
    extract_summary_body,
    is_compact_summary_message,
    normalize_memory_mode,
    strip_internal_message_keys,
    turn_node_from_message,
)
from core.vector_store.in_memory import InMemoryMemoryRepository
from sdk.adapters.memory import MemoryRepository


class InMemorySessionStore:
    """Thread-safe pure in-memory reference implementation of ConversationSessionPort."""

    def __init__(
        self,
        session_id: str = "in-memory-session",
        *,
        shared_memory_rollback: Callable[[str, int], int] | None = None,
    ) -> None:
        self._session_id = str(session_id or "in-memory-session").strip() or "in-memory-session"
        self._shared_memory_rollback = shared_memory_rollback
        self._lock = threading.RLock()
        self._save_repo = InMemoryMemoryRepository()
        self._turns: list[TurnNode] = []
        self._next_seq = 0
        self._checkpoints: list[CompactCheckpoint] = []
        self._next_checkpoint_id = 0
        self._memory_mode: MemoryMode = MEMORY_MODE_SHARED
        self._auto_outfit_switch: bool = True
        self._outfits: dict[str, OutfitState] = {}
        self._system_prompts: dict[str, str] = {}
        self._closed = False

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def save_memory_repo(self) -> MemoryRepository:
        return self._save_repo

    def get_system_prompt(self, *, branch_id: str = "main") -> str | None:
        b = str(branch_id or "main").strip() or "main"
        with self._lock:
            return self._system_prompts.get(b)

    def set_system_prompt(self, prompt: str, *, branch_id: str = "main") -> None:
        b = str(branch_id or "main").strip() or "main"
        with self._lock:
            self._system_prompts[b] = str(prompt)

    def append_turn(self, turn: TurnNode) -> TurnNode:
        branch_id = str(turn.branch_id or "main").strip() or "main"
        role = str(turn.role or "").strip()
        if not role:
            raise ValueError("TurnNode.role is required")
        now_ms = int(turn.created_at_ms) if turn.created_at_ms > 0 else int(time.time() * 1000)

        with self._lock:
            for char_name, state in (turn.outfit_snapshot or {}).items():
                cname = str(char_name or state.character_name or "").strip()
                if cname:
                    self._outfits[cname] = OutfitState(
                        character_name=cname,
                        active_group=str(state.active_group or ""),
                        locked=bool(state.locked),
                        updated_at_ms=int(state.updated_at_ms or now_ms),
                    )
            merged_snapshot = dict(self._outfits)
            self._next_seq += 1
            stored = replace(
                turn,
                seq=self._next_seq,
                branch_id=branch_id,
                raw_message=strip_internal_message_keys(turn.raw_message),
                attachments=tuple(copy.deepcopy(dict(a)) for a in turn.attachments),
                outfit_snapshot=merged_snapshot,
                created_at_ms=now_ms,
            )
            self._turns.append(stored)
            return stored

    def append_raw_message(
        self,
        message: Mapping[str, Any],
        *,
        branch_id: str = "main",
        outfit_snapshot: Mapping[str, OutfitState] | None = None,
    ) -> TurnNode:
        b = str(branch_id or "main").strip() or "main"
        if str(message.get("role") or "") == "system":
            self.set_system_prompt(str(message.get("content") or ""), branch_id=b)
            return TurnNode(
                seq=0,
                branch_id=b,
                role="system",
                raw_message=strip_internal_message_keys(message),
                source="system",
                created_at_ms=int(time.time() * 1000),
            )
        node = turn_node_from_message(
            message,
            branch_id=b,
            outfit_snapshot=outfit_snapshot,
        )
        return self.append_turn(node)

    def _delete_branch_turns_after_locked(self, branch_id: str, cutoff: int) -> int:
        before = len(self._turns)
        self._turns = [
            t for t in self._turns if not (t.branch_id == branch_id and t.seq > cutoff)
        ]
        return before - len(self._turns)

    def replace_turns(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        branch_id: str = "main",
    ) -> Sequence[TurnNode]:
        b = str(branch_id or "main").strip() or "main"
        with self._lock:
            self.sync_messages(messages, branch_id=b)
            return self.list_turns(branch_id=b)

    def sync_messages(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        branch_id: str = "main",
    ) -> Sequence[TurnNode]:
        """Synchronize runtime messages without losing pre-compaction turns."""
        b = str(branch_id or "main").strip() or "main"
        with self._lock:
            non_system: list[dict[str, Any]] = []
            for raw in messages:
                if not isinstance(raw, Mapping):
                    continue
                if raw.get("role") == "system":
                    self._system_prompts[b] = str(raw.get("content") or "")
                    continue
                non_system.append(copy.deepcopy(dict(raw)))

            summary_idx = -1
            for idx, item in enumerate(non_system):
                if is_compact_summary_message(item):
                    summary_idx = idx
            if summary_idx >= 0:
                summary_msg = non_system[summary_idx]
                tail_msgs = [strip_internal_message_keys(m) for m in non_system[summary_idx + 1 :]]
                existing_branch = [t for t in self._turns if t.branch_id == b]
                active_cp = self.get_active_compact_checkpoint(branch_id=b)
                raw_up_to = summary_msg.get(COMPACT_UP_TO_SEQ_KEY)
                if raw_up_to is not None:
                    anchor_seq = int(raw_up_to)
                elif active_cp is not None:
                    anchor_seq = active_cp.up_to_seq
                else:
                    anchor_seq = 0

                body = extract_summary_body(str(summary_msg.get("content") or ""))
                if body and (
                    active_cp is None
                    or active_cp.up_to_seq != anchor_seq
                    or active_cp.rolling_summary != body
                ):
                    self.add_compact_checkpoint(
                        up_to_seq=anchor_seq,
                        rolling_summary=body,
                        branch_id=b,
                    )

                post_turns = [t for t in existing_branch if t.seq > anchor_seq]
                post_raw = [dict(t.raw_message) for t in post_turns]
                if post_raw == tail_msgs:
                    return tuple(existing_branch)
                if len(tail_msgs) > len(post_raw) and tail_msgs[: len(post_raw)] == post_raw:
                    for extra in tail_msgs[len(post_raw) :]:
                        self.append_raw_message(extra, branch_id=b)
                    return self.list_turns(branch_id=b)
                self._delete_branch_turns_after_locked(b, anchor_seq)
                for extra in tail_msgs:
                    self.append_raw_message(extra, branch_id=b)
                return self.list_turns(branch_id=b)

            clean_incoming = [strip_internal_message_keys(m) for m in non_system]
            existing_branch = [t for t in self._turns if t.branch_id == b]
            existing_raw = [dict(t.raw_message) for t in existing_branch]

            if existing_raw == clean_incoming:
                return tuple(existing_branch)

            if (
                len(clean_incoming) < len(existing_raw)
                and existing_raw[: len(clean_incoming)] == clean_incoming
            ):
                cutoff = existing_branch[len(clean_incoming) - 1].seq if clean_incoming else 0
                self.truncate_after(cutoff, branch_id=b)
                return self.list_turns(branch_id=b)

            if (
                len(clean_incoming) > len(existing_raw)
                and clean_incoming[: len(existing_raw)] == existing_raw
            ):
                for extra in clean_incoming[len(existing_raw) :]:
                    self.append_raw_message(extra, branch_id=b)
                return self.list_turns(branch_id=b)

            self._turns = [t for t in self._turns if t.branch_id != b]
            self._checkpoints = [cp for cp in self._checkpoints if cp.branch_id != b]
            for item in clean_incoming:
                self.append_raw_message(item, branch_id=b)
            return self.list_turns(branch_id=b)

    def list_turns(
        self,
        *,
        branch_id: str = "main",
        after_seq: int = 0,
        up_to_seq: int | None = None,
    ) -> Sequence[TurnNode]:
        b = str(branch_id or "main").strip() or "main"
        low = int(after_seq)
        high = None if up_to_seq is None else int(up_to_seq)
        with self._lock:
            rows = [
                t
                for t in self._turns
                if t.branch_id == b
                and t.seq > low
                and (high is None or t.seq <= high)
            ]
            rows.sort(key=lambda t: t.seq)
            return tuple(rows)

    def truncate_after(
        self,
        seq: int,
        *,
        branch_id: str = "main",
    ) -> TruncateReport:
        cutoff = max(0, int(seq))
        b = str(branch_id or "main").strip() or "main"
        with self._lock:
            deleted_turns = self._delete_branch_turns_after_locked(b, cutoff)

            before_cp = len(self._checkpoints)
            if cutoff == 0:
                self._checkpoints = [
                    cp for cp in self._checkpoints if cp.branch_id != b
                ]
            else:
                self._checkpoints = [
                    cp
                    for cp in self._checkpoints
                    if not (cp.branch_id == b and cp.up_to_seq >= cutoff)
                ]
            deleted_checkpoints = before_cp - len(self._checkpoints)

            surviving = [t for t in self._turns if t.branch_id == b and t.seq <= cutoff]
            surviving.sort(key=lambda t: t.seq)
            if surviving:
                self._outfits = dict(surviving[-1].outfit_snapshot)
            else:
                self._outfits = {}
            restored_outfits = dict(self._outfits)

            rolled_back_save = self._save_repo.rollback_after_turn(self._session_id, cutoff)

        rolled_back_shared = 0
        if self._shared_memory_rollback is not None:
            rolled_back_shared = int(
                self._shared_memory_rollback(self._session_id, cutoff) or 0
            )

        return TruncateReport(
            kept_up_to_seq=cutoff,
            deleted_turns=deleted_turns,
            deleted_checkpoints=deleted_checkpoints,
            rolled_back_save_memories=rolled_back_save,
            rolled_back_shared_memories=rolled_back_shared,
            restored_outfits=restored_outfits,
        )

    def clear(self, *, branch_id: str | None = None) -> None:
        with self._lock:
            if branch_id is None:
                self._turns.clear()
                self._checkpoints.clear()
                self._outfits.clear()
                self._system_prompts.clear()
                self._save_repo.clear()
            else:
                b = str(branch_id or "main").strip() or "main"
                self._turns = [t for t in self._turns if t.branch_id != b]
                self._checkpoints = [cp for cp in self._checkpoints if cp.branch_id != b]
                self._system_prompts.pop(b, None)
                if b == "main":
                    self._outfits.clear()
        if branch_id is None and self._shared_memory_rollback is not None:
            self._shared_memory_rollback(self._session_id, 0)

    def add_compact_checkpoint(
        self,
        *,
        up_to_seq: int,
        rolling_summary: str,
        branch_id: str = "main",
        created_at_ms: int | None = None,
    ) -> CompactCheckpoint:
        b = str(branch_id or "main").strip() or "main"
        anchor = max(0, int(up_to_seq))
        body = extract_summary_body(rolling_summary)
        if not body:
            raise ValueError("CompactCheckpoint.rolling_summary cannot be empty")
        ts_ms = int(time.time() * 1000) if created_at_ms is None else int(created_at_ms)
        with self._lock:
            self._next_checkpoint_id += 1
            cp = CompactCheckpoint(
                checkpoint_id=self._next_checkpoint_id,
                branch_id=b,
                up_to_seq=anchor,
                rolling_summary=body,
                created_at_ms=ts_ms,
            )
            self._checkpoints.append(cp)
            return cp

    def get_active_compact_checkpoint(
        self,
        *,
        branch_id: str = "main",
        max_seq: int | None = None,
    ) -> CompactCheckpoint | None:
        b = str(branch_id or "main").strip() or "main"
        bound = None if max_seq is None else int(max_seq)
        with self._lock:
            candidates = [
                cp
                for cp in self._checkpoints
                if cp.branch_id == b and (bound is None or cp.up_to_seq <= bound)
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda cp: (cp.up_to_seq, cp.checkpoint_id))
            return candidates[-1]

    def list_compact_checkpoints(
        self,
        *,
        branch_id: str = "main",
    ) -> Sequence[CompactCheckpoint]:
        b = str(branch_id or "main").strip() or "main"
        with self._lock:
            rows = [cp for cp in self._checkpoints if cp.branch_id == b]
            rows.sort(key=lambda cp: (cp.up_to_seq, cp.checkpoint_id))
            return tuple(rows)

    def build_active_llm_messages(
        self,
        *,
        system_prompt: str | None = None,
        branch_id: str = "main",
        max_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        b = str(branch_id or "main").strip() or "main"
        with self._lock:
            resolved_system = (
                system_prompt
                if system_prompt is not None
                else self._system_prompts.get(b)
            )
            cp = self.get_active_compact_checkpoint(branch_id=b, max_seq=max_seq)
            after = cp.up_to_seq if cp is not None else 0
            turns = self.list_turns(branch_id=b, after_seq=after, up_to_seq=max_seq)

            assembled: list[dict[str, Any]] = []
            if resolved_system is not None:
                assembled.append({"role": "system", "content": resolved_system})
            if cp is not None:
                assembled.append(
                    build_compact_summary_message(
                        cp.rolling_summary,
                        up_to_seq=cp.up_to_seq,
                    )
                )
            for turn in turns:
                assembled.append(copy.deepcopy(dict(turn.raw_message)))
            return assembled

    def build_full_raw_messages(
        self,
        *,
        include_system: bool = True,
        branch_id: str = "main",
    ) -> list[dict[str, Any]]:
        """Return 100% uncompacted raw messages for UI history and active.json mirror."""
        b = str(branch_id or "main").strip() or "main"
        with self._lock:
            result: list[dict[str, Any]] = []
            sys_prompt = self._system_prompts.get(b)
            if include_system and sys_prompt is not None:
                result.append({"role": "system", "content": sys_prompt})
            for turn in self.list_turns(branch_id=b):
                result.append(copy.deepcopy(dict(turn.raw_message)))
            return result

    def get_memory_mode(self) -> MemoryMode:
        with self._lock:
            return self._memory_mode

    def set_memory_mode(self, mode: MemoryMode) -> None:
        normalized = normalize_memory_mode(mode)
        with self._lock:
            self._memory_mode = normalized

    def get_auto_outfit_switch(self) -> bool:
        with self._lock:
            return self._auto_outfit_switch

    def set_auto_outfit_switch(self, enabled: bool) -> None:
        with self._lock:
            self._auto_outfit_switch = bool(enabled)

    def get_outfit_state(self, character_name: str) -> OutfitState | None:
        cname = str(character_name or "").strip()
        if not cname:
            return None
        with self._lock:
            return self._outfits.get(cname)

    def list_outfit_states(self) -> Mapping[str, OutfitState]:
        with self._lock:
            return dict(self._outfits)

    def set_outfit_state(self, state: OutfitState) -> None:
        cname = str(state.character_name or "").strip()
        if not cname:
            raise ValueError("OutfitState.character_name is required")
        now_ms = int(state.updated_at_ms) if state.updated_at_ms > 0 else int(time.time() * 1000)
        normalized = OutfitState(
            character_name=cname,
            active_group=str(state.active_group or ""),
            locked=bool(state.locked),
            updated_at_ms=now_ms,
        )
        with self._lock:
            self._outfits[cname] = normalized
            if self._turns:
                last_idx = len(self._turns) - 1
                last_turn = self._turns[last_idx]
                updated_snap = dict(last_turn.outfit_snapshot)
                updated_snap[cname] = normalized
                self._turns[last_idx] = replace(last_turn, outfit_snapshot=updated_snap)

    def close(self) -> None:
        with self._lock:
            self._closed = True


__all__ = ["InMemorySessionStore"]
