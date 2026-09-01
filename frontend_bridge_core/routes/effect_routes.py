from __future__ import annotations

from application.effects import EffectOperation
from frontend_bridge_core.effects import (
    effect_response_payload,
    effect_use_case,
    parse_effect_request,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
)


def _list_effects(request: ApiRequest) -> JsonResponse:
    return JsonResponse(request.state.config_manager.config.effect_list)


def _execute_effect(
    request: ApiRequest,
    operation: EffectOperation,
    *,
    name: str = "",
) -> JsonResponse:
    parsed = parse_effect_request(operation, request.body, name=name)
    result = effect_use_case(request.state).execute(parsed)
    return JsonResponse(effect_response_payload(result))


def _upload_effect_audio_route(request: ApiRequest) -> JsonResponse:
    return _execute_effect(request, EffectOperation.UPLOAD_AUDIO)


def _delete_effect_audio_route(request: ApiRequest) -> JsonResponse:
    return _execute_effect(request, EffectOperation.DELETE_AUDIO)


def _delete_all_effect_audio_route(request: ApiRequest) -> JsonResponse:
    return _execute_effect(request, EffectOperation.DELETE_ALL_AUDIO)


def _save_effect_audio_tags_route(request: ApiRequest) -> JsonResponse:
    return _execute_effect(request, EffectOperation.SAVE_AUDIO_TAGS)


def _save_effect_route(request: ApiRequest) -> JsonResponse:
    return _execute_effect(request, EffectOperation.SAVE)


def _delete_effect_route(request: ApiRequest) -> JsonResponse:
    return _execute_effect(
        request,
        EffectOperation.DELETE,
        name=request.params["name"],
    )


EFFECT_ROUTES = (
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/effects",
        handler=_list_effects,
        body_kind=BodyKind.NONE,
        name="effects.list",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/effects/audio/upload",
        handler=_upload_effect_audio_route,
        name="effects.audio.upload",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/effects/audio/delete",
        handler=_delete_effect_audio_route,
        name="effects.audio.delete",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/effects/audio/delete-all",
        handler=_delete_all_effect_audio_route,
        name="effects.audio.delete_all",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/effects/audio-tags",
        handler=_save_effect_audio_tags_route,
        name="effects.audio_tags.save",
    ),
    Route(
        methods=frozenset({"POST", "PUT"}),
        pattern="/api/effects",
        handler=_save_effect_route,
        name="effects.save",
    ),
    Route(
        methods=frozenset({"DELETE"}),
        pattern="/api/effects/{name}",
        handler=_delete_effect_route,
        body_kind=BodyKind.NONE,
        name="effects.delete",
    ),
)
