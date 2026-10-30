from __future__ import annotations

from types import SimpleNamespace

from application.media import open_workflow_folder as workflows
from frontend_bridge_core.routes.router import ApiRequest, BodyKind
from frontend_bridge_core.routes.utility_routes import UTILITY_ROUTES


def _contracts() -> set[tuple[str, str]]:
    return {
        (method, route.pattern) for route in UTILITY_ROUTES for method in route.methods
    }


def test_utility_route_contracts_remain_stable() -> None:
    assert _contracts() == {
        ("GET", "/api/logs"),
        ("GET", "/api/logs/default"),
        ("POST", "/api/files/browse"),
        ("POST", "/api/files/t2i-workflows/open"),
        ("POST", "/api/logs/diagnostic-bundle"),
        ("POST", "/api/logs/read"),
        ("POST", "/api/media/thumbnails"),
    }


def test_open_workflows_route_opens_only_the_bundled_directory(tmp_path, monkeypatch):
    folder = tmp_path / "ai" / "t2i" / "workflows"
    folder.mkdir(parents=True)
    opened = []

    def open_path(path):
        opened.append(path)
        return {"opened": path}

    monkeypatch.setattr(workflows, "open_local_path", open_path)
    route = next(
        route for route in UTILITY_ROUTES if route.name == "files.open_t2i_workflows"
    )
    request = ApiRequest(
        state=SimpleNamespace(project_root_dir=str(tmp_path)),
        method="POST",
        path=route.pattern,
        query={},
        params={},
        body={"path": "../another-directory"},
    )
    assert route.body_kind is BodyKind.NONE
    assert route.handler(request).data == {"path": folder.resolve().as_posix()}
    assert opened == [str(folder.resolve())]
