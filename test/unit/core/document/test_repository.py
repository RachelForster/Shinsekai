"""Unit tests for content-addressed DocumentRepository and atomic publishing."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pytest

from core.document import (
    DOCUMENT_BINDING_FILENAME,
    DocumentRepository,
    SessionDocumentBinding,
)
from core.storage.layout import StorageLayout


def test_repository_content_addressed_dedup_and_reads(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path)
    repo = DocumentRepository(layout)

    body = "第一章 相遇\n\n" + ("这是正文的精彩内容，需要足够多字符来稳定读取。\n\n" * 15)
    file_a = tmp_path / "novel_a.txt"
    file_b = tmp_path / "novel_copy.txt"
    file_a.write_text(body, encoding="utf-8")
    file_b.write_text(body, encoding="utf-8")

    manifest_a = repo.ingest_and_store(file_a, title="Novel A")
    manifest_b = repo.ingest_and_store(file_b, title="Novel B")

    assert manifest_a.doc_id == manifest_b.doc_id
    assert len(repo.list_documents()) == 1
    assert repo.get_manifest(manifest_a.doc_id) == manifest_a
    assert len(repo.read_chapters(manifest_a.doc_id)) >= 1
    chunks = repo.read_chunks(manifest_a.doc_id)
    assert len(chunks) == manifest_a.total_chunks
    assert repo.get_chunk(manifest_a.doc_id, 0) == chunks[0]
    assert repo.get_chunk(manifest_a.doc_id, -1) is None
    assert "第一章 相遇" in repo.read_normalized_text(manifest_a.doc_id)


def test_repository_stale_tmp_cleanup_and_whitelist_delete(tmp_path: Path) -> None:
    layout = StorageLayout(tmp_path)
    repo = DocumentRepository(layout)
    repo.documents_dir.mkdir(parents=True, exist_ok=True)

    stale_dir = repo.documents_dir / ".ingest-oldtmp.tmp"
    stale_dir.mkdir()
    (stale_dir / "manifest.json").write_text("{}", encoding="utf-8")
    old_ts = time.time() - 7200.0
    os.utime(stale_dir, (old_ts, old_ts))

    fresh_dir = repo.documents_dir / ".ingest-fresh.tmp"
    fresh_dir.mkdir()
    (fresh_dir / "manifest.json").write_text("{}", encoding="utf-8")

    cleaned = repo.cleanup_stale_tmp(max_age_seconds=3600.0)
    assert cleaned == 1
    assert not stale_dir.exists()
    assert fresh_dir.exists()

    doc_file = tmp_path / "book.txt"
    doc_file.write_text("正文一段足够长的内容来生成文档包。" * 5, encoding="utf-8")
    manifest = repo.ingest_and_store(doc_file)
    doc_dir = layout.document_dir(manifest.doc_id)
    # Unlisted custom file should block blind directory destruction.
    custom = doc_dir / "user_notes.txt"
    custom.write_text("keep", encoding="utf-8")
    assert repo.remove_document(manifest.doc_id) is False
    assert custom.is_file()
    assert not (doc_dir / "manifest.json").exists()

    custom.unlink()
    assert repo.remove_document(manifest.doc_id) is True
    assert not doc_dir.exists()


def test_layout_rejects_invalid_doc_id_and_binds_session_atomically(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(tmp_path)
    with pytest.raises(ValueError):
        layout.document_dir("../escape")
    with pytest.raises(ValueError):
        layout.document_dir("not-a-sha256")

    session_dir = layout.chat_history_dir / "session_1"
    binding = SessionDocumentBinding(
        doc_id="a" * 64,
        behavior_id="novel_theater",
        bound_at_ms=123456,
        source_filename="novel.txt",
    )
    bound_path = DocumentRepository.write_session_binding(session_dir, binding)
    assert bound_path == session_dir / DOCUMENT_BINDING_FILENAME
    loaded = DocumentRepository.read_session_binding(session_dir)
    assert loaded == binding
    raw_json = json.loads(bound_path.read_text(encoding="utf-8"))
    assert raw_json["docId"] == "a" * 64
