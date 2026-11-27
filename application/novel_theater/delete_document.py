"""Safely delete unreferenced documents from the shared store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from application.chat.conversation_library import _registered_session_dirs
from application.chat.history.paths import _state_project_root
from application.documents.reclaim_documents import scan_referenced_doc_ids
from core.document import DocumentRepository
from core.storage.layout import StorageLayout
from sdk.exception.types import AppError


def delete_novel_document(state: Any, doc_id: str) -> dict[str, Any]:
    """Delete a stored document if no conversation session references it."""
    clean_id = str(doc_id or "").strip().lower()
    layout = StorageLayout(_state_project_root(state))
    repo = DocumentRepository(layout)
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

    history_root = Path(getattr(state, "history_dir", None) or layout.chat_history_dir)
    referenced = scan_referenced_doc_ids(
        history_root,
        extra_session_dirs=_registered_session_dirs(state),
    )
    if clean_id in referenced:
        raise AppError(
            "novel.document_in_use",
            params={"docId": clean_id},
            fallback_message="Document is still bound by one or more conversations.",
            http_status=409,
        )

    removed = repo.remove_document(clean_id)
    return {"ok": bool(removed), "docId": clean_id}


__all__ = ["delete_novel_document"]
