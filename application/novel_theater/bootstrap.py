"""Runtime attachment and fresh-session auto-kickoff for bound Novel Theater sessions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import uuid

from ai.llm.llm_manager import LLMAdapterFactory
from ai.llm.template.integrations.localization import resolve_template_locale
from application.chat.history.paths import _state_project_root
from application.novel_theater.behavior import NovelTheaterBehavior
from application.novel_theater.import_document import build_chapter_toc_entries
from application.novel_theater.prepare_launch import (
    NOVEL_THEATER_BEHAVIOR_ID,
    resolve_chapter_index_for_chunk,
)
from application.novel_theater.save_casting import build_novel_runtime_system_prompt
from application.novel_theater.turn_runner import NovelTheaterTurnRunner
from application.session_behavior.prefetch import SpeculativePrefetchCoordinator
from core.chat_history.behavior_state_models import (
    BehaviorCommitResult,
    BehaviorVersionConflictError,
)
from core.chat_history.behavior_state_store import BehaviorStateStore
from core.chat_history.storage import (
    chat_history_session_dir,
    legacy_active_history_branch,
    open_session_store,
)
from core.document import DocumentRepository
from core.storage.layout import StorageLayout


def _adapter_factory_from_config(config_manager: Any) -> Callable[[], Any]:
    def _create() -> Any:
        get_llm = getattr(config_manager, "get_llm_api_config", None)
        if not callable(get_llm):
            raise RuntimeError("No LLM configuration helper available")
        provider, model, base_url, api_key = get_llm()
        kwargs = config_manager.merged_llm_factory_kwargs(
            provider,
            {
                "llm_provider": provider,
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
            },
        )
        return LLMAdapterFactory.create_adapter(**kwargs)

    return _create


def _resolve_project_root(
    config_manager: Any,
    project_root: Path | str | None = None,
    *,
    session_dir: Path | None = None,
    doc_id: str = "",
) -> Path:
    """Resolve the active project root across explicit hints, env vars, and session ancestry."""
    backend = getattr(config_manager, "active_backend", None)
    for candidate in (
        project_root,
        getattr(config_manager, "project_root_dir", None),
        getattr(config_manager, "project_root", None),
        getattr(config_manager, "base_dir", None),
        getattr(backend, "project_root", None) if backend is not None else None,
        os.environ.get("SHINSEKAI_PROJECT_ROOT", "").strip(),
        os.environ.get("EASYAI_PROJECT_ROOT", "").strip(),
    ):
        if isinstance(candidate, Path):
            return candidate
        if isinstance(candidate, str) and candidate.strip():
            return Path(candidate.strip())
    if session_dir is not None and doc_id:
        for parent in session_dir.resolve(strict=False).parents[:5]:
            try:
                if DocumentRepository(StorageLayout(parent)).get_manifest(doc_id) is not None:
                    return parent
            except (OSError, ValueError):
                continue
    return _state_project_root(config_manager)


def attach_novel_theater_if_bound(
    capability: Any,
    context: Any,
    *,
    project_root: Path | str | None = None,
) -> bool:
    """Attach ``NovelTheaterBehavior`` if ``context.args.history`` is bound to ``novel_theater``."""
    history_arg = str(getattr(getattr(context, "args", None), "history", "") or "").strip()
    if not history_arg:
        return False
    session_dir = chat_history_session_dir(history_arg)
    binding = DocumentRepository.read_session_binding(session_dir)
    if binding is None or binding.behavior_id != NOVEL_THEATER_BEHAVIOR_ID:
        return False

    config_manager = getattr(context, "config", None)
    startup = getattr(context, "startup", None)
    runtime = getattr(context, "runtime", None)
    app_runtime = getattr(context, "app_runtime", None)
    ui_updates = getattr(context, "ui_updates", None) or (
        getattr(app_runtime, "ui_update_manager", None) if app_runtime is not None else None
    )
    chat_turn_service = getattr(context, "chat_turn_service", None) or (
        getattr(app_runtime, "chat_turn_service", None) if app_runtime is not None else None
    )
    llm_manager = getattr(startup, "llm_manager", None) or (
        getattr(app_runtime, "llm_manager", None) if app_runtime is not None else None
    )
    dialog_queue = (
        getattr(runtime, "dialog_queue", None)
        if runtime is not None
        else getattr(app_runtime, "dialog_queue", None)
    )
    presentation_queue = (
        getattr(runtime, "presentation_queue", None)
        if runtime is not None
        else getattr(app_runtime, "presentation_queue", None)
    )

    resolved_root = _resolve_project_root(
        config_manager,
        project_root,
        session_dir=session_dir,
        doc_id=binding.doc_id,
    )
    repo = DocumentRepository(StorageLayout(resolved_root))
    manifest = repo.get_manifest(binding.doc_id)
    if manifest is None:
        return False
    chapters = repo.read_chapters(binding.doc_id)
    chunks = repo.read_chunks(binding.doc_id)
    if not chunks:
        return False
    toc_entries = build_chapter_toc_entries(chapters, chunks)

    locale_fn = lambda: resolve_template_locale(config_manager)
    create_adapter = _adapter_factory_from_config(config_manager)
    prefetch = SpeculativePrefetchCoordinator(
        create_prefetch_adapter=create_adapter,
        locale_provider=locale_fn,
    )

    def _commit_async(
        branch_id: str,
        expected_ver: int,
        next_state: dict[str, Any],
        messages: tuple[dict[str, Any], ...],
    ) -> BehaviorCommitResult | None:
        with capability._lock:
            store = capability._state_store
            behavior = capability._behavior
            if store is None or behavior is None:
                return None
            try:
                result = store.commit_behavior_turn(
                    branch_id=branch_id,
                    behavior_id=behavior.behavior_id,
                    expected_state_version=expected_ver,
                    next_state=next_state,
                    messages=messages,
                )
            except BehaviorVersionConflictError:
                return None
            capability._sync_media_policy(result.snapshot.state)
            envelope = behavior.describe_state(
                result.snapshot.state,
                result.snapshot.state_version,
            )
        capability._emit_replace(envelope)
        return result

    def _get_opencc() -> Any | None:
        return getattr(runtime, "opencc", None) or (
            getattr(app_runtime, "opencc", None) if app_runtime is not None else None
        )

    media_mode = str(
        getattr(getattr(context, "args", None), "media_selection_mode", "indexed")
        or "indexed"
    ).strip()
    turn_runner = NovelTheaterTurnRunner(
        chunks=chunks,
        chapters=chapters,
        toc_entries=toc_entries,
        prefetch=prefetch,
        create_adapter=create_adapter,
        llm_manager=llm_manager,
        dialog_queue=dialog_queue,
        presentation_queue=presentation_queue,
        ui_updates=ui_updates,
        chat_turn_service=chat_turn_service,
        history_path=history_arg,
        media_selection_mode=media_mode,
        locale_provider=locale_fn,
        opencc_provider=_get_opencc,
        commit_async=_commit_async,
    )
    def _rebuild_system_prompt(
        entries: Sequence[Mapping[str, Any]],
        bound_names: Sequence[str],
        name_mode: str = "story",
    ) -> str:
        stub_state = SimpleNamespace(
            config_manager=config_manager,
            project_root_dir=str(resolved_root),
        )
        _, _, runtime_prompt = build_novel_runtime_system_prompt(
            stub_state,
            {
                "castEntries": [dict(item) for item in entries if isinstance(item, Mapping)],
                "characters": list(bound_names),
                "nameMode": name_mode,
                "backgroundName": str(getattr(getattr(context, "args", None), "background", "") or ""),
                "mediaSelectionMode": media_mode,
                "useEffect": False,
                "useTranslation": True,
            },
            locale=locale_fn(),
        )
        return runtime_prompt

    behavior = NovelTheaterBehavior(
        manifest=manifest,
        chapters=chapters,
        chunks=chunks,
        toc_entries=toc_entries,
        turn_runner=turn_runner,
        locale_provider=locale_fn,
        rebuild_system_prompt=_rebuild_system_prompt,
    )

    set_hist = getattr(capability, "set_history_argument", None)
    if callable(set_hist):
        set_hist(history_arg)
    session_store = open_session_store(history_arg)
    state_store = BehaviorStateStore(session_store, session_dir)
    branch = legacy_active_history_branch(history_arg)
    fallback_chap_idx, _ = resolve_chapter_index_for_chunk(0, toc_entries)
    fallback_initial = {
        "docId": binding.doc_id,
        "title": manifest.title,
        "chunkIndex": 0,
        "chapterIndex": fallback_chap_idx,
        "totalChunks": len(chunks),
        "totalChapters": len(toc_entries),
        "phase": "ready",
        "nameMode": "story",
        "casting": {"bindings": []},
        "castEntries": [],
        "chapters": toc_entries,
        "lastError": "",
    }
    capability.attach_behavior(
        behavior,
        state_store=state_store,
        initial_state=fallback_initial,
        branch_id=branch,
    )
    # If the session crashed or exited mid-generation previously, reset generating -> playing/ready.
    latest = state_store.get_latest_state(branch)
    if latest is not None and latest.state.get("phase") == "generating":
        recovered_phase = "ready" if int(latest.state.get("chunkIndex") or 0) == 0 else "playing"
        commit = state_store.commit_behavior_turn(
            branch_id=branch,
            behavior_id=behavior.behavior_id,
            expected_state_version=latest.state_version,
            next_state={**latest.state, "phase": recovered_phase, "lastError": ""},
            messages=(),
        )
        capability._emit_replace(
            behavior.describe_state(commit.snapshot.state, commit.snapshot.state_version)
        )
    return True


def kickoff_novel_theater_if_fresh(capability: Any) -> None:
    """Start chunk 0 automatically once a fresh Novel Theater session becomes ready."""
    behavior = getattr(capability, "behavior", None)
    store = getattr(capability, "state_store", None)
    if behavior is None or store is None:
        return
    if getattr(behavior, "behavior_id", "") != NOVEL_THEATER_BEHAVIOR_ID:
        return
    branch = capability._current_branch()
    latest = store.get_latest_state(branch)
    if latest is None:
        return
    phase = str(latest.state.get("phase") or "")
    if phase == "ready":
        emit = getattr(capability, "_emit_event", None)
        if callable(emit):
            emit({"type": "options.clear"})
        capability.handle_behavior_command(
            {
                "commandId": f"kickoff-{uuid.uuid4().hex}",
                "action": "advance",
                "expectedStateVersion": int(latest.state_version),
                "payload": {"trigger": "session_ready"},
            }
        )


__all__ = [
    "attach_novel_theater_if_bound",
    "kickoff_novel_theater_if_fresh",
]
