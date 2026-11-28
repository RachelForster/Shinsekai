"""Runtime worker, turn admission, and OpenCC resolution helpers for SessionBehavior."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import copy
import logging
from pathlib import Path
import sqlite3
from typing import Any

from application.chat.capabilities.contracts import (
    BaseTurnContextProvider,
    TurnAdmissionDecision,
    TurnAdmissionRequest,
)
from application.session_behavior.casting import CastingMap
from core.chat_history.behavior_state_store import BehaviorStateStore
from core.chat_history.storage import chat_history_session_dir, open_session_store
from sdk.exception.types import AppError

logger = logging.getLogger(__name__)


def resolve_ui_worker(runtime_components: Any, app_runtime: Any) -> Any | None:
    """Resolve the active PresentationWorker across runtime components and AppRuntime."""
    ui_worker = getattr(runtime_components, "ui_worker", None)
    if ui_worker is not None:
        return ui_worker
    workflow = getattr(runtime_components, "workflow", None)
    if workflow is not None:
        try:
            from application.runtime.workflow import get_chat_workflow_handles

            handles = get_chat_workflow_handles(workflow)
            if getattr(handles, "ui_worker", None) is not None:
                return handles.ui_worker
        except Exception:
            pass
    if app_runtime is not None:
        return getattr(app_runtime, "ui_worker", None)
    return None


def resolve_character_media_handler(
    runtime_components: Any,
    app_runtime: Any,
) -> Any | None:
    """Locate CharacterMediaHandler across runtime worker handles and AppRuntime."""
    candidates: list[Any] = []
    direct = getattr(runtime_components, "dialog_media_worker", None)
    if direct is not None:
        candidates.append(direct)

    workflow = getattr(runtime_components, "workflow", None)
    if workflow is not None:
        try:
            from application.runtime.workflow import get_chat_workflow_handles

            handles = get_chat_workflow_handles(workflow)
            if getattr(handles, "dialog_media_worker", None) is not None:
                candidates.append(handles.dialog_media_worker)
        except Exception:
            pass

    if app_runtime is not None:
        for attr in ("dialog_media_worker", "tts_worker"):
            worker = getattr(app_runtime, attr, None)
            if worker is not None:
                candidates.append(worker)

    for worker in candidates:
        dispatcher = getattr(worker, "dialog_media_dispatcher", None) or getattr(
            worker, "handler_chain", None
        )
        if dispatcher is None:
            continue
        handlers = getattr(dispatcher, "handlers", None)
        if not handlers:
            handlers = getattr(dispatcher, "_handlers", ())
        for handler in handlers or ():
            if hasattr(handler, "casting_map_provider"):
                return handler
    return None


def resolve_opencc(runtime_components: Any, app_runtime: Any) -> Any | None:
    """Resolve the active OpenCC instance used for presentation alias matching."""
    cc = getattr(runtime_components, "opencc", None)
    if cc is not None:
        return cc
    cc = getattr(app_runtime, "opencc", None) if app_runtime is not None else None
    if cc is not None:
        return cc
    try:
        from application.runtime.context import try_get_app_runtime

        rt = try_get_app_runtime()
        return getattr(rt, "opencc", None) if rt is not None else None
    except Exception:
        return None


class BehaviorTurnContextProvider(BaseTurnContextProvider):
    """Enforce active SessionBehavior free-text policy at LLMWorker admission."""

    capability_id = "session_behavior"

    def __init__(self, capability: Any) -> None:
        self._capability = capability

    def admit_turn(
        self,
        request: TurnAdmissionRequest,
    ) -> TurnAdmissionDecision | None:
        source = str(request.source or "user").strip() or "user"
        if source == "user" and not self._capability.is_free_text_allowed():
            return TurnAdmissionDecision(admitted=False, record_user_message=False)
        return None


def sync_casting_media_policy(
    llm_manager: Any | None,
    casting: CastingMap | None,
    *,
    media_handler: Any | None,
    opencc_provider: Callable[[], Any | None],
    active_casting_provider: Callable[[], CastingMap | None],
) -> None:
    """Propagate active casting rules to LLMManager and CharacterMediaHandler."""
    if llm_manager is not None and hasattr(llm_manager, "set_speaker_media_policy"):
        if casting is not None:
            def _speaker_requires_media(
                speaker_name: str,
                _casting: CastingMap = casting,
            ) -> bool:
                return _casting.speaker_requires_media(speaker_name, cc=opencc_provider())

            llm_manager.set_speaker_media_policy(
                _speaker_requires_media,
                casting.bound_speaker_names(),
            )
        else:
            llm_manager.set_speaker_media_policy(None, ())
    if media_handler is not None and hasattr(media_handler, "casting_map_provider"):
        media_handler.casting_map_provider = (
            active_casting_provider if casting is not None else None
        )


def auto_attach_bound_behavior(capability: Any, context: Any) -> bool:
    """Attach plugin or persisted host SessionBehavior bound to the session."""
    if getattr(capability, "behavior", None) is not None:
        return True
    try:
        from application.session_behavior.plugin_attachment import (
            try_attach_plugin_behavior,
        )

        if try_attach_plugin_behavior(
            capability,
            args=getattr(context, "args", None),
            config=getattr(context, "config", None),
            startup=getattr(context, "startup", None),
            runtime_components=getattr(context, "runtime", None),
            app_runtime=getattr(context, "app_runtime", None),
        ):
            return True
    except AppError:
        raise
    except Exception:
        logger.warning("Failed to auto-attach plugin session behavior", exc_info=True)
    try:
        from application.novel_theater.bootstrap import attach_novel_theater_if_bound

        return bool(attach_novel_theater_if_bound(capability, context))
    except AppError:
        raise
    except Exception:
        logger.warning("Failed to auto-attach bound session behavior", exc_info=True)
        return False


def notify_behavior_session_ready(capability: Any) -> None:
    """Notify bound SessionBehavior when streaming/session startup completes."""
    if getattr(capability, "behavior", None) is None:
        return
    try:
        from application.novel_theater.bootstrap import kickoff_novel_theater_if_fresh

        kickoff_novel_theater_if_fresh(capability)
    except Exception:
        logger.warning("Failed to run SessionBehavior on_session_ready hook", exc_info=True)
    try:
        from application.session_behavior.plugin_attachment import (
            dispatch_behavior_session_ready,
        )

        dispatch_behavior_session_ready(capability)
    except AppError:
        raise
    except Exception:
        logger.warning(
            "Failed to dispatch plugin SessionBehavior on_session_ready",
            exc_info=True,
        )


def after_behavior_transition_committed(
    behavior: Any,
    *,
    branch_id: str,
    state_version: int,
    appended_turn_seqs: tuple[int, ...] = (),
) -> None:
    """Trigger post-commit behavior work only after SQLite commit and replace emit."""
    callback = getattr(behavior, "on_transition_committed", None)
    if callable(callback):
        callback(
            branch_id=branch_id,
            state_version=state_version,
            appended_turn_seqs=appended_turn_seqs,
        )


def _reopen_behavior_state_store(
    capability: Any,
    store: Any,
    *,
    branch_id: str,
) -> BehaviorStateStore | None:
    raw_dir = getattr(store, "_session_dir", None)
    history_arg = str(getattr(capability, "_history_argument", "") or "").strip()
    if raw_dir is not None:
        session_dir: Path | None = Path(raw_dir)
    elif history_arg:
        session_dir = chat_history_session_dir(history_arg)
    else:
        session_dir = None
    open_target = history_arg or (session_dir.as_posix() if session_dir is not None else "")
    if not open_target:
        return None
    fresh_session_store = open_session_store(open_target)
    llm_manager = getattr(capability, "_llm_manager", None)
    user_template = str(getattr(llm_manager, "user_template", "") or "")
    if user_template and hasattr(fresh_session_store, "set_system_prompt"):
        try:
            fresh_session_store.set_system_prompt(user_template, branch_id=branch_id)
        except Exception:
            logger.debug("Failed to restore system prompt after history clear", exc_info=True)
    return BehaviorStateStore(fresh_session_store, session_dir)


def handle_behavior_history_mutated(
    capability: Any,
    reason: str,
    *,
    branch_id: str | None = None,
) -> Any | None:
    """Invalidate prefetch and resync or reopen authoritative behavior state after history mutation."""
    if capability._prefetch is not None:
        capability._prefetch.invalidate_all()
    with capability._lock:
        target_branch = branch_id or capability._current_branch()
        capability._idempotency.clear_branch(target_branch)
        behavior = capability._behavior
        store = capability._state_store
        if behavior is None or store is None:
            return None
        restored: Any | None = None
        if reason == "clear":
            behavior.on_state_restored(None)
            fresh_store = _reopen_behavior_state_store(
                capability,
                store,
                branch_id=target_branch,
            )
            if fresh_store is not None:
                build_reset = getattr(behavior, "build_reset_state", None)
                last_state = getattr(capability, "_last_state", None)
                if callable(build_reset):
                    reset_state = build_reset(last_state)
                else:
                    reset_state = copy.deepcopy(
                        getattr(capability, "_initial_state", {}) or {}
                    )
                restored = fresh_store.initialize_state(
                    branch_id=target_branch,
                    behavior_id=behavior.behavior_id,
                    state=reset_state,
                )
                capability._state_store = fresh_store
            else:
                try:
                    restored = store.clear_branch(target_branch, preserve_initial=True)
                except sqlite3.ProgrammingError:
                    capability._behavior = None
                    capability._state_store = None
                    capability._sync_media_policy(None)
                    restored = None
        else:
            try:
                restored = store.get_latest_state(target_branch)
            except sqlite3.ProgrammingError:
                fresh_store = _reopen_behavior_state_store(
                    capability,
                    store,
                    branch_id=target_branch,
                )
                if fresh_store is not None:
                    capability._state_store = fresh_store
                    restored = fresh_store.get_latest_state(target_branch)
        behavior.on_state_restored(restored)
        capability._sync_media_policy(restored.state if restored is not None else None)
        envelope = (
            behavior.describe_state(restored.state, restored.state_version)
            if restored is not None
            else None
        )
    capability._emit_replace(envelope)
    return envelope


__all__ = [
    "BehaviorTurnContextProvider",
    "after_behavior_transition_committed",
    "auto_attach_bound_behavior",
    "handle_behavior_history_mutated",
    "notify_behavior_session_ready",
    "resolve_character_media_handler",
    "resolve_opencc",
    "resolve_ui_worker",
    "sync_casting_media_policy",
]
