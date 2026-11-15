"""Durable write queue for long-term memory saves."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
import inspect
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
import uuid

from ai.memory.operations import memory_remember

logger = logging.getLogger(__name__)


class QueuePersistenceError(RuntimeError):
    """Raised when the memory write queue cannot be persisted."""


def _default_queue_path() -> Path:
    return Path.cwd() / "data" / "memory" / "pending_queue.json"


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _resolve_character_name(value: str | None) -> str:
    resolved = _clean_text(value)
    if resolved == "__self__":
        return "user"
    return resolved or "user"


def _remember_succeeded(result: Any) -> bool:
    return isinstance(result, dict) and result.get("ok") is True


def _remember_failure_message(result: Any) -> str:
    if not isinstance(result, dict):
        return f"unexpected remember result: {result!r}"
    for key in ("error", "message", "kind", "status"):
        value = _clean_text(result.get(key))
        if value:
            return value
    return f"remember did not report success: {result!r}"


def _clean_str_list(raw: Any) -> list[str]:
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        val = _clean_text(item)
        if val and val.casefold() not in seen:
            seen.add(val.casefold())
            out.append(val)
    return out


@dataclass
class MemoryQueueItem:
    id: str
    character_name: str
    memory: str
    source: str
    confidence: float
    created_at: float
    gist_text: str = ""
    slot_key: str = ""
    kind: str = "episodic"
    topic_tags: list[str] | None = None
    entities: list[str] | None = None
    importance: float | None = None
    event_at: float | None = None
    memory_mode: str = ""
    player_character: str = ""
    source_session_id: str = ""
    source_turn_seq: int | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MemoryQueueItem | None":
        memory = _clean_text(raw.get("memory") or raw.get("content"))
        if not memory:
            return None
        try:
            confidence = float(raw.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        try:
            created_at = float(raw.get("created_at", raw.get("createdAt", time.time())))
        except (TypeError, ValueError):
            created_at = time.time()
        raw_turn_seq = raw.get("source_turn_seq", raw.get("sourceTurnSeq"))
        turn_seq: int | None = None
        if raw_turn_seq is not None and raw_turn_seq != "":
            try:
                turn_seq = int(raw_turn_seq)
            except (TypeError, ValueError):
                turn_seq = None
        raw_imp = raw.get("importance")
        importance: float | None = None
        if raw_imp is not None and raw_imp != "":
            try:
                importance = max(0.0, min(1.0, float(raw_imp)))
            except (TypeError, ValueError):
                importance = None
        raw_event_at = raw.get("event_at", raw.get("eventAt"))
        event_at: float | None = None
        if raw_event_at is not None and raw_event_at != "":
            try:
                event_at = float(raw_event_at)
            except (TypeError, ValueError):
                event_at = None
        topics = _clean_str_list(raw.get("topic_tags") or raw.get("topicTags"))
        ents = _clean_str_list(raw.get("entities"))
        return cls(
            id=_clean_text(raw.get("id")) or uuid.uuid4().hex,
            character_name=_resolve_character_name(
                raw.get("character_name") or raw.get("characterName")
            ),
            memory=memory,
            source=_clean_text(raw.get("source")) or "unknown",
            confidence=max(0.0, min(1.0, confidence)),
            created_at=created_at,
            gist_text=_clean_text(raw.get("gist_text") or raw.get("gistText")),
            slot_key=_clean_text(raw.get("slot_key") or raw.get("slotKey")),
            kind=_clean_text(raw.get("kind")) or "episodic",
            topic_tags=topics or None,
            entities=ents or None,
            importance=importance,
            event_at=event_at,
            memory_mode=_clean_text(raw.get("memory_mode") or raw.get("memoryMode")),
            player_character=_clean_text(
                raw.get("player_character") or raw.get("playerCharacter")
            ),
            source_session_id=_clean_text(
                raw.get("source_session_id") or raw.get("sourceSessionId")
            ),
            source_turn_seq=turn_seq,
        )


class MemoryWriteQueue:
    """Thread-safe queue that survives process restarts."""

    def __init__(
        self,
        *,
        path: str | Path | None = None,
        remember_func: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else _default_queue_path()
        self._remember = remember_func or memory_remember
        self._lock = threading.RLock()
        self._items: list[MemoryQueueItem] = []
        self._load()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(item) for item in self._items]

    def enqueue(
        self,
        memory: str,
        *,
        character_name: str | None = None,
        source: str = "auto",
        confidence: float = 1.0,
        gist_text: str = "",
        slot_key: str = "",
        kind: str = "episodic",
        topic_tags: Sequence[str] = (),
        entities: Sequence[str] = (),
        importance: float | None = None,
        event_at: float | None = None,
        memory_mode: str = "",
        player_character: str = "",
        source_session_id: str = "",
        source_turn_seq: int | None = None,
    ) -> dict[str, Any]:
        text = _clean_text(memory)
        if not text:
            return {"ok": False, "error": "memory is required"}
        character = _resolve_character_name(character_name)
        try:
            clean_confidence = float(confidence)
        except (TypeError, ValueError):
            clean_confidence = 1.0
        clean_slot = _clean_text(slot_key)
        clean_kind = _clean_text(kind) or "episodic"
        clean_session = _clean_text(source_session_id)
        clean_seq = None if source_turn_seq is None else int(source_turn_seq)
        clean_imp: float | None = None
        if importance is not None:
            try:
                clean_imp = max(0.0, min(1.0, float(importance)))
            except (TypeError, ValueError):
                clean_imp = None
        clean_event_at = None if event_at is None else float(event_at)
        clean_topics = _clean_str_list(topic_tags)
        clean_entities = _clean_str_list(entities)
        dedupe_key = self._dedupe_key(character, text)
        with self._lock:
            for item in self._items:
                if self._dedupe_key(item.character_name, item.memory) == dedupe_key:
                    return {"ok": True, "queued": False, "duplicate": True, "id": item.id}
            item = MemoryQueueItem(
                id=uuid.uuid4().hex,
                character_name=character,
                memory=text,
                source=_clean_text(source) or "auto",
                confidence=max(0.0, min(1.0, clean_confidence)),
                created_at=time.time(),
                gist_text=_clean_text(gist_text),
                slot_key=clean_slot,
                kind=clean_kind,
                topic_tags=clean_topics or None,
                entities=clean_entities or None,
                importance=clean_imp,
                event_at=clean_event_at,
                memory_mode=_clean_text(memory_mode),
                player_character=_clean_text(player_character),
                source_session_id=clean_session,
                source_turn_seq=clean_seq,
            )
            self._items.append(item)
            self._save_locked()
            return {"ok": True, "queued": True, "id": item.id}

    def rollback_after_turn(self, session_id: str, turn_seq: int) -> int:
        """Drop queued items originating from session_id at turns > turn_seq."""
        sid = _clean_text(session_id)
        if not sid:
            return 0
        cutoff = max(0, int(turn_seq))
        with self._lock:
            retained = [
                item
                for item in self._items
                if not (
                    item.source_session_id == sid
                    and item.source_turn_seq is not None
                    and item.source_turn_seq > cutoff
                )
            ]
            removed = len(self._items) - len(retained)
            if removed > 0:
                previous = list(self._items)
                self._items = retained
                try:
                    self._save_locked()
                except QueuePersistenceError:
                    self._items = previous
                    raise
            return removed

    def _invoke_remember(self, item: MemoryQueueItem) -> dict[str, Any]:
        extra_kwargs: dict[str, Any] = {}
        if item.gist_text:
            extra_kwargs["gist_text"] = item.gist_text
        if item.slot_key:
            extra_kwargs["slot_key"] = item.slot_key
        if item.kind and item.kind != "episodic":
            extra_kwargs["kind"] = item.kind
        if item.topic_tags:
            extra_kwargs["topic_tags"] = tuple(item.topic_tags)
        if item.entities:
            extra_kwargs["entities"] = tuple(item.entities)
        if item.importance is not None:
            extra_kwargs["importance"] = item.importance
        if item.event_at is not None:
            extra_kwargs["event_at"] = item.event_at
        if item.memory_mode:
            extra_kwargs["memory_mode"] = item.memory_mode
        if item.player_character:
            extra_kwargs["player_character"] = item.player_character
        if item.source_session_id:
            extra_kwargs["source_session_id"] = item.source_session_id
        if item.source_turn_seq is not None:
            extra_kwargs["source_turn_seq"] = item.source_turn_seq
        if not extra_kwargs:
            return self._remember(item.memory, item.character_name)
        try:
            params = inspect.signature(self._remember).parameters
        except (TypeError, ValueError):
            return self._remember(item.memory, item.character_name)
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        accepted = {
            k: v
            for k, v in extra_kwargs.items()
            if has_var_kw or k in params
        }
        return self._remember(item.memory, item.character_name, **accepted)

    def flush(self, *, limit: int | None = None) -> dict[str, Any]:
        """Try to persist queued memories through the configured remember function."""

        with self._lock:
            items = list(self._items if limit is None else self._items[: max(0, int(limit))])
        if not items:
            return {"attempted": 0, "saved": 0, "pending": len(self), "errors": []}

        saved_ids: set[str] = set()
        errors: list[dict[str, str]] = []
        for item in items:
            try:
                result = self._invoke_remember(item)
            except Exception as exc:
                logger.exception("memory queue flush failed")
                errors.append({"id": item.id, "error": str(exc)})
                continue
            if not _remember_succeeded(result):
                errors.append({"id": item.id, "error": _remember_failure_message(result)})
                continue
            saved_ids.add(item.id)

        with self._lock:
            if saved_ids:
                previous_items = list(self._items)
                self._items = [item for item in self._items if item.id not in saved_ids]
                try:
                    self._save_locked()
                except QueuePersistenceError:
                    self._items = previous_items
                    raise
            return {
                "attempted": len(items),
                "saved": len(saved_ids),
                "pending": len(self._items),
                "errors": errors,
            }

    def _load(self) -> None:
        with self._lock:
            self._items = []
            if not self.path.is_file():
                return
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.exception("failed to load memory queue")
                return
            rows = raw.get("items") if isinstance(raw, dict) else raw
            if not isinstance(rows, list):
                return
            seen: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                item = MemoryQueueItem.from_dict(row)
                if item is None:
                    continue
                key = self._dedupe_key(item.character_name, item.memory)
                if key in seen:
                    continue
                seen.add(key)
                self._items.append(item)

    def _save_locked(self) -> None:
        payload = {"items": [asdict(item) for item in self._items]}
        data = json.dumps(payload, ensure_ascii=False, indent=2)
        tmp_path = self.path.with_name(f"{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(data, encoding="utf-8")
            os.replace(tmp_path, self.path)
        except OSError as exc:
            logger.error("failed to persist memory queue to %s", self.path, exc_info=True)
            raise QueuePersistenceError(f"failed to persist memory queue to {self.path}") from exc
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                logger.debug("failed to remove memory queue temp file %s", tmp_path, exc_info=True)

    @staticmethod
    def _dedupe_key(character_name: str, memory: str) -> str:
        return f"{_resolve_character_name(character_name).casefold()}\n{_clean_text(memory).casefold()}"
