"""Shared document ingestion, elastic chunking, and content-addressed storage."""

from core.document.chunker import chunk_document
from core.document.ingest import (
    compute_doc_id,
    decode_text_bytes,
    detect_chapters,
    heal_pdf_line_breaks,
    ingest_document,
    ingest_pdf,
    ingest_txt,
    normalize_plain_text,
)
from core.document.models import (
    ChapterEntry,
    DocumentChunk,
    DocumentManifest,
    IngestedDocument,
    SessionDocumentBinding,
)
from core.document.repository import DOCUMENT_BINDING_FILENAME, DocumentRepository

__all__ = [
    "ChapterEntry",
    "DOCUMENT_BINDING_FILENAME",
    "DocumentChunk",
    "DocumentManifest",
    "DocumentRepository",
    "IngestedDocument",
    "SessionDocumentBinding",
    "chunk_document",
    "compute_doc_id",
    "decode_text_bytes",
    "detect_chapters",
    "heal_pdf_line_breaks",
    "ingest_document",
    "ingest_pdf",
    "ingest_txt",
    "normalize_plain_text",
]
