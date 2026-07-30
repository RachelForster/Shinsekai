from __future__ import annotations

from frontend_bridge_core.characters import (
    _delete_all_character_sprites,
    _delete_character_sprite,
    _delete_sprite_voice,
    _generate_character_setting,
    _save_character,
    _save_character_emotion_tags,
    _save_sprite_scale,
    _save_sprite_voice_text,
    _save_sprite_voice_type,
    _translate_character_fields,
    _upload_character_sprites,
    _upload_sprite_voice,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
)


def _list_characters(request: ApiRequest) -> JsonResponse:
    return JsonResponse(request.state.config_manager.config.characters)


def _save_character_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_character(request.state, request.body))


def _generate_character_setting_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_generate_character_setting(request.state, request.body))


def _translate_character_fields_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_translate_character_fields(request.state, request.body))


def _upload_sprite_voice_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_upload_sprite_voice(request.state, request.body))


def _upload_character_sprites_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_upload_character_sprites(request.state, request.body))


def _save_character_emotion_tags_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_character_emotion_tags(request.state, request.body))


def _delete_character_sprite_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_delete_character_sprite(request.state, request.body))


def _delete_all_character_sprites_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_delete_all_character_sprites(request.state, request.body))


def _save_sprite_scale_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_sprite_scale(request.state, request.body))


def _save_sprite_voice_text_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_sprite_voice_text(request.state, request.body))


def _save_sprite_voice_type_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_sprite_voice_type(request.state, request.body))


def _delete_sprite_voice_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_delete_sprite_voice(request.state, request.body))


def _delete_character_route(request: ApiRequest) -> JsonResponse:
    message, names = request.state.character_manager.delete_character(
        request.params["name"]
    )
    return JsonResponse({"message": message, "names": names})


CHARACTER_ROUTES = (
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/characters",
        handler=_list_characters,
        body_kind=BodyKind.NONE,
        name="characters.list",
    ),
    Route(
        methods=frozenset({"POST", "PUT"}),
        pattern="/api/characters",
        handler=_save_character_route,
        name="characters.save",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/ai-setting",
        handler=_generate_character_setting_route,
        name="characters.ai_setting",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/translate",
        handler=_translate_character_fields_route,
        name="characters.translate",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/sprite-voice/upload",
        handler=_upload_sprite_voice_route,
        name="characters.sprite_voice.upload",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/sprites/upload",
        handler=_upload_character_sprites_route,
        name="characters.sprites.upload",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/emotion-tags",
        handler=_save_character_emotion_tags_route,
        name="characters.emotion_tags.save",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/sprites/delete",
        handler=_delete_character_sprite_route,
        name="characters.sprites.delete",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/sprites/delete-all",
        handler=_delete_all_character_sprites_route,
        name="characters.sprites.delete_all",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/sprite-scale",
        handler=_save_sprite_scale_route,
        name="characters.sprite_scale.save",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/sprite-voice/text",
        handler=_save_sprite_voice_text_route,
        name="characters.sprite_voice.text.save",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/sprite-voice/voice-type",
        handler=_save_sprite_voice_type_route,
        name="characters.sprite_voice.voice_type.save",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/sprite-voice/delete",
        handler=_delete_sprite_voice_route,
        name="characters.sprite_voice.delete",
    ),
    Route(
        methods=frozenset({"DELETE"}),
        pattern="/api/characters/{name}",
        handler=_delete_character_route,
        body_kind=BodyKind.NONE,
        name="characters.delete",
    ),
)
