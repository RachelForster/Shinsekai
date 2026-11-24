"""Unit tests for shared document reference counting and reclamation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from application.chat.conversation_library import delete_conversation, remember_conversation
from application.documents import reclaim_unreferenced_documents
from core.chat_history.storage import remove_chat_history_storage
from core.document import DocumentRepository, SessionDocumentBinding
from core.storage.layout import StorageLayout


def test_document_reclamation_across_shared_sessions_and_clear_history(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(tmp_path)
    repo = DocumentRepository(layout)
    book = tmp_path / "shared_novel.txt"
    book.write_text("第一章 共读\n\n" + ("夜风吹过长廊，灯影摇曳不止。" * 8), encoding="utf-8")
    manifest = repo.ingest_and_store(book)
    doc_dir = layout.document_dir(manifest.doc_id)
    assert doc_dir.is_dir()

    state = SimpleNamespace(
        project_root_dir=str(tmp_path),
        history_dir=str(layout.chat_history_dir),
        template_dir_path=str(tmp_path / "templates"),
        chat_session={},
        config_manager=SimpleNamespace(get_character_by_name=lambda _n: None),
    )

    sess_a = layout.chat_history_dir / "session_a"
    sess_b = layout.chat_history_dir / "session_b"
    for sess in (sess_a, sess_b):
        (sess / "active.json").parent.mkdir(parents=True, exist_ok=True)
        (sess / "active.json").write_text("[]", encoding="utf-8")
        DocumentRepository.write_session_binding(
            sess,
            SessionDocumentBinding(
                doc_id=manifest.doc_id,
                behavior_id="novel_theater",
                bound_at_ms=100,
                source_filename="shared_novel.txt",
            ),
        )
        remember_conversation(state, sess, {"templateId": "t1", "characters": []})

    from application.chat.conversation_library import list_conversations

    records = {Path(r["historyPath"]).name: r["id"] for r in list_conversations(state)}

    # clear-history must preserve document-binding.json and keep doc_dir alive
    remove_chat_history_storage(sess_a)
    assert (sess_a / "document-binding.json").is_file()
    assert reclaim_unreferenced_documents(layout) == ()
    assert doc_dir.is_dir()
    # Restore cleared empty active.json (matching clear_chat_history persistence)
    (sess_a / "active.json").write_text("[]", encoding="utf-8")

    # Deleting session_a must NOT remove doc_dir because session_b still references it
    delete_conversation(state, records["session_a"])
    assert not sess_a.exists()
    assert doc_dir.is_dir()

    # Deleting session_b drops refcount to 0 and reclaims doc_dir automatically
    delete_conversation(state, records["session_b"])
    assert not sess_b.exists()
    assert not doc_dir.exists()
    assert repo.get_manifest(manifest.doc_id) is None
