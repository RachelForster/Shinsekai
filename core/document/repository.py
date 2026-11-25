"""Content-addressed storage repository and session binding for documents."""

from __future__ import annotations

from collections.abc import Iterable
import json
import logging
import os
from pathlib import Path
import tempfile
import time
import uuid

from core.document.chunker import chunk_document
from core.document.ingest import compute_doc_id, ingest_document
from core.document.models import (
    ChapterEntry,
    DocumentChunk,
    DocumentManifest,
    SessionDocumentBinding,
)
from core.storage.layout import StorageLayout
from sdk.file_io import durable_mkdir, durable_rename, sync_directory

logger = logging.getLogger(__name__)

DOCUMENT_BINDING_FILENAME = "document-binding.json"
_INGEST_DIR_PREFIX = ".ingest-"
_TRASH_DIR_PREFIX = ".trash-"
_MANIFEST_FILENAME = "manifest.json"
_NORMALIZED_TEXT_FILENAME = "normalized.txt"
_CHAPTERS_FILENAME = "chapters.json"
_CHUNKS_FILENAME = "chunks.jsonl"
_INDEX_SQLITE_FILENAME = "index.sqlite"
_DOC_ARTIFACT_FILES: tuple[str, ...] = (
    _MANIFEST_FILENAME,
    _NORMALIZED_TEXT_FILENAME,
    _CHAPTERS_FILENAME,
    _CHUNKS_FILENAME,
    _INDEX_SQLITE_FILENAME,
)
_DOC_ARTIFACT_FILE_SET = frozenset(_DOC_ARTIFACT_FILES)


def _fsync_write_text(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _directory_contains_only_allowed(
    directory: Path,
    allowed_files: frozenset[str],
) -> bool:
    if not directory.is_dir():
        return False
    try:
        entries = list(directory.iterdir())
    except OSError:
        return False
    for entry in entries:
        if entry.is_dir() and not entry.is_symlink():
            return False
        if entry.name not in allowed_files:
            return False
    return True


def _safe_cleanup_dir(directory: Path, allowed_files: Iterable[str]) -> None:
    if not directory.is_dir():
        return
    for name in allowed_files:
        candidate = directory / name
        if candidate.is_file() or candidate.is_symlink():
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass
    try:
        directory.rmdir()
    except OSError:
        pass


class DocumentRepository:
    """Manage immutable, content-addressed documents under ``StorageLayout.documents_dir``."""

    def __init__(self, layout: StorageLayout) -> None:
        self._layout = layout

    @property
    def documents_dir(self) -> Path:
        return self._layout.documents_dir

    def cleanup_stale_tmp(self, *, max_age_seconds: float = 3600.0) -> int:
        """Remove stale ``.ingest-*.tmp`` and ``.trash-*.tmp`` staging dirs."""
        root = self.documents_dir
        if not root.is_dir():
            return 0
        now = time.time()
        removed = 0
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            is_temp_dir = (
                entry.name.startswith(_INGEST_DIR_PREFIX)
                or entry.name.startswith(_TRASH_DIR_PREFIX)
            ) and entry.name.endswith(".tmp")
            if not is_temp_dir:
                continue
            try:
                age = now - entry.stat().st_mtime
            except OSError:
                continue
            if age < max_age_seconds:
                continue
            if not _directory_contains_only_allowed(entry, _DOC_ARTIFACT_FILE_SET):
                continue
            _safe_cleanup_dir(entry, _DOC_ARTIFACT_FILES)
            if not entry.exists():
                removed += 1
        if removed:
            sync_directory(root)
        return removed

    def ingest_and_store(
        self,
        source_path: str | Path,
        *,
        title: str | None = None,
        target_chars: int = 800,
        min_chars: int = 500,
        max_chars: int = 1300,
        lookahead_chars: int = 120,
    ) -> DocumentManifest:
        """Ingest, chunk, and atomically publish a content-addressed document."""
        try:
            self.cleanup_stale_tmp()
        except OSError:
            logger.debug("Best-effort stale tmp cleanup skipped", exc_info=True)

        path = Path(source_path)
        raw_bytes = path.read_bytes() if path.is_file() else b""
        if raw_bytes:
            doc_id = compute_doc_id(raw_bytes)
            existing = self.get_manifest(doc_id)
            if existing is not None:
                return existing

        ingested = ingest_document(path, title=title, raw_bytes=raw_bytes or None)
        existing = self.get_manifest(ingested.doc_id)
        if existing is not None:
            return existing

        chunks = chunk_document(
            ingested.normalized_text,
            ingested.chapters,
            target_chars=target_chars,
            min_chars=min_chars,
            max_chars=max_chars,
            lookahead_chars=lookahead_chars,
        )
        manifest = DocumentManifest(
            doc_id=ingested.doc_id,
            title=ingested.title,
            source_format=ingested.source_format,
            source_filename=ingested.source_filename,
            total_chars=len(ingested.normalized_text),
            total_chunks=len(chunks),
            total_chapters=len(ingested.chapters),
            created_at_ms=int(time.time() * 1000),
            page_count=ingested.page_count,
            chunk_config={
                "targetChars": int(target_chars),
                "minChars": int(min_chars),
                "maxChars": int(max_chars),
                "lookaheadChars": int(lookahead_chars),
            },
        )

        durable_mkdir(self.documents_dir)
        target_dir = self._layout.document_dir(ingested.doc_id)
        staging_dir = self.documents_dir / f"{_INGEST_DIR_PREFIX}{uuid.uuid4().hex}.tmp"
        staging_dir.mkdir(parents=True, exist_ok=False)
        try:
            _fsync_write_text(
                staging_dir / _NORMALIZED_TEXT_FILENAME,
                ingested.normalized_text,
            )
            _fsync_write_text(
                staging_dir / _CHAPTERS_FILENAME,
                json.dumps(
                    [chapter.to_dict() for chapter in ingested.chapters],
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            chunks_lines = "\n".join(
                json.dumps(chunk.to_dict(), ensure_ascii=False, separators=(",", ":"))
                for chunk in chunks
            )
            _fsync_write_text(
                staging_dir / _CHUNKS_FILENAME,
                f"{chunks_lines}\n" if chunks_lines else "",
            )
            _fsync_write_text(
                staging_dir / _MANIFEST_FILENAME,
                json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            )
            sync_directory(staging_dir)
            try:
                durable_rename(staging_dir, target_dir, replace=False)
            except OSError:
                concurrent = self.get_manifest(ingested.doc_id)
                if concurrent is not None:
                    _safe_cleanup_dir(staging_dir, _DOC_ARTIFACT_FILES)
                    return concurrent
                raise
        except Exception:
            _safe_cleanup_dir(staging_dir, _DOC_ARTIFACT_FILES)
            raise
        return manifest

    def get_manifest(self, doc_id: str) -> DocumentManifest | None:
        manifest_path = self._layout.document_dir(doc_id) / _MANIFEST_FILENAME
        if not manifest_path.is_file():
            return None
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return DocumentManifest.from_dict(data)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def list_documents(self) -> list[DocumentManifest]:
        root = self.documents_dir
        if not root.is_dir():
            return []
        manifests: list[DocumentManifest] = []
        for entry in sorted(root.iterdir(), key=lambda item: item.name):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            try:
                manifest = self.get_manifest(entry.name)
            except ValueError:
                continue
            if manifest is not None:
                manifests.append(manifest)
        return manifests

    def read_normalized_text(self, doc_id: str) -> str:
        path = self._layout.document_dir(doc_id) / _NORMALIZED_TEXT_FILENAME
        return path.read_text(encoding="utf-8")

    def read_chapters(self, doc_id: str) -> list[ChapterEntry]:
        path = self._layout.document_dir(doc_id) / _CHAPTERS_FILENAME
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [ChapterEntry.from_dict(item) for item in data]

    def read_chunks(self, doc_id: str) -> list[DocumentChunk]:
        path = self._layout.document_dir(doc_id) / _CHUNKS_FILENAME
        chunks: list[DocumentChunk] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                chunks.append(DocumentChunk.from_dict(json.loads(stripped)))
        return chunks

    def get_chunk(self, doc_id: str, index: int) -> DocumentChunk | None:
        idx = int(index)
        if idx < 0:
            return None
        path = self._layout.document_dir(doc_id) / _CHUNKS_FILENAME
        if not path.is_file():
            return None
        current = 0
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                if current == idx:
                    return DocumentChunk.from_dict(json.loads(stripped))
                current += 1
        return None

    def remove_document(self, doc_id: str) -> bool:
        """Atomically quarantine and delete a validated whitelist-only doc directory."""
        target_dir = self._layout.document_dir(doc_id)
        if not target_dir.is_dir():
            return False
        if not _directory_contains_only_allowed(target_dir, _DOC_ARTIFACT_FILE_SET):
            logger.warning(
                "Skipping document deletion for %s because unexpected entries are present",
                doc_id,
            )
            return False
        quarantine_dir = self.documents_dir / f"{_TRASH_DIR_PREFIX}{uuid.uuid4().hex}.tmp"
        durable_rename(target_dir, quarantine_dir, replace=False)
        _safe_cleanup_dir(quarantine_dir, _DOC_ARTIFACT_FILES)
        sync_directory(self.documents_dir)
        return not target_dir.exists()

    @staticmethod
    def write_session_binding(
        session_dir: str | Path,
        binding: SessionDocumentBinding,
    ) -> Path:
        target = Path(session_dir) / DOCUMENT_BINDING_FILENAME
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".doc-binding-", suffix=".tmp", dir=target.parent
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(binding.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            durable_rename(tmp_path, target, replace=True)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        return target

    @staticmethod
    def read_session_binding(session_dir: str | Path) -> SessionDocumentBinding | None:
        target = Path(session_dir) / DOCUMENT_BINDING_FILENAME
        if not target.is_file():
            return None
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return SessionDocumentBinding.from_dict(data)
        except (OSError, ValueError, KeyError, TypeError):
            return None


__all__ = [
    "DOCUMENT_BINDING_FILENAME",
    "DocumentRepository",
]
