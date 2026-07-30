from __future__ import annotations

from frontend_bridge_core.effects import (
    _delete_all_effect_audio,
    _delete_effect,
    _delete_effect_audio,
    _save_effect,
    _save_effect_audio_tags,
    _upload_effect_audio,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
)


def _list_effects(request: ApiRequest) -> JsonResponse:
    return JsonResponse(request.state.config_manager.config.effect_list)


def _upload_effect_audio_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_upload_effect_audio(request.state, request.body))


def _delete_effect_audio_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_delete_effect_audio(request.state, request.body))


def _delete_all_effect_audio_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_delete_all_effect_audio(request.state, request.body))


def _save_effect_audio_tags_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_effect_audio_tags(request.state, request.body))


def _save_effect_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_effect(request.state, request.body))


def _delete_effect_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_delete_effect(request.state, request.params["name"]))


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
