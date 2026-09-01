from __future__ import annotations

from http import HTTPStatus

from application.chat.runtime_process import (
    _chat_history,
    _chat_runtime_status,
    _chat_snapshot,
    _chat_theme_payload,
    _handle_chat_command,
)
from application.chat.stop_chat import stop_chat
from frontend_bridge_core.chat_session import (
    launch_chat,
    resume_last_chat,
    start_chat_initialization,
)
from frontend_bridge_core.chat_themes import (
    delete_chat_theme,
    get_active_chat_theme_id,
    get_chat_theme_manifest,
    list_chat_themes,
    save_chat_theme,
    set_active_chat_theme,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
)


def _runtime_status(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_chat_runtime_status(request.state))


def _snapshot(request: ApiRequest) -> JsonResponse:
    renderer_id = str((request.query.get("rendererId") or [""])[0]).strip()[:128]
    return JsonResponse(_chat_snapshot(request.state, renderer_id=renderer_id))


def _history(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_chat_history(request.state))


def _legacy_theme(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_chat_theme_payload(request.state))


def _list_themes(request: ApiRequest) -> JsonResponse:
    return JsonResponse(list_chat_themes(request.state))


def _active_theme(request: ApiRequest) -> JsonResponse:
    return JsonResponse(get_active_chat_theme_id(request.state))


def _theme_manifest(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        get_chat_theme_manifest(request.state, request.params["theme_id"])
    )


def _launch(request: ApiRequest) -> JsonResponse:
    return JsonResponse(launch_chat(request.state, request.body))


def _resume_last(request: ApiRequest) -> JsonResponse:
    return JsonResponse(resume_last_chat(request.state))


def _initialize(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        start_chat_initialization(request.state, request.body),
        HTTPStatus.ACCEPTED,
    )


def _close(request: ApiRequest) -> JsonResponse:
    return JsonResponse(stop_chat(request.state))


def _command(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_handle_chat_command(request.state, request.body))


def _set_active_theme(request: ApiRequest) -> JsonResponse:
    return JsonResponse(set_active_chat_theme(request.state, request.body))


def _save_theme(request: ApiRequest) -> JsonResponse:
    return JsonResponse(save_chat_theme(request.state, request.body))


def _delete_theme(request: ApiRequest) -> JsonResponse:
    return JsonResponse(delete_chat_theme(request.state, request.params["theme_id"]))


CHAT_ROUTES = (
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/chat/runtime-status",
        handler=_runtime_status,
        body_kind=BodyKind.NONE,
        name="chat.runtime_status",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/chat/snapshot",
        handler=_snapshot,
        body_kind=BodyKind.NONE,
        name="chat.snapshot",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/chat/history",
        handler=_history,
        body_kind=BodyKind.NONE,
        name="chat.history",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/chat/theme",
        handler=_legacy_theme,
        body_kind=BodyKind.NONE,
        name="chat.theme.legacy",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/chat/themes",
        handler=_list_themes,
        body_kind=BodyKind.NONE,
        name="chat.themes.list",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/chat/themes/active",
        handler=_active_theme,
        body_kind=BodyKind.NONE,
        name="chat.themes.active",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/chat/themes/{theme_id}",
        handler=_theme_manifest,
        body_kind=BodyKind.NONE,
        name="chat.themes.get",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/chat/launch",
        handler=_launch,
        name="chat.launch",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/chat/resume-last",
        handler=_resume_last,
        name="chat.resume_last",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/chat/init",
        handler=_initialize,
        name="chat.initialize",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/chat/close",
        handler=_close,
        name="chat.close",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/chat/command",
        handler=_command,
        name="chat.command",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/chat/themes/active",
        handler=_set_active_theme,
        name="chat.themes.set_active",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/chat/themes/save",
        handler=_save_theme,
        name="chat.themes.save",
    ),
    Route(
        methods=frozenset({"DELETE"}),
        pattern="/api/chat/themes/{theme_id}",
        handler=_delete_theme,
        body_kind=BodyKind.NONE,
        name="chat.themes.delete",
    ),
)
