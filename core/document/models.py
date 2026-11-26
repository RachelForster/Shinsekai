"""Immutable data models for ingested documents, chapters, chunks, and session bindings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChapterEntry:
    """Logical chapter span within a normalized document."""

    index: int
    title: str
    char_start: int
    char_end: int
    page_start: int | None = None
    page_end: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "charStart": self.char_start,
            "charEnd": self.char_end,
            "pageStart": self.page_start,
            "pageEnd": self.page_end,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChapterEntry:
        return cls(
            index=int(data["index"]),
            title=str(data["title"]),
            char_start=int(data["charStart"]),
            char_end=int(data["charEnd"]),
            page_start=(
                int(data["pageStart"]) if data.get("pageStart") is not None else None
            ),
            page_end=(
                int(data["pageEnd"]) if data.get("pageEnd") is not None else None
            ),
        )


@dataclass(frozen=True)
class DocumentChunk:
    """One chunked reading slice with bounded lookahead into the following slice."""

    chunk_id: str
    index: int
    chapter_index: int
    text: str
    lookahead: str
    char_start: int
    char_end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunkId": self.chunk_id,
            "index": self.index,
            "chapterIndex": self.chapter_index,
            "text": self.text,
            "lookahead": self.lookahead,
            "charStart": self.char_start,
            "charEnd": self.char_end,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DocumentChunk:
        return cls(
            chunk_id=str(data["chunkId"]),
            index=int(data["index"]),
            chapter_index=int(data.get("chapterIndex", 0)),
            text=str(data["text"]),
            lookahead=str(data.get("lookahead") or ""),
            char_start=int(data["charStart"]),
            char_end=int(data["charEnd"]),
        )


@dataclass(frozen=True)
class DocumentManifest:
    """Content-addressed metadata stored in ``manifest.json``."""

    doc_id: str
    title: str
    source_format: str
    source_filename: str
    total_chars: int
    total_chunks: int
    total_chapters: int
    created_at_ms: int
    page_count: int | None = None
    chunk_config: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "docId": self.doc_id,
            "title": self.title,
            "sourceFormat": self.source_format,
            "sourceFilename": self.source_filename,
            "totalChars": self.total_chars,
            "totalChunks": self.total_chunks,
            "totalChapters": self.total_chapters,
            "createdAtMs": self.created_at_ms,
            "pageCount": self.page_count,
            "chunkConfig": dict(self.chunk_config),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DocumentManifest:
        raw_cfg = data.get("chunkConfig")
        cfg = (
            {str(k): int(v) for k, v in raw_cfg.items()}
            if isinstance(raw_cfg, Mapping)
            else {}
        )
        return cls(
            doc_id=str(data["docId"]),
            title=str(data["title"]),
            source_format=str(data["sourceFormat"]),
            source_filename=str(data["sourceFilename"]),
            total_chars=int(data["totalChars"]),
            total_chunks=int(data["totalChunks"]),
            total_chapters=int(data["totalChapters"]),
            created_at_ms=int(data["createdAtMs"]),
            page_count=(
                int(data["pageCount"]) if data.get("pageCount") is not None else None
            ),
            chunk_config=cfg,
        )


@dataclass(frozen=True)
class IngestedDocument:
    """Normalized full-text and extracted structural outline prior to chunking."""

    doc_id: str
    title: str
    source_format: str
    source_filename: str
    normalized_text: str
    chapters: tuple[ChapterEntry, ...]
    page_count: int | None = None


@dataclass(frozen=True)
class SessionDocumentBinding:
    """Session-local binding record pointing to a content-addressed document."""

    doc_id: str
    behavior_id: str
    bound_at_ms: int
    source_filename: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "docId": self.doc_id,
            "behaviorId": self.behavior_id,
            "boundAtMs": self.bound_at_ms,
            "sourceFilename": self.source_filename,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SessionDocumentBinding:
        return cls(
            doc_id=str(data["docId"]),
            behavior_id=str(data["behaviorId"]),
            bound_at_ms=int(data["boundAtMs"]),
            source_filename=str(data.get("sourceFilename") or ""),
        )


__all__ = [
    "ChapterEntry",
    "DocumentChunk",
    "DocumentManifest",
    "IngestedDocument",
    "SessionDocumentBinding",
]
