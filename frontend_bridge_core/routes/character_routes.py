from __future__ import annotations

from application.characters import CharacterOperation
from frontend_bridge_core.characters import (
    _ensure_character_briefs,
    _execute_character_request,
    _generate_character_brief,
    _generate_character_setting,
    _save_character_emotion_tags,
    _save_sprite_scale,
    _translate_character_fields,
)
from frontend_bridge_core.image_annotations import run_character_sprite_auto_label
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
    TaskResponse,
)


def _list_characters(request: ApiRequest) -> JsonResponse:
    return JsonResponse(request.state.config_manager.config.characters)


def _save_character_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_character_request(request.state, CharacterOperation.SAVE, request.body)
    )


def _generate_character_setting_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_generate_character_setting(request.state, request.body))


def _generate_character_brief_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_generate_character_brief(request.state, request.body))


def _ensure_character_briefs_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_ensure_character_briefs(request.state, request.body))


def _translate_character_fields_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_translate_character_fields(request.state, request.body))


def _upload_sprite_voice_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_character_request(
            request.state,
            CharacterOperation.UPLOAD_SPRITE_VOICE,
            request.body,
        )
    )


def _upload_character_sprites_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_character_request(
            request.state,
            CharacterOperation.UPLOAD_SPRITES,
            request.body,
        )
    )


def _save_character_emotion_tags_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_character_emotion_tags(request.state, request.body))


def _delete_character_sprite_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_character_request(
            request.state,
            CharacterOperation.DELETE_SPRITE,
            request.body,
        )
    )


def _delete_all_character_sprites_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_character_request(
            request.state,
            CharacterOperation.DELETE_ALL_SPRITES,
            request.body,
        )
    )


def _save_sprite_scale_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_sprite_scale(request.state, request.body))


def _save_sprite_voice_text_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_character_request(
            request.state,
            CharacterOperation.SAVE_SPRITE_VOICE_TEXT,
            request.body,
        )
    )


def _save_sprite_voice_type_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_character_request(
            request.state,
            CharacterOperation.SAVE_SPRITE_VOICE_TYPE,
            request.body,
        )
    )


def _delete_sprite_voice_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_character_request(
            request.state,
            CharacterOperation.DELETE_SPRITE_VOICE,
            request.body,
        )
    )


def _delete_character_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_character_request(
            request.state,
            CharacterOperation.DELETE,
            {"name": request.params["name"]},
        )
    )


def _auto_label_character_sprites(request: ApiRequest) -> TaskResponse:
    name = str(request.body.get("name") or "").strip()
    if not name:
        raise ValueError("角色名称不能为空")
    return TaskResponse(
        kind="moondream-character-auto-label",
        title=f"标注 {name} 的角色立绘",
        message="Moondream 图片标注任务已排队。",
        worker=lambda task_id: run_character_sprite_auto_label(
            request.state,
            task_id,
            name,
        ),
    )


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
        pattern="/api/characters/ai-brief",
        handler=_generate_character_brief_route,
        name="characters.ai_brief",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/ensure-briefs",
        handler=_ensure_character_briefs_route,
        name="characters.ensure_briefs",
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
        pattern="/api/characters/sprites/auto-label",
        handler=_auto_label_character_sprites,
        name="characters.sprites.auto_label",
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
