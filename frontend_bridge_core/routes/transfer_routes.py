from __future__ import annotations

from pathlib import Path
from typing import Any

from application.diagnostics.logs import _log_snapshot
from application.media.attachments import stage_uploaded_chat_attachments
from application.runtime.state import BridgeState, _jsonify
from frontend_bridge_core.characters import _as_character_config
from frontend_bridge_core.chat_themes import install_theme_from_zip
from frontend_bridge_core.effects import _effect_dir, _validate_effect_storage_name
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
from sdk.path_utils import safe_child_path, safe_filename, safe_project_path


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


def _safe_export_output_path(name: str, suffix: str) -> tuple[Path, str]:
    project_root = Path.cwd().resolve(strict=False)
    output_root = safe_project_path("output", root=project_root)
    output_root.mkdir(parents=True, exist_ok=True)
    output = safe_child_path(output_root, safe_filename(f"{name}{suffix}"))
    return output, output.relative_to(project_root).as_posix()


def _export_response(output_relative: str) -> JsonResponse:
    return JsonResponse(
        {
            "downloadUrl": f"/api/download?path={output_relative}",
            "path": output_relative,
        }
    )


def _import_characters(state: BridgeState, paths: list[str]) -> list[dict[str, Any]]:
    import tools.file_util as file_util

    imported = []
    for item in paths:
        imported.extend(file_util.import_character(str(item)))
    state.config_manager.reload()
    return [item.__dict__ for item in imported]


def _import_characters_from_paths(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_import_characters(request.state, _request_paths(request)))


def _import_uploaded_characters(request: ApiRequest) -> JsonResponse:
    uploads = _uploads(request)
    return JsonResponse(
        _import_characters(request.state, [str(path) for path in uploads.paths])
    )


def _export_character(request: ApiRequest) -> JsonResponse:
    name = str(request.body.get("name") or "")
    character = request.state.config_manager.get_character_by_name(name)
    if character is None:
        raise KeyError(f"character not found: {name}")
    output, output_relative = _safe_export_output_path(name, ".char")
    import tools.file_util as file_util

    file_util.export_character(
        [_as_character_config(character)],
        output.as_posix(),
        open_folder=False,
    )
    return _export_response(output_relative)


def _import_backgrounds(state: BridgeState, paths: list[str]) -> list[dict[str, Any]]:
    import tools.file_util as file_util

    existing = state.config_manager.config.background_list
    imported = []
    for item in paths:
        batch = file_util.import_background(str(item), existing)
        imported.extend(batch)
        for background in batch:
            if background not in existing:
                existing.append(background)
    state.config_manager.save_background_config()
    state.config_manager.reload()
    return [_jsonify(item) for item in imported]


def _import_backgrounds_from_paths(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_import_backgrounds(request.state, _request_paths(request)))


def _import_uploaded_backgrounds(request: ApiRequest) -> JsonResponse:
    uploads = _uploads(request)
    return JsonResponse(
        _import_backgrounds(request.state, [str(path) for path in uploads.paths])
    )


def _export_background(request: ApiRequest) -> JsonResponse:
    name = str(request.body.get("name") or "")
    background = request.state.config_manager.get_background_by_name(name)
    if background is None:
        raise KeyError(f"background not found: {name}")
    output, output_relative = _safe_export_output_path(name, ".bg")
    import tools.file_util as file_util

    file_util.export_background([background], output.as_posix(), open_folder=False)
    return _export_response(output_relative)


def _import_effects(state: BridgeState, paths: list[str]) -> list[dict[str, Any]]:
    import tools.file_util as file_util

    existing = state.config_manager.config.effect_list
    imported = []
    for item in paths:
        batch = file_util.import_effect(str(item), existing)
        imported.extend(batch)
        for effect in batch:
            if effect not in existing:
                existing.append(effect)
            effect_dir = _effect_dir(effect.name)
            effect_dir.mkdir(parents=True, exist_ok=True)
    state.config_manager.save_effect_config()
    state.config_manager.reload()
    return [_jsonify(item) for item in imported]


def _import_effects_from_paths(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_import_effects(request.state, _request_paths(request)))


def _import_uploaded_effects(request: ApiRequest) -> JsonResponse:
    uploads = _uploads(request)
    return JsonResponse(
        _import_effects(request.state, [str(path) for path in uploads.paths])
    )


def _export_effect(request: ApiRequest) -> JsonResponse:
    name = _validate_effect_storage_name(str(request.body.get("name") or ""))
    effect = request.state.config_manager.get_effect_by_name(name)
    if effect is None:
        raise KeyError(f"effect not found: {name}")
    output, output_relative = _safe_export_output_path(name, ".ef")
    import tools.file_util as file_util

    file_util.export_effect([effect], output.as_posix(), open_folder=False)
    return _export_response(output_relative)


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
