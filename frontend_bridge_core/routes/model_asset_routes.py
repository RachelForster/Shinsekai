from __future__ import annotations

from application.model_assets.download_model import (
    download_model,
    inspect_model,
    resolve_model_asset,
)
from frontend_bridge_core.model_assets import (
    configured_asr_model,
    find_running_model_download,
    huggingface_token,
    model_download_enqueue_guard,
    model_download_progress,
    parse_model_asset_request,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    JsonResponse,
    Route,
    TaskResponse,
)


def _get_model_asset_status(request: ApiRequest) -> JsonResponse:
    parsed = parse_model_asset_request(request.body)
    return JsonResponse(
        inspect_model(
            parsed,
            configured_asr_model=configured_asr_model(request.state),
        )
    )


def _download_model_asset_route(request: ApiRequest) -> TaskResponse:
    parsed = parse_model_asset_request(request.body)
    spec = resolve_model_asset(
        parsed,
        configured_asr_model=configured_asr_model(request.state),
    )
    return TaskResponse(
        kind="model-download",
        title=spec.title,
        message=f"{spec.title} download queued.",
        task_updates={
            "assetId": spec.asset_id,
            "assetKey": spec.task_key,
            "variant": spec.variant,
        },
        worker=lambda task_id: download_model(
            spec,
            token=huggingface_token(request.state),
            update_task=model_download_progress(request.state, task_id),
        ),
        find_existing=lambda: find_running_model_download(
            request.state,
            spec.task_key,
        ),
        enqueue_guard=model_download_enqueue_guard,
    )


MODEL_ASSET_ROUTES = (
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/model-assets/status",
        handler=_get_model_asset_status,
        name="model_assets.status",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/model-assets/download",
        handler=_download_model_asset_route,
        name="model_assets.download",
    ),
)
