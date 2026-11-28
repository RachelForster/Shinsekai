from __future__ import annotations

from application.chat.dialog_formats import list_dialog_formats
from application.chat.templates import (
    _generate_template_summary,
    _list_templates,
    _load_template_session_payload,
    _load_user_prompt_presets,
    _save_template_session_payload,
    _save_template_summary,
    _save_user_prompt_presets,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
)


def _list_template_rows(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_list_templates(request.state))


def _list_dialog_format_rows(request: ApiRequest) -> JsonResponse:
    query = getattr(request, "query", None)
    query_locale = str(query.get("locale") or "").strip() if isinstance(query, dict) else ""
    cfg_manager = getattr(request.state, "config_manager", None)
    cfg = getattr(cfg_manager, "config", None)
    sys_cfg = getattr(cfg, "system_config", None)
    state_locale = str(getattr(sys_cfg, "ui_language", "") or "").strip()
    locale = query_locale or state_locale or None
    return JsonResponse(list_dialog_formats(locale=locale))


def _load_template_session(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_load_template_session_payload(request.state))


def _save_template(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_template_summary(request.state, request.body))


def _save_template_session(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_template_session_payload(request.state, request.body))


def _generate_template(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_generate_template_summary(request.state, request.body))


def _load_presets(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_load_user_prompt_presets(request.state))


def _save_presets(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_user_prompt_presets(request.state, request.body))


TEMPLATE_ROUTES = (
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/templates/dialog-formats",
        handler=_list_dialog_format_rows,
        body_kind=BodyKind.NONE,
        name="templates.dialog_formats",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/templates",
        handler=_list_template_rows,
        body_kind=BodyKind.NONE,
        name="templates.list",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/templates/presets",
        handler=_load_presets,
        body_kind=BodyKind.NONE,
        name="templates.presets.get",
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
        methods=frozenset({"POST", "PUT"}),
        pattern="/api/templates/presets",
        handler=_save_presets,
        name="templates.presets.save",
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
