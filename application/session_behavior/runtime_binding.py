"""Runtime worker, turn admission, and OpenCC resolution helpers for SessionBehavior."""

from __future__ import annotations

from typing import Any

from application.chat.capabilities.contracts import (
    BaseTurnContextProvider,
    TurnAdmissionDecision,
    TurnAdmissionRequest,
)


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


__all__ = [
    "BehaviorTurnContextProvider",
    "resolve_character_media_handler",
    "resolve_opencc",
    "resolve_ui_worker",
]
