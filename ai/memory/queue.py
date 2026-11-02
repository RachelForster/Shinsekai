"""Durable write queue for long-term memory saves."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from ai.memory.operations import memory_remember

logger = logging.getLogger(__name__)


class QueuePersistenceError(RuntimeError):
    """Raised when the memory write queue cannot be persisted."""


def _default_queue_path() -> Path:
    return Path.cwd() / "data" / "memory" / "pending_queue.json"


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _resolve_character_name(value: str | None) -> str:
    return _clean_text(value) or "user"


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


@dataclass
class MemoryQueueItem:
    id: str
    character_name: str
    memory: str
    source: str
    confidence: float
    created_at: float

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
        return cls(
            id=_clean_text(raw.get("id")) or uuid.uuid4().hex,
            character_name=_resolve_character_name(raw.get("character_name") or raw.get("characterName")),
            memory=memory,
            source=_clean_text(raw.get("source")) or "unknown",
            confidence=max(0.0, min(1.0, confidence)),
            created_at=created_at,
        )


class MemoryWriteQueue:
    """Thread-safe queue that survives process restarts."""

    def __init__(
        self,
        *,
        path: str | Path | None = None,
        remember_func: Callable[[str, str | None], dict[str, Any]] | None = None,
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
    ) -> dict[str, Any]:
        text = _clean_text(memory)
        if not text:
            return {"ok": False, "error": "memory is required"}
        character = _resolve_character_name(character_name)
        try:
            clean_confidence = float(confidence)
        except (TypeError, ValueError):
            clean_confidence = 1.0
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
            )
            self._items.append(item)
            self._save_locked()
            return {"ok": True, "queued": True, "id": item.id}

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
                result = self._remember(item.memory, item.character_name)
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
