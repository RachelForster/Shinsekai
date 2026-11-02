from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from frontend_bridge_core.routes.api import FrontendBridgeHandler
from frontend_bridge_core.routes.file_transport import dispatch_file_request
from frontend_bridge_core.routes.router import ApiRequest, TaskResponse


@pytest.mark.parametrize("operation", ["status", "prepare", "install"])
def test_runtime_endpoints_use_control_plane_and_existing_task_transport(monkeypatch, operation):
    service = Mock()
    service.status.return_value = {"installed": False}
    service.prepare.return_value = {"sources": {}}
    service.install.return_value = {"installed": True}
    monkeypatch.setattr("frontend_bridge_core.routes.avatar_runtime_routes.runtime_service", lambda _: service)
    path = f"/api/avatar/runtime/l2d/{operation}"
    matched = FrontendBridgeHandler.api_router.match("POST", path)
    assert matched
    request = ApiRequest(SimpleNamespace(), "POST", path, {}, matched.params, {"source_path": "sdk.zip", "accepted_license": True})
    response = matched.route.handler(request)
    if operation == "status":
        assert response.data == {"installed": False}
        service.status.assert_called_once_with("l2d")
    else:
        assert isinstance(response, TaskResponse)
        response.worker("task")
        getattr(service, operation).assert_called_once_with("l2d", request.body)
    assert FrontendBridgeHandler.api_router.match("GET", path) is None


@pytest.mark.parametrize("send_body", [True, False])
def test_runtime_file_route_uses_media_auth_and_exact_service_lookup(tmp_path, monkeypatch, send_body):
    service = Mock()
    target = tmp_path / "sdk.js"
    service.file.return_value = target
    factory = Mock(return_value=service)
    monkeypatch.setattr("application.media.avatar_runtime.AvatarRuntimeService", factory)
    handler = SimpleNamespace(state=SimpleNamespace(project_root_dir=str(tmp_path)), _require_authorized_media_read=Mock(), _send_local_file=Mock())
    assert dispatch_file_request(handler, "/api/avatar/runtime/file", "format=l2d&path=cubism-sdk.js", send_body=send_body)
    handler._require_authorized_media_read.assert_called_once()
    factory.assert_called_once_with(Path(tmp_path))
    service.file.assert_called_once_with("l2d", "cubism-sdk.js")
    handler._send_local_file.assert_called_once_with(target, send_body=send_body)


def test_runtime_file_route_rejects_unauthorized_reads_before_file_lookup(tmp_path, monkeypatch):
    factory = Mock()
    monkeypatch.setattr("application.media.avatar_runtime.AvatarRuntimeService", factory)
    handler = SimpleNamespace(state=SimpleNamespace(project_root_dir=str(tmp_path)), _require_authorized_media_read=Mock(side_effect=PermissionError("token")))
    with pytest.raises(PermissionError):
        dispatch_file_request(handler, "/api/avatar/runtime/file", "format=l2d&path=cubism-sdk.js", send_body=True)
    factory.assert_not_called()
