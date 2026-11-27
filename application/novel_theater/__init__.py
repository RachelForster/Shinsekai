"""Novel Theater internal application domain built on core/document & SessionBehavior."""

from __future__ import annotations

from application.novel_theater.behavior import (
    NOVEL_THEATER_BEHAVIOR_ID,
    NovelTheaterBehavior,
)
from application.novel_theater.bootstrap import (
    attach_novel_theater_if_bound,
    kickoff_novel_theater_if_fresh,
)
from application.novel_theater.delete_document import delete_novel_document
from application.novel_theater.extract_cast import extract_novel_cast
from application.novel_theater.import_document import (
    build_chapter_toc_entries,
    get_novel_document_detail,
    import_novel_document,
    list_novel_documents,
    serialize_document_detail,
)
from application.novel_theater.prepare_launch import (
    build_novel_system_template,
    materialize_novel_session_binding,
    normalize_cast_bindings,
    prepare_novel_launch,
    rollback_novel_session_binding,
)
from application.novel_theater.save_casting import (
    build_novel_runtime_system_prompt,
    save_novel_casting,
)

__all__ = [
    "NOVEL_THEATER_BEHAVIOR_ID",
    "NovelTheaterBehavior",
    "attach_novel_theater_if_bound",
    "build_chapter_toc_entries",
    "build_novel_runtime_system_prompt",
    "build_novel_system_template",
    "delete_novel_document",
    "extract_novel_cast",
    "get_novel_document_detail",
    "import_novel_document",
    "kickoff_novel_theater_if_fresh",
    "list_novel_documents",
    "materialize_novel_session_binding",
    "normalize_cast_bindings",
    "prepare_novel_launch",
    "rollback_novel_session_binding",
    "save_novel_casting",
    "serialize_document_detail",
]
