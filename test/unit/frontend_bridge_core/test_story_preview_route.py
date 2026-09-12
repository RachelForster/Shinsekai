from types import SimpleNamespace

from frontend_bridge_core.routes.router import ApiRequest, BodyKind
from frontend_bridge_core.routes.story_routes import STORY_ROUTES
from test.unit.application.story.test_generation import ScriptedModel, service_at


def test_preview_route_reads_the_requested_task_without_accepting_paths(tmp_path):
    service, _ = service_at(tmp_path, ScriptedModel({}))
    task = service.create("A new story")
    state = SimpleNamespace(
        config_manager=SimpleNamespace(feature_flags=service.flags),
        story_generation_service=service,
    )
    route = next(item for item in STORY_ROUTES if item.name == "story.generation.preview")
    path = f"/api/story/generation/{task['id']}/preview"
    assert route.body_kind is BodyKind.NONE
    response = route.handler(ApiRequest(
        state=state, method="GET", path=path, query={},
        params=route.match_path(path), body={},
    ))
    assert response.data == {"artifacts": {}, "graph": None, "title": ""}
    assert route.match_path("/api/story/generation/../../secret/preview") is None
