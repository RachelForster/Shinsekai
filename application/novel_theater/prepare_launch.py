"""Casting normalization, launch payload assembly, and live casting updates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Any
import uuid

from ai.llm.template.integrations.localization import resolve_template_locale
from ai.llm.template.session.novel_theater import (
    render_novel_director_prompt,
    render_novel_pure_dialog_system,
)
from application.chat.history.paths import (
    _state_project_root,
    resolve_history_path_for_project,
)
from application.novel_theater.casting import (
    DEFAULT_NOVEL_NAME_MODE,
    NOVEL_NAME_MODE_STORY,
    count_cast_targets,
    effective_cast_display_name,
    normalize_novel_name_mode,
    novel_prompt_character_entries,
)
from application.novel_theater.import_document import build_chapter_toc_entries
from application.session_behavior.casting import CastBinding, CastingMap
from core.chat_history.behavior_state_store import BehaviorStateStore
from core.chat_history.sqlite_session_store import (
    borrow_session_store_for_dir,
    close_session_store_for_dir,
)
from core.chat_history.storage import (
    chat_history_active_path,
    chat_history_session_dir,
    remove_chat_history_storage,
)
from core.document import (
    DOCUMENT_BINDING_FILENAME,
    DocumentRepository,
    SessionDocumentBinding,
)
from core.storage.layout import StorageLayout
from sdk.exception.types import AppError

NOVEL_THEATER_BEHAVIOR_ID = "novel_theater"
_VALID_ROLES = frozenset({"protagonist", "supporting", "antagonist"})


@dataclass(frozen=True, slots=True)
class NovelMaterializationHandle:
    """Tracks newly created Novel Theater session artifacts for failure rollback."""

    session_dir: Path
    created_dir: bool


def resolve_chapter_index_for_chunk(
    chunk_index: int,
    chapters: Sequence[Mapping[str, Any]],
) -> tuple[int, str]:
    """Return 0-based (chapter_index, chapter_title) containing ``chunk_index``."""
    if not chapters:
        return 0, ""
    chosen_idx = 0
    chosen_title = str(chapters[0].get("title") or "")
    for idx, entry in enumerate(chapters):
        start = int(entry.get("startChunkIndex", 0) or 0)
        count = int(entry.get("chunkCount", 0) or 0)
        if count <= 0:
            continue
        if chunk_index >= start:
            chosen_idx = idx
            chosen_title = str(entry.get("title") or "")
        else:
            break
    return chosen_idx, chosen_title


def normalize_cast_bindings(
    raw_bindings: Sequence[Mapping[str, Any]],
    config_manager: Any,
    *,
    name_mode: str = NOVEL_NAME_MODE_STORY,
) -> tuple[CastingMap, list[str], list[dict[str, Any]]]:
    """Validate and convert UI cast rows into ``CastingMap`` and metadata entries."""
    resolved_mode = normalize_novel_name_mode(
        name_mode,
        default=NOVEL_NAME_MODE_STORY,
    )
    entries: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    target_order: list[str] = []

    getter = getattr(config_manager, "get_character_by_name", None)
    for raw in raw_bindings:
        if not isinstance(raw, Mapping):
            continue
        source_name = str(
            raw.get("sourceName") or raw.get("name") or raw.get("source_name") or ""
        ).strip()
        if not source_name:
            continue
        raw_aliases = raw.get("aliases") or ()
        aliases = list(
            dict.fromkeys(
                clean
                for item in (raw_aliases if isinstance(raw_aliases, (list, tuple)) else ())
                if (clean := str(item or "").strip()) and clean != source_name
            )
        )
        role = str(raw.get("role") or "supporting").strip().lower()
        if role not in _VALID_ROLES:
            role = "supporting"
        silhouette = bool(raw.get("silhouetteUntilRevealed", False))
        raw_target = str(
            raw.get("targetCharacter") or raw.get("target_character") or ""
        ).strip()
        canonical_target = ""
        if raw_target:
            char_obj = getter(raw_target) if callable(getter) else None
            if char_obj is None:
                raise AppError(
                    "novel.unknown_target_character",
                    params={"character": raw_target},
                    fallback_message=f"Unknown target character: {raw_target}",
                    http_status=400,
                )
            canonical_target = str(getattr(char_obj, "name", "") or raw_target).strip()
            if canonical_target not in seen_targets:
                seen_targets.add(canonical_target)
                target_order.append(canonical_target)

        entries.append(
            {
                "sourceName": source_name,
                "aliases": aliases,
                "targetCharacter": canonical_target,
                "role": role,
                "silhouetteUntilRevealed": silhouette,
            }
        )

    target_counts = count_cast_targets(entries)
    bindings: list[CastBinding] = []
    for entry in entries:
        canonical_target = entry["targetCharacter"]
        if not canonical_target:
            continue
        source_name = entry["sourceName"]
        display_name = effective_cast_display_name(
            source_name,
            canonical_target,
            name_mode=resolved_mode,
            target_counts=target_counts,
        )
        merged_aliases = tuple(
            dict.fromkeys(
                item
                for item in (source_name, *entry["aliases"])
                if item and item != canonical_target
            )
        )
        bindings.append(
            CastBinding(
                character_name=canonical_target,
                display_name=display_name,
                aliases=merged_aliases,
                role=entry["role"],
                silhouette_until_revealed=bool(entry["silhouetteUntilRevealed"]),
                revealed=not bool(entry["silhouetteUntilRevealed"]),
            )
        )

    return CastingMap(bindings), target_order, entries


def build_novel_system_template(
    state: Any,
    payload: Mapping[str, Any],
) -> str:
    """Build the system dialog-contract template supporting both bound and pure-dialogue modes."""
    config_manager = getattr(state, "config_manager", None)
    characters = list(payload.get("characters") or [])
    if not characters:
        return render_novel_pure_dialog_system(
            locale=resolve_template_locale(config_manager)
        )
    generator = getattr(state, "template_generator", None)
    if generator is None:
        from ai.llm.template_generator import TemplateGenerator

        generator = TemplateGenerator()
    media_mode = (
        "semantic"
        if str(payload.get("mediaSelectionMode") or "").strip().lower() == "semantic"
        else "indexed"
    )
    character_entries = novel_prompt_character_entries(payload, characters)
    content, _ = generator.generate_chat_template(
        characters,
        str(payload.get("backgroundName") or ""),
        bool(payload.get("useEffect", True)),
        False,
        bool(payload.get("useTranslation", True)),
        False,
        False,
        True,
        False,
        media_selection_mode=media_mode,
        include_character_profiles=False,
        character_entries=character_entries,
    )
    return str(content or "")


def _load_validated_novel_inputs(
    state: Any,
    doc_id: str,
    start_chapter_index: int,
) -> tuple[Any, list[dict[str, Any]], int, int, int]:
    layout = StorageLayout(_state_project_root(state))
    repo = DocumentRepository(layout)
    try:
        manifest = repo.get_manifest(doc_id)
    except ValueError as exc:
        raise AppError(
            "novel.document_not_found",
            params={"docId": doc_id},
            fallback_message="Document not found.",
            http_status=404,
        ) from exc
    if manifest is None:
        raise AppError(
            "novel.document_not_found",
            params={"docId": doc_id},
            fallback_message="Document not found.",
            http_status=404,
        )

    chapters = repo.read_chapters(doc_id)
    chunks = repo.read_chunks(doc_id)
    if not chunks:
        raise AppError(
            "novel.document_empty",
            params={"docId": doc_id},
            fallback_message="Document has no playable chunks.",
            http_status=400,
        )
    toc = build_chapter_toc_entries(chapters, chunks)

    if toc and not (0 <= start_chapter_index < len(toc)):
        raise AppError(
            "novel.invalid_chapter",
            params={"chapterIndex": start_chapter_index},
            fallback_message=f"Invalid starting chapter index: {start_chapter_index}",
            http_status=400,
        )
    start_chunk_index = (
        int(toc[start_chapter_index].get("startChunkIndex", 0) or 0)
        if toc
        else 0
    )
    start_chunk_index = max(0, min(start_chunk_index, len(chunks) - 1))
    resolved_chap_idx, _ = resolve_chapter_index_for_chunk(start_chunk_index, toc)
    return manifest, toc, len(chunks), start_chunk_index, resolved_chap_idx


def _resolve_cast_from_payload(
    body: Mapping[str, Any],
    config_manager: Any,
) -> tuple[CastingMap, list[str], list[dict[str, Any]]]:
    name_mode = normalize_novel_name_mode(
        body.get("nameMode"),
        default=NOVEL_NAME_MODE_STORY,
    )
    raw_entries = body.get("castEntries")
    if isinstance(raw_entries, Sequence) and not isinstance(raw_entries, (str, bytes)):
        return normalize_cast_bindings(raw_entries, config_manager, name_mode=name_mode)
    raw_casting = body.get("casting")
    if isinstance(raw_casting, Sequence) and not isinstance(raw_casting, (str, bytes)):
        return normalize_cast_bindings(raw_casting, config_manager, name_mode=name_mode)
    if isinstance(raw_casting, Mapping):
        raw_bindings = raw_casting.get("bindings")
        if isinstance(raw_bindings, Sequence) and not isinstance(raw_bindings, (str, bytes)):
            synthesized = [
                {
                    "sourceName": (
                        item.get("displayName")
                        or item.get("characterName")
                        or item.get("targetCharacter")
                        or ""
                    ),
                    "aliases": list(item.get("aliases") or ()),
                    "targetCharacter": item.get("characterName") or item.get("targetCharacter") or "",
                    "role": item.get("role") or "supporting",
                    "silhouetteUntilRevealed": bool(item.get("silhouetteUntilRevealed", False)),
                }
                for item in raw_bindings
                if isinstance(item, Mapping)
            ]
            return normalize_cast_bindings(synthesized, config_manager, name_mode=name_mode)
    return normalize_cast_bindings((), config_manager, name_mode=name_mode)


def prepare_novel_launch(
    state: Any,
    body: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate document/cast inputs and build a side-effect-free Novel Theater launch payload."""
    doc_id = str(body.get("docId") or "").strip().lower()
    raw_start_chapter = int(body.get("startChapterIndex", 0) or 0)
    manifest, _toc, _total_chunks, _start_chunk, resolved_chap_idx = (
        _load_validated_novel_inputs(state, doc_id, raw_start_chapter)
    )

    config_manager = getattr(state, "config_manager", None)
    name_mode = normalize_novel_name_mode(
        body.get("nameMode"),
        default=DEFAULT_NOVEL_NAME_MODE,
    )
    raw_casting = body.get("casting") or ()
    casting_map, bound_characters, cast_entries = normalize_cast_bindings(
        raw_casting if isinstance(raw_casting, Sequence) else (),
        config_manager,
        name_mode=name_mode,
    )

    layout = StorageLayout(_state_project_root(state))
    raw_history = str(body.get("historyPath") or "").strip()
    history_root = Path(getattr(state, "history_dir", None) or layout.chat_history_dir)
    target_raw = (
        raw_history
        if raw_history
        else (history_root / f"novel-{uuid.uuid4().hex[:12]}").as_posix()
    )
    history_path = resolve_history_path_for_project(state, target_raw)

    locale = resolve_template_locale(config_manager)
    director_scenario = render_novel_director_prompt(
        cast_entries,
        name_mode=name_mode,
        locale=locale,
    )
    media_mode = (
        "semantic"
        if str(body.get("mediaSelectionMode") or "").strip().lower() == "semantic"
        else "indexed"
    )
    background_name = str(body.get("backgroundName") or "").strip()
    custom_title = str(body.get("conversationTitle") or "").strip()[:120]
    conversation_title = custom_title or manifest.title
    return {
        "behaviorId": NOVEL_THEATER_BEHAVIOR_ID,
        "novelDocId": doc_id,
        "startChapterIndex": resolved_chap_idx,
        "nameMode": name_mode,
        "casting": casting_map.to_dict(),
        "castEntries": cast_entries,
        "characters": bound_characters,
        "backgroundName": background_name,
        "mediaSelectionMode": media_mode,
        "useChoice": False,
        "useNarration": True,
        "useStat": False,
        "useEffect": bool(body.get("useEffect", True)),
        "useTranslation": bool(body.get("useTranslation", True)),
        "memoryMode": "isolated",
        "showInitialSprite": False,
        "historyPath": history_path.as_posix(),
        "conversationTitle": conversation_title,
        "templateId": "",
        "templateName": manifest.title,
        "scenario": director_scenario,
        "resetHistory": False,
        "enableMobileAccess": bool(body.get("enableMobileAccess", False)),
    }


def materialize_novel_session_binding(
    state: Any,
    body: Mapping[str, Any],
    history_path: Path | str,
) -> NovelMaterializationHandle | None:
    """Create session binding and initial behavior snapshot when launching a fresh novel session."""
    resolved_history = resolve_history_path_for_project(state, str(history_path))
    session_dir = chat_history_session_dir(resolved_history)
    if DocumentRepository.read_session_binding(session_dir) is not None:
        return None

    doc_id = str(body.get("novelDocId") or body.get("docId") or "").strip().lower()
    raw_start_chapter = int(body.get("startChapterIndex", 0) or 0)
    manifest, toc, total_chunks, start_chunk_index, resolved_chap_idx = (
        _load_validated_novel_inputs(state, doc_id, raw_start_chapter)
    )
    config_manager = getattr(state, "config_manager", None)
    casting_map, _bound_characters, cast_entries = _resolve_cast_from_payload(
        body, config_manager
    )

    existed_before = session_dir.exists()
    handle = NovelMaterializationHandle(session_dir=session_dir, created_dir=not existed_before)
    try:
        session_dir.mkdir(parents=True, exist_ok=True)
        active_file = chat_history_active_path(resolved_history)
        if not active_file.exists():
            active_file.write_text("[]", encoding="utf-8")

        DocumentRepository.write_session_binding(
            session_dir,
            SessionDocumentBinding(
                doc_id=doc_id,
                behavior_id=NOVEL_THEATER_BEHAVIOR_ID,
                bound_at_ms=int(time.time() * 1000),
                source_filename=manifest.source_filename,
            ),
        )

        initial_state = {
            "docId": doc_id,
            "title": manifest.title,
            "chunkIndex": start_chunk_index,
            "chapterIndex": resolved_chap_idx,
            "totalChunks": total_chunks,
            "totalChapters": len(toc),
            "phase": "ready",
            "nameMode": normalize_novel_name_mode(
                body.get("nameMode"),
                default=NOVEL_NAME_MODE_STORY,
            ),
            "casting": casting_map.to_dict(),
            "castEntries": cast_entries,
            "chapters": toc,
            "lastError": "",
        }
        with borrow_session_store_for_dir(session_dir, create_if_dir_exists=True) as store:
            assert store is not None
            BehaviorStateStore(store, session_dir).initialize_state(
                branch_id="main",
                behavior_id=NOVEL_THEATER_BEHAVIOR_ID,
                state=initial_state,
            )
    except BaseException:
        rollback_novel_session_binding(handle)
        raise
    return handle


def rollback_novel_session_binding(handle: NovelMaterializationHandle | None) -> None:
    """Remove freshly created session binding and history artifacts after a failed launch."""
    if handle is None:
        return
    session_dir = handle.session_dir
    close_session_store_for_dir(session_dir)
    try:
        (session_dir / DOCUMENT_BINDING_FILENAME).unlink(missing_ok=True)
    except OSError:
        pass
    remove_chat_history_storage(session_dir)


def save_novel_casting(
    state: Any,
    conversation_id: str,
    raw_bindings: Sequence[Mapping[str, Any]],
    *,
    name_mode: str | None = None,
) -> dict[str, Any]:
    """Delegate to ``application.novel_theater.save_casting.save_novel_casting``."""
    from application.novel_theater.save_casting import (
        save_novel_casting as _save_novel_casting,
    )

    return _save_novel_casting(state, conversation_id, raw_bindings, name_mode=name_mode)


__all__ = [
    "NOVEL_THEATER_BEHAVIOR_ID",
    "NovelMaterializationHandle",
    "build_novel_system_template",
    "materialize_novel_session_binding",
    "normalize_cast_bindings",
    "prepare_novel_launch",
    "resolve_chapter_index_for_chunk",
    "rollback_novel_session_binding",
    "save_novel_casting",
]
