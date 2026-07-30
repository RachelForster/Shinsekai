from __future__ import annotations

from application.chat.templates import (
    _generate_template_summary,
    _list_templates,
    _load_template_session_payload,
    _save_template_session_payload,
    _save_template_summary,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
)


def _list_template_rows(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_list_templates(request.state))


def _load_template_session(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_load_template_session_payload(request.state))


def _save_template(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_template_summary(request.state, request.body))


def _save_template_session(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_template_session_payload(request.state, request.body))


def _generate_template(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_generate_template_summary(request.state, request.body))


TEMPLATE_ROUTES = (
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/templates",
        handler=_list_template_rows,
        body_kind=BodyKind.NONE,
        name="templates.list",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/templates/session",
        handler=_load_template_session,
        body_kind=BodyKind.NONE,
        name="templates.session.get",
    ),
    Route(
        methods=frozenset({"POST", "PUT"}),
        pattern="/api/templates",
        handler=_save_template,
        name="templates.save",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/templates/session",
        handler=_save_template_session,
        name="templates.session.save",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/templates/generate",
        handler=_generate_template,
        name="templates.generate",
    ),
)
