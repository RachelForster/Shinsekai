"""Unit tests for shared document reference counting and reclamation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from application.chat.conversation_library import (
    delete_conversation,
    list_conversations,
    remember_conversation,
)
from application.documents import reclaim_unreferenced_documents
from application.story import deletion
from core.chat_history.storage import remove_chat_history_storage
from core.document import DocumentRepository, SessionDocumentBinding
from core.storage.layout import StorageLayout
from test.unit.application.story.test_library import selected_story


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


def test_external_registered_history_protects_shared_document_until_deleted(
    tmp_path: Path,
) -> None:
    layout = StorageLayout(tmp_path)
    repo = DocumentRepository(layout)
    book = tmp_path / "external_shared.txt"
    book.write_text("第一章 外部会话\n\n" + ("远方灯塔照亮海岸线。" * 10), encoding="utf-8")
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

    in_root = layout.chat_history_dir / "in_root_chat"
    external_dir = tmp_path / "outside_history_root" / "external_chat"
    for sess in (in_root, external_dir):
        sess.mkdir(parents=True, exist_ok=True)
        (sess / "active.json").write_text("[]", encoding="utf-8")
        DocumentRepository.write_session_binding(
            sess,
            SessionDocumentBinding(
                doc_id=manifest.doc_id,
                behavior_id="novel_theater",
                bound_at_ms=200,
                source_filename="external_shared.txt",
            ),
        )
        remember_conversation(state, sess, {"templateId": "t1", "characters": []})

    by_name = {Path(r["historyPath"]).name: r["id"] for r in list_conversations(state)}

    # Deleting the in-root session must NOT delete the shared doc still bound outside history_dir.
    delete_conversation(state, by_name["in_root_chat"])
    assert not in_root.exists()
    assert doc_dir.is_dir()

    # Deleting the registered external session drops refcount to 0 and reclaims the doc.
    delete_conversation(state, by_name["external_chat"])
    assert not external_dir.exists()
    assert not doc_dir.exists()


def test_delete_story_version_reclaims_document_only_after_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, task, _, _ = selected_story(tmp_path)
    story_path = Path(task["draftPath"])
    state.template_dir_path = tmp_path / "data" / "templates"
    state.chat_session = {}
    monkeypatch.setattr(deletion, "_chat_runtime_status", lambda _state: {"state": "idle"})

    layout = StorageLayout(Path(state.project_root_dir))
    repo = DocumentRepository(layout)
    book = tmp_path / "story_doc.txt"
    book.write_text("第一章 剧本联动\n\n" + ("剧场与文档联合回滚校验。" * 10), encoding="utf-8")
    manifest = repo.ingest_and_store(book)
    doc_dir = layout.document_dir(manifest.doc_id)

    bound_session = Path(state.history_dir) / "story_bound_chat"
    remember_conversation(state, bound_session, {"storyPath": str(story_path)})
    (bound_session / "branches.json").write_text("{}", encoding="utf-8")
    (bound_session / "story-prompt-binding.json").write_text(
        json.dumps({"storyPath": str(story_path)}),
        encoding="utf-8",
    )
    DocumentRepository.write_session_binding(
        bound_session,
        SessionDocumentBinding(
            doc_id=manifest.doc_id,
            behavior_id="novel_theater",
            bound_at_ms=300,
            source_filename="story_doc.txt",
        ),
    )

    orig_unlink = Path.unlink

    def _fail_story_unlink(target: Path, *args, **kwargs) -> None:
        if target == story_path:
            raise PermissionError("story file locked")
        orig_unlink(target, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _fail_story_unlink)
    with pytest.raises(PermissionError, match="locked"):
        deletion.delete_story_version(state, str(story_path))

    # Rollback must restore document-binding.json AND keep data/documents/<doc_id> alive.
    assert (bound_session / "document-binding.json").is_file()
    assert doc_dir.is_dir()

    # Once unlock succeeds, deletion commits and post-commit GC reclaims the unreferenced doc.
    monkeypatch.setattr(Path, "unlink", orig_unlink)
    result = deletion.delete_story_version(state, str(story_path))
    assert result["ok"] is True
    assert not doc_dir.exists()
