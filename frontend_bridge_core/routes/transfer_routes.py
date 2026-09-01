from __future__ import annotations

from typing import Any

from application.backgrounds import BackgroundOperation
from application.characters import CharacterOperation
from application.diagnostics.logs import _log_snapshot
from application.effects import EffectOperation
from application.media.attachments import stage_uploaded_chat_attachments
from application.runtime.state import BridgeState
from frontend_bridge_core.backgrounds import (
    _execute_background_request,
    background_response_payload,
)
from frontend_bridge_core.characters import (
    _execute_character_request,
    character_response_payload,
)
from frontend_bridge_core.chat_themes import install_theme_from_zip
from frontend_bridge_core.effects import (
    effect_response_payload,
    effect_use_case,
    parse_effect_request,
)
from frontend_bridge_core.memory import (
    _preview_character_memory_import,
    _run_character_memory_import,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
    TaskResponse,
)
from frontend_bridge_core.routes.uploads import UploadedFiles


def _uploads(request: ApiRequest) -> UploadedFiles:
    if request.uploads is None:
        raise RuntimeError(
            f"multipart route did not receive uploaded files: {request.path}"
        )
    return request.uploads


def _request_paths(request: ApiRequest) -> list[str]:
    paths = request.body.get("paths") or []
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    return [str(item) for item in paths]


def _import_characters(
    state: BridgeState,
    paths: list[Any],
    *,
    extra_file_access_roots: tuple[Any, ...] = (),
) -> Any:
    return _execute_character_request(
        state,
        CharacterOperation.IMPORT,
        {"paths": paths},
        extra_file_access_roots=extra_file_access_roots,
    )


def _import_characters_from_paths(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_import_characters(request.state, _request_paths(request)))


def _import_uploaded_characters(request: ApiRequest) -> JsonResponse:
    uploads = _uploads(request)
    return JsonResponse(
        _import_characters(
            request.state,
            list(uploads.paths),
            extra_file_access_roots=(uploads.root,),
        )
    )


def _export_character(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        character_response_payload(
            _execute_character_request(
                request.state,
                CharacterOperation.EXPORT,
                request.body,
            )
        )
    )


def _import_backgrounds(
    state: BridgeState,
    paths: list[Any],
    *,
    extra_file_access_roots: tuple[Any, ...] = (),
) -> Any:
    return _execute_background_request(
        state,
        BackgroundOperation.IMPORT,
        {"paths": paths},
        extra_file_access_roots=extra_file_access_roots,
    )


def _import_backgrounds_from_paths(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_import_backgrounds(request.state, _request_paths(request)))


def _import_uploaded_backgrounds(request: ApiRequest) -> JsonResponse:
    uploads = _uploads(request)
    return JsonResponse(
        _import_backgrounds(
            request.state,
            list(uploads.paths),
            extra_file_access_roots=(uploads.root,),
        )
    )


def _export_background(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        background_response_payload(
            _execute_background_request(
                request.state,
                BackgroundOperation.EXPORT,
                request.body,
            )
        )
    )


def _execute_effect(
    state: BridgeState,
    operation: EffectOperation,
    body: dict[str, Any],
    *,
    additional_file_roots: tuple[str, ...] = (),
) -> Any:
    parsed = parse_effect_request(operation, body)
    result = effect_use_case(
        state,
        additional_file_roots=additional_file_roots,
    ).execute(parsed)
    return effect_response_payload(result)


def _import_effects(
    state: BridgeState,
    paths: list[Any],
    *,
    additional_file_roots: tuple[str, ...] = (),
) -> Any:
    return _execute_effect(
        state,
        EffectOperation.IMPORT,
        {"paths": [str(path) for path in paths]},
        additional_file_roots=additional_file_roots,
    )


def _import_effects_from_paths(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_import_effects(request.state, _request_paths(request)))


def _import_uploaded_effects(request: ApiRequest) -> JsonResponse:
    uploads = _uploads(request)
    return JsonResponse(
        _import_effects(
            request.state,
            list(uploads.paths),
            additional_file_roots=(str(uploads.root),),
        )
    )


def _export_effect(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_effect(
            request.state,
            EffectOperation.EXPORT,
            request.body,
        )
    )


def _preview_uploaded_character_memories(request: ApiRequest) -> JsonResponse:
    uploads = _uploads(request)
    name = str((request.query.get("name") or [""])[0])
    return JsonResponse(
        _preview_character_memory_import(
            request.state,
            name,
            uploads.paths,
            source_root=uploads.root,
        )
    )


def _import_uploaded_character_memories(request: ApiRequest) -> TaskResponse:
    uploads = _uploads(request)
    name = str((request.query.get("name") or [""])[0]).strip()
    return TaskResponse(
        kind="memory-import",
        title=f"导入 {name or '角色'} 的长期记忆",
        message="长期记忆导入任务已排队。",
        worker=lambda task_id: _run_character_memory_import(
            request.state,
            task_id,
            name,
            uploads.paths,
            source_root=uploads.root,
        ),
    )


def _import_uploaded_log(request: ApiRequest) -> JsonResponse:
    uploads = _uploads(request)
    return JsonResponse(_log_snapshot(uploads.paths[0], roots=(uploads.root,)))


def _upload_chat_theme(request: ApiRequest) -> JsonResponse:
    uploads = _uploads(request)
    if not uploads.paths:
        raise ValueError("未收到主题压缩包")
    return JsonResponse(install_theme_from_zip(request.state, uploads.paths[0]))


def _upload_chat_attachments(request: ApiRequest) -> JsonResponse:
    uploads = _uploads(request)
    return JsonResponse({"attachments": stage_uploaded_chat_attachments(uploads.paths)})


TRANSFER_ROUTES = (
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/import",
        handler=_import_characters_from_paths,
        name="characters.import",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/import-upload",
        handler=_import_uploaded_characters,
        body_kind=BodyKind.MULTIPART,
        name="characters.import_upload",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/export",
        handler=_export_character,
        name="characters.export",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/backgrounds/import",
        handler=_import_backgrounds_from_paths,
        name="backgrounds.import",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/backgrounds/import-upload",
        handler=_import_uploaded_backgrounds,
        body_kind=BodyKind.MULTIPART,
        name="backgrounds.import_upload",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/backgrounds/export",
        handler=_export_background,
        name="backgrounds.export",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/effects/import",
        handler=_import_effects_from_paths,
        name="effects.import",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/effects/import-upload",
        handler=_import_uploaded_effects,
        body_kind=BodyKind.MULTIPART,
        name="effects.import_upload",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/effects/export",
        handler=_export_effect,
        name="effects.export",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/memories/import-preview-upload",
        handler=_preview_uploaded_character_memories,
        body_kind=BodyKind.MULTIPART,
        name="characters.memories.import_preview_upload",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/memories/import-upload",
        handler=_import_uploaded_character_memories,
        body_kind=BodyKind.MULTIPART,
        name="characters.memories.import_upload",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/logs/import-upload",
        handler=_import_uploaded_log,
        body_kind=BodyKind.MULTIPART,
        name="logs.import_upload",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/chat/themes/upload",
        handler=_upload_chat_theme,
        body_kind=BodyKind.MULTIPART,
        name="chat.themes.upload",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/chat/attachments/upload",
        handler=_upload_chat_attachments,
        body_kind=BodyKind.MULTIPART,
        name="chat.attachments.upload",
    ),
)
