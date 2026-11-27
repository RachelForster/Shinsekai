"""Import, inspect, and list shared Novel Theater documents."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from application.chat.history.paths import _state_project_root
from core.document import (
    ChapterEntry,
    DocumentChunk,
    DocumentManifest,
    DocumentRepository,
)
from core.storage.layout import StorageLayout
from sdk.exception.types import AppError


def build_chapter_toc_entries(
    chapters: Sequence[ChapterEntry],
    chunks: Sequence[DocumentChunk],
) -> list[dict[str, Any]]:
    """Build chapter TOC metadata mapped onto chunk ranges."""
    start_by_chapter: dict[int, int] = {}
    count_by_chapter: dict[int, int] = {}
    for chunk in chunks:
        cidx = int(chunk.chapter_index)
        start_by_chapter.setdefault(cidx, int(chunk.index))
        count_by_chapter[cidx] = count_by_chapter.get(cidx, 0) + 1

    last_known_start = 0
    entries: list[dict[str, Any]] = []
    for chapter in sorted(chapters, key=lambda item: item.index):
        cidx = int(chapter.index)
        start_chunk = start_by_chapter.get(cidx, last_known_start)
        last_known_start = start_chunk
        entries.append(
            {
                "index": cidx,
                "title": chapter.title,
                "startChunkIndex": start_chunk,
                "chunkCount": count_by_chapter.get(cidx, 0),
                "pageStart": chapter.page_start,
                "pageEnd": chapter.page_end,
            }
        )
    return entries


def _document_repo(state: Any) -> DocumentRepository:
    return DocumentRepository(StorageLayout(_state_project_root(state)))


def serialize_document_summary(
    repo: DocumentRepository,
    manifest: DocumentManifest,
) -> dict[str, Any]:
    """Serialize one stored document's manifest and chapter TOC."""
    chapters = repo.read_chapters(manifest.doc_id)
    chunks = repo.read_chunks(manifest.doc_id)
    return {
        "manifest": manifest.to_dict(),
        "chapters": build_chapter_toc_entries(chapters, chunks),
    }


def serialize_document_detail(
    repo: DocumentRepository,
    manifest: DocumentManifest,
    *,
    sample_chunk_count: int = 3,
) -> dict[str, Any]:
    """Serialize manifest, full chapter TOC, and leading preview chunks."""
    chapters = repo.read_chapters(manifest.doc_id)
    chunks = repo.read_chunks(manifest.doc_id)
    samples = [
        {
            "chunkId": chunk.chunk_id,
            "index": chunk.index,
            "chapterIndex": chunk.chapter_index,
            "text": chunk.text,
        }
        for chunk in chunks[: max(0, int(sample_chunk_count))]
    ]
    return {
        "manifest": manifest.to_dict(),
        "chapters": build_chapter_toc_entries(chapters, chunks),
        "sampleChunks": samples,
    }


def import_novel_document(
    state: Any,
    source_path: str | Path,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """Ingest a TXT/Markdown/PDF novel into the shared content-addressed store."""
    repo = _document_repo(state)
    clean_title = str(title or "").strip() or None
    try:
        manifest = repo.ingest_and_store(source_path, title=clean_title)
    except AppError:
        raise
    except (ValueError, OSError) as exc:
        raise AppError(
            "novel.import_failed",
            params={"reason": str(exc)},
            fallback_message=str(exc) or "Failed to import document.",
            http_status=400,
        ) from exc
    return serialize_document_detail(repo, manifest)


def list_novel_documents(state: Any) -> list[dict[str, Any]]:
    """List ingested documents stored in the shared repository."""
    repo = _document_repo(state)
    items: list[dict[str, Any]] = []
    for manifest in repo.list_documents():
        try:
            items.append(serialize_document_summary(repo, manifest))
        except (OSError, ValueError):
            continue
    items.sort(
        key=lambda item: int((item.get("manifest") or {}).get("createdAtMs") or 0),
        reverse=True,
    )
    return items


def get_novel_document_detail(state: Any, doc_id: str) -> dict[str, Any]:
    """Return manifest, chapter TOC, and preview chunks for a stored document."""
    clean_id = str(doc_id or "").strip().lower()
    repo = _document_repo(state)
    try:
        manifest = repo.get_manifest(clean_id)
    except ValueError as exc:
        raise AppError(
            "novel.document_not_found",
            params={"docId": clean_id},
            fallback_message="Document not found.",
            http_status=404,
        ) from exc
    if manifest is None:
        raise AppError(
            "novel.document_not_found",
            params={"docId": clean_id},
            fallback_message="Document not found.",
            http_status=404,
        )
    return serialize_document_detail(repo, manifest)


__all__ = [
    "build_chapter_toc_entries",
    "get_novel_document_detail",
    "import_novel_document",
    "list_novel_documents",
    "serialize_document_detail",
    "serialize_document_summary",
]
