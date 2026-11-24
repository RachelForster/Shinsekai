"""Reference-counted garbage collection for content-addressed document stores."""

from __future__ import annotations

from collections.abc import Iterable
import json
import logging
from pathlib import Path

from core.document.repository import DOCUMENT_BINDING_FILENAME, DocumentRepository
from core.storage.layout import StorageLayout

logger = logging.getLogger(__name__)


def read_bound_doc_id(session_dir: str | Path) -> str | None:
    """Read ``docId`` from a session directory's ``document-binding.json`` if valid."""
    target = Path(session_dir) / DOCUMENT_BINDING_FILENAME
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    doc_id = str(payload.get("docId") or "").strip().lower()
    return doc_id or None


def scan_referenced_doc_ids(history_root: str | Path) -> set[str]:
    """Scan all live chat history sessions for referenced ``docId`` entries."""
    root = Path(history_root)
    referenced: set[str] = set()
    if not root.is_dir():
        return referenced
    for binding_path in root.rglob(DOCUMENT_BINDING_FILENAME):
        if not binding_path.is_file():
            continue
        doc_id = read_bound_doc_id(binding_path.parent)
        if doc_id:
            referenced.add(doc_id)
    return referenced


def reclaim_unreferenced_documents(
    layout: StorageLayout,
    *,
    history_root: str | Path | None = None,
    candidate_doc_ids: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Remove unreferenced content-addressed documents safely under whitelist rules."""
    resolved_history = (
        Path(history_root) if history_root is not None else layout.chat_history_dir
    )
    referenced = scan_referenced_doc_ids(resolved_history)
    repo = DocumentRepository(layout)
    if candidate_doc_ids is None:
        candidates = [manifest.doc_id for manifest in repo.list_documents()]
    else:
        candidates = []
        seen: set[str] = set()
        for raw in candidate_doc_ids:
            clean = str(raw or "").strip().lower()
            if clean and clean not in seen:
                seen.add(clean)
                candidates.append(clean)

    reclaimed: list[str] = []
    for doc_id in candidates:
        if doc_id in referenced:
            continue
        try:
            if repo.remove_document(doc_id):
                reclaimed.append(doc_id)
        except Exception:
            logger.warning(
                "Failed to reclaim unreferenced document %s",
                doc_id,
                exc_info=True,
            )
    return tuple(reclaimed)


__all__ = [
    "read_bound_doc_id",
    "reclaim_unreferenced_documents",
    "scan_referenced_doc_ids",
]
