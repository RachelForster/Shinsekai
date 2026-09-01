from __future__ import annotations

from application.backgrounds import BackgroundOperation
from frontend_bridge_core.backgrounds import (
    _execute_background_request,
    _save_background_bgm_tags,
    _save_background_image_tags,
    _translate_background_fields,
)
from frontend_bridge_core.image_annotations import run_background_image_auto_label
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
    TaskResponse,
)


def _list_backgrounds(request: ApiRequest) -> JsonResponse:
    return JsonResponse(request.state.config_manager.config.background_list)


def _translate_background_fields_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_translate_background_fields(request.state, request.body))


def _upload_background_images_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_background_request(
            request.state,
            BackgroundOperation.UPLOAD_IMAGES,
            request.body,
        )
    )


def _upload_background_bgm_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_background_request(
            request.state,
            BackgroundOperation.UPLOAD_BGM,
            request.body,
        )
    )


def _delete_background_image_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_background_request(
            request.state,
            BackgroundOperation.DELETE_IMAGE,
            request.body,
        )
    )


def _delete_all_background_images_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_background_request(
            request.state,
            BackgroundOperation.DELETE_ALL_IMAGES,
            request.body,
        )
    )


def _delete_background_bgm_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_background_request(
            request.state,
            BackgroundOperation.DELETE_BGM,
            request.body,
        )
    )


def _delete_all_background_bgm_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_background_request(
            request.state,
            BackgroundOperation.DELETE_ALL_BGM,
            request.body,
        )
    )


def _save_background_image_tags_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_background_image_tags(request.state, request.body))


def _save_background_bgm_tags_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_background_bgm_tags(request.state, request.body))


def _save_background_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_background_request(
            request.state,
            BackgroundOperation.SAVE,
            request.body,
        )
    )


def _delete_background_route(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _execute_background_request(
            request.state,
            BackgroundOperation.DELETE,
            {"name": request.params["name"]},
        )
    )


def _auto_label_background_images(request: ApiRequest) -> TaskResponse:
    name = str(request.body.get("name") or "").strip()
    if not name:
        raise ValueError("背景名称不能为空")
    return TaskResponse(
        kind="moondream-background-auto-label",
        title=f"标注 {name} 的背景图片",
        message="Moondream 图片标注任务已排队。",
        worker=lambda task_id: run_background_image_auto_label(
            request.state,
            task_id,
            name,
        ),
    )


BACKGROUND_ROUTES = (
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/backgrounds",
        handler=_list_backgrounds,
        body_kind=BodyKind.NONE,
        name="backgrounds.list",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/backgrounds/translate",
        handler=_translate_background_fields_route,
        name="backgrounds.translate",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/backgrounds/images/upload",
        handler=_upload_background_images_route,
        name="backgrounds.images.upload",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/backgrounds/images/auto-label",
        handler=_auto_label_background_images,
        name="backgrounds.images.auto_label",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/backgrounds/bgm/upload",
        handler=_upload_background_bgm_route,
        name="backgrounds.bgm.upload",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/backgrounds/images/delete",
        handler=_delete_background_image_route,
        name="backgrounds.images.delete",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/backgrounds/images/delete-all",
        handler=_delete_all_background_images_route,
        name="backgrounds.images.delete_all",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/backgrounds/bgm/delete",
        handler=_delete_background_bgm_route,
        name="backgrounds.bgm.delete",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/backgrounds/bgm/delete-all",
        handler=_delete_all_background_bgm_route,
        name="backgrounds.bgm.delete_all",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/backgrounds/tags",
        handler=_save_background_image_tags_route,
        name="backgrounds.tags.save",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/backgrounds/bgm-tags",
        handler=_save_background_bgm_tags_route,
        name="backgrounds.bgm_tags.save",
    ),
    Route(
        methods=frozenset({"POST", "PUT"}),
        pattern="/api/backgrounds",
        handler=_save_background_route,
        name="backgrounds.save",
    ),
    Route(
        methods=frozenset({"DELETE"}),
        pattern="/api/backgrounds/{name}",
        handler=_delete_background_route,
        body_kind=BodyKind.NONE,
        name="backgrounds.delete",
    ),
)
