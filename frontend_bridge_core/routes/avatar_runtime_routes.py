from pathlib import Path

from application.media.avatar_runtime import AvatarRuntimeService
from frontend_bridge_core.routes.router import ApiRequest, JsonResponse, Route, TaskResponse
from frontend_bridge_core.tools import _local_file_access_roots


def runtime_service(state):
    return AvatarRuntimeService(Path(state.project_root_dir), file_access_roots=_local_file_access_roots(state))


def _status(request: ApiRequest):
    return JsonResponse(runtime_service(request.state).status(request.params["format"]))


def _prepare(request: ApiRequest):
    body = dict(request.body)
    return TaskResponse(kind="avatar-runtime-prepare", title="Validate avatar SDK", message="Validating SDK ZIP",
                        worker=lambda _: runtime_service(request.state).prepare(request.params["format"], body))


def _install(request: ApiRequest):
    body = dict(request.body)
    return TaskResponse(kind="avatar-runtime-install", title="Install avatar SDK", message="Installing SDK",
                        worker=lambda _: runtime_service(request.state).install(request.params["format"], body))


AVATAR_RUNTIME_ROUTES = (
    Route(frozenset({"POST"}), "/api/avatar/runtime/{format}/status", _status, name="avatar_runtime.status"),
    Route(frozenset({"POST"}), "/api/avatar/runtime/{format}/prepare", _prepare, name="avatar_runtime.prepare"),
    Route(frozenset({"POST"}), "/api/avatar/runtime/{format}/install", _install, name="avatar_runtime.install"),
)
