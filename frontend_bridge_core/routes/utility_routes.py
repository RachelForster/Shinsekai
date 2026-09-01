from __future__ import annotations

from pathlib import Path

from application.diagnostics.logs import (
    _default_log_snapshot,
    _diagnostic_bundle,
    _log_file_list,
    _log_snapshot,
)
from frontend_bridge_core.routes.file_transport import (
    media_thumbnail_batch_response,
    resolve_project_path,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
)
from frontend_bridge_core.tools import _browse_local_files


def _default_logs(_request: ApiRequest) -> JsonResponse:
    return JsonResponse(_default_log_snapshot(Path.cwd().resolve()))


def _list_logs(_request: ApiRequest) -> JsonResponse:
    return JsonResponse(_log_file_list(Path.cwd().resolve()))


def _browse_files(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_browse_local_files(request.state, request.body))


def _media_thumbnails(request: ApiRequest) -> JsonResponse:
    return JsonResponse(media_thumbnail_batch_response(request.body))


def _read_log(request: ApiRequest) -> JsonResponse:
    project_root = Path.cwd().resolve()
    return JsonResponse(
        _log_snapshot(
            resolve_project_path(str(request.body.get("path") or "")),
            roots=(project_root,),
        )
    )


def _create_diagnostic_bundle(_request: ApiRequest) -> JsonResponse:
    return JsonResponse(_diagnostic_bundle(Path.cwd().resolve()))


UTILITY_ROUTES = (
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/logs/default",
        handler=_default_logs,
        body_kind=BodyKind.NONE,
        name="logs.default",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/logs",
        handler=_list_logs,
        body_kind=BodyKind.NONE,
        name="logs.list",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/files/browse",
        handler=_browse_files,
        name="files.browse",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/media/thumbnails",
        handler=_media_thumbnails,
        name="media.thumbnails",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/logs/read",
        handler=_read_log,
        name="logs.read",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/logs/diagnostic-bundle",
        handler=_create_diagnostic_bundle,
        name="logs.diagnostic_bundle",
    ),
)
