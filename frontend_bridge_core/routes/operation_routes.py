from __future__ import annotations

from application.model_assets.tts_bundle import _download_tts_bundle
from application.runtime.dependencies import install_runtime_dependency
from frontend_bridge_core.mcp import (
    _mcp_config_response,
    _open_mcp_config_file,
    _preview_mcp_tools_from_payload,
    _save_and_apply_mcp_config,
)
from frontend_bridge_core.music import (
    _music_cover_search,
    _run_music_cover,
    _save_music_cover_config,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
    TaskResponse,
)
from frontend_bridge_core.tools import (
    _crop_sprites,
    _generate_sprite_prompts,
    _generate_sprites,
    _remove_sprite_background,
)


def _music_search(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_music_cover_search(request.state, request.body))


def _music_config(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_save_music_cover_config(request.state, request.body))


def _music_run(request: ApiRequest) -> TaskResponse:
    return TaskResponse(
        kind="music-cover",
        title="音乐翻唱流水线",
        message="音乐翻唱流水线已排队。",
        worker=lambda task_id: _run_music_cover(
            request.state,
            task_id,
            request.body,
        ),
    )


def _download_tts_bundle_route(request: ApiRequest) -> TaskResponse:
    return TaskResponse(
        kind="tts-bundle",
        title="TTS 整合包下载",
        message="TTS 整合包下载已排队。",
        worker=lambda task_id: _download_tts_bundle(
            request.state,
            task_id,
            request.body,
        ),
    )


def _generate_prompts(request: ApiRequest) -> TaskResponse:
    return TaskResponse(
        kind="tools-prompts",
        title="生成立绘提示词",
        message="立绘提示词生成任务已排队。",
        worker=lambda task_id: _generate_sprite_prompts(
            request.state,
            task_id,
            request.body,
        ),
    )


def _generate_sprite_batch(request: ApiRequest) -> TaskResponse:
    return TaskResponse(
        kind="tools-sprites",
        title="批量生成立绘",
        message="立绘批量生成任务已排队。",
        worker=lambda task_id: _generate_sprites(
            request.state,
            task_id,
            request.body,
        ),
    )


def _crop_sprite_batch(request: ApiRequest) -> TaskResponse:
    return TaskResponse(
        kind="tools-crop",
        title="批量裁剪立绘",
        message="立绘裁剪任务已排队。",
        worker=lambda task_id: _crop_sprites(
            request.state,
            task_id,
            request.body,
        ),
    )


def _remove_sprite_backgrounds(request: ApiRequest) -> TaskResponse:
    return TaskResponse(
        kind="tools-rmbg",
        title="批量抠出立绘",
        message="立绘抠图任务已排队。",
        worker=lambda task_id: _remove_sprite_background(
            request.state,
            task_id,
            request.body,
        ),
    )


def _get_mcp_config(_request: ApiRequest) -> JsonResponse:
    return JsonResponse(_mcp_config_response())


def _open_mcp_config(_request: ApiRequest) -> JsonResponse:
    return JsonResponse(_open_mcp_config_file())


def _apply_mcp_config(request: ApiRequest) -> TaskResponse:
    return TaskResponse(
        kind="mcp-apply",
        title="保存并应用 MCP 配置",
        message="MCP 保存应用任务已排队。",
        worker=lambda task_id: _save_and_apply_mcp_config(
            request.state,
            task_id,
            request.body,
        ),
    )


def _preview_mcp_tools(request: ApiRequest) -> TaskResponse:
    return TaskResponse(
        kind="mcp-preview",
        title="刷新 MCP 工具列表",
        message="MCP 工具预览任务已排队。",
        worker=lambda task_id: _preview_mcp_tools_from_payload(
            request.state,
            task_id,
            request.body,
        ),
    )


def _install_missing_dependency(request: ApiRequest) -> TaskResponse:
    module_name = str(request.body.get("moduleName") or "").strip()
    if not module_name:
        raise ValueError("moduleName is required")
    return TaskResponse(
        kind="runtime-dependency-install",
        title=f"Install {module_name}",
        message=f"Installing dependency for {module_name}",
        task_updates={
            "source": module_name,
            "phase": "pip",
            "progress": 0,
        },
        worker=lambda task_id: install_runtime_dependency(
            module_name,
            _task_id=task_id,
            _state=request.state,
        ),
    )


OPERATION_ROUTES = (
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/music-cover/search",
        handler=_music_search,
        name="music_cover.search",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/music-cover/config",
        handler=_music_config,
        name="music_cover.config.save",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/music-cover/run",
        handler=_music_run,
        name="music_cover.run",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/config/tts-bundle/download",
        handler=_download_tts_bundle_route,
        name="config.tts_bundle.download",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/tools/sprite-prompts",
        handler=_generate_prompts,
        name="tools.sprite_prompts",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/tools/sprites/generate",
        handler=_generate_sprite_batch,
        name="tools.sprites.generate",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/tools/sprites/crop",
        handler=_crop_sprite_batch,
        name="tools.sprites.crop",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/tools/sprites/remove-background",
        handler=_remove_sprite_backgrounds,
        name="tools.sprites.remove_background",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/mcp/config",
        handler=_get_mcp_config,
        body_kind=BodyKind.NONE,
        name="mcp.config.get",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/mcp/config/open",
        handler=_open_mcp_config,
        name="mcp.config.open",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/mcp/config/apply",
        handler=_apply_mcp_config,
        name="mcp.config.apply",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/mcp/preview",
        handler=_preview_mcp_tools,
        name="mcp.preview",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/runtime/install-missing-dependency",
        handler=_install_missing_dependency,
        name="runtime.install_missing_dependency",
    ),
)
