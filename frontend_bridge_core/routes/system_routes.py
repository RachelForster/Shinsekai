from __future__ import annotations

from http import HTTPStatus

from application.model_assets.tts_bundle import _tts_bundle_recommendation
from application.runtime.state import plugin_load_snapshot
from application.runtime.tasks import _get_task, _request_task_cancel
from frontend_bridge_core.config import (
    _app_config_response,
    _fetch_llm_models,
    _save_api_config,
    _test_llm_connection,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
)


def _health(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        {
            "ok": True,
            "plugins": plugin_load_snapshot(request.state),
        }
    )


def _get_config(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_app_config_response(request.state))


def _detect_network_proxy(_request: ApiRequest) -> JsonResponse:
    from config.network_proxy import detect_network_proxy_configuration

    return JsonResponse(detect_network_proxy_configuration().as_payload())


def _get_tts_bundle_recommendation(_request: ApiRequest) -> JsonResponse:
    return JsonResponse(_tts_bundle_recommendation())


def _get_task_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_get_task(request.state, request.params["task_id"]))


def _save_api_config_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_api_config(request.state, request.body))


def _save_system_config(request: ApiRequest) -> JsonResponse:
    from config.mirror_env import REGION_AUTO
    from config.schema import SystemConfig

    config = SystemConfig.model_validate(request.body)
    config.mirror_region = REGION_AUTO
    request.state.config_manager.config.system_config = config
    request.state.config_manager.save_system_config()
    try:
        from i18n import init_i18n

        init_i18n(config.ui_language)
    except Exception:
        pass
    return JsonResponse(config)


def _llm_error_response(exc: Exception, *, fallback_message: str) -> JsonResponse:
    from sdk.exception.presenter import format_llm_exception_message

    message = format_llm_exception_message(exc, fallback_message=fallback_message)
    return JsonResponse(
        {"error": message, "type": exc.__class__.__name__},
        HTTPStatus.BAD_REQUEST,
    )


def _fetch_llm_models_route(request: ApiRequest) -> JsonResponse:
    try:
        return JsonResponse(_fetch_llm_models(request.body))
    except Exception as exc:
        return _llm_error_response(exc, fallback_message="获取模型列表失败。")


def _test_llm_connection_route(request: ApiRequest) -> JsonResponse:
    try:
        return JsonResponse(_test_llm_connection(request.body))
    except Exception as exc:
        return _llm_error_response(exc, fallback_message="LLM 连通检测失败。")


def _cancel_task(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_request_task_cancel(request.state, request.params["task_id"]))


SYSTEM_ROUTES = (
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/health",
        handler=_health,
        body_kind=BodyKind.NONE,
        name="health",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/config",
        handler=_get_config,
        body_kind=BodyKind.NONE,
        name="config.get",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/config/network-proxy/detect",
        handler=_detect_network_proxy,
        body_kind=BodyKind.NONE,
        name="config.network_proxy.detect",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/config/tts-bundle/recommendation",
        handler=_get_tts_bundle_recommendation,
        body_kind=BodyKind.NONE,
        name="config.tts_bundle.recommendation",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/tasks/{task_id}",
        handler=_get_task_route,
        body_kind=BodyKind.NONE,
        name="tasks.get",
    ),
    Route(
        methods=frozenset({"POST", "PUT"}),
        pattern="/api/config/api",
        handler=_save_api_config_route,
        name="config.api.save",
    ),
    Route(
        methods=frozenset({"POST", "PUT"}),
        pattern="/api/config/system",
        handler=_save_system_config,
        name="config.system.save",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/config/llm-models",
        handler=_fetch_llm_models_route,
        name="config.llm_models",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/config/llm-connection-test",
        handler=_test_llm_connection_route,
        name="config.llm_connection_test",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/tasks/{task_id}/cancel",
        handler=_cancel_task,
        name="tasks.cancel",
    ),
)
