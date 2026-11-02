from __future__ import annotations

from frontend_bridge_core.memory import (
    _add_character_memory,
    _delete_character_memory,
    _get_mem0_status,
    _list_character_memories,
    _memory_asset_index,
    _memory_asset_search,
    _memory_tool_forget,
    _memory_tool_remember,
    _memory_tool_search,
)
from frontend_bridge_core.routes.router import ApiRequest, JsonResponse, Route


def _character_memory_status(_request: ApiRequest) -> JsonResponse:
    return JsonResponse(_get_mem0_status())


def _character_memory_list(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_list_character_memories(str(request.body.get("name") or "")))


def _character_memory_add(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _add_character_memory(
            str(request.body.get("name") or ""),
            str(request.body.get("content") or ""),
        )
    )


def _character_memory_delete(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _delete_character_memory(
            str(request.body.get("name") or ""),
            str(request.body.get("memoryId") or ""),
        )
    )


def _memory_status(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _get_mem0_status(start_loading=bool(request.body.get("startLoading", True)))
    )


def _memory_list(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _list_character_memories(
            str(request.body.get("name") or request.body.get("characterName") or "")
        )
    )


def _memory_search(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _memory_tool_search(
            str(request.body.get("query") or ""),
            str(
                request.body.get("characterName")
                or request.body.get("character_name")
                or ""
            ),
            int(request.body.get("limit") or 10),
        )
    )


def _memory_remember(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _memory_tool_remember(
            str(request.body.get("content") or ""),
            str(
                request.body.get("characterName")
                or request.body.get("character_name")
                or ""
            ),
        )
    )


def _memory_forget(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _memory_tool_forget(
            str(request.body.get("memoryId") or request.body.get("memory_id") or "")
        )
    )


def _memory_asset_lookup(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_memory_asset_search(request.body))


def _memory_asset_prepare(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_memory_asset_index(request.body))


MEMORY_ROUTES = (
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/memory/asset-index",
        handler=_memory_asset_prepare,
        name="memory.asset-index",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/memory/asset-search",
        handler=_memory_asset_lookup,
        name="memory.asset-search",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/memories/status",
        handler=_character_memory_status,
        name="characters.memories.status",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/memories/list",
        handler=_character_memory_list,
        name="characters.memories.list",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/memories/add",
        handler=_character_memory_add,
        name="characters.memories.add",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/memories/delete",
        handler=_character_memory_delete,
        name="characters.memories.delete",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/memory/status",
        handler=_memory_status,
        name="memory.status",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/memory/list",
        handler=_memory_list,
        name="memory.list",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/memory/search",
        handler=_memory_search,
        name="memory.search",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/memory/remember",
        handler=_memory_remember,
        name="memory.remember",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/memory/forget",
        handler=_memory_forget,
        name="memory.forget",
    ),
)
