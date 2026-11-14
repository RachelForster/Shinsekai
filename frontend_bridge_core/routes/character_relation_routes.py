"""Character-owned JSON graph endpoints."""
from __future__ import annotations

from application.character_relation.manage_relations import (
    CharacterRelationUseCase,
    build_relation_use_case,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
)


def get_relation_use_case(request: ApiRequest) -> CharacterRelationUseCase:
    return build_relation_use_case(
        request.state.config_manager,
    )


def get_relation_graph(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        get_relation_use_case(request).get_relation_graph(request.params["owner"])
    )


def apply_relation_changes(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        get_relation_use_case(request).apply_relation_changes(
            request.params["owner"],
            request.body.get("operations"),
        )
    )

CHARACTER_RELATION_ROUTES = (
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/character-relations/graphs/{owner}",
        handler=get_relation_graph,
        body_kind=BodyKind.NONE,
        name="character_relations.graphs.get",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/character-relations/graphs/{owner}/changes",
        handler=apply_relation_changes,
        name="character_relations.graphs.apply_changes",
    ),
)
