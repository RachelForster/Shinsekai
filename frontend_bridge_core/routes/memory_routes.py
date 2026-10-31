from __future__ import annotations

from http import HTTPStatus

from frontend_bridge_core.memory import (
    _add_character_memory,
    _delete_character_memory,
    _get_mem0_status,
    _list_character_memories,
    _memory_asset_index,
    _memory_asset_search,
    _scoped_memory_operation,
    _memory_tool_forget,
    _memory_tool_remember,
    _memory_tool_search,
)
from frontend_bridge_core.routes.router import ApiRequest, JsonResponse, Route


def _scoped(request, action):
    return JsonResponse(_scoped_memory_operation(request.state, action, request.body))


def _memory_extract(request):
    return _scoped(request, "extract")


def _daily_memory(request, action):
    """Resolve shared identity from the registry; never trust an identity from UI."""
    from application.characters.links import _request
    from config.character_identity import installation_id
    from pathlib import Path
    from uuid import uuid4
    from datetime import datetime, timezone
    name = str(request.body.get("name") or request.body.get("characterName") or "")
    character = next((c for c in request.state.config_manager.config.characters if c.name == name), None)
    if character is None:
        raise ValueError("请先保存并选择角色。")
    root = Path(request.state.project_root_dir)
    try:
        link = _request("state", {"shinsekai_instance": installation_id(root), "shinsekai_id": character.id}).get("link")
    except OSError as exc:
        raise ValueError("暂时无法读取日常记忆，请启动 Doki 后重试。") from exc
    if not link or link.get("role") != "character":
        raise ValueError("该角色尚未链接 Doki 聊天角色，不能读取日常线记忆。")
    scope = {"character_id": link["memory_identity"], "timeline": "daily", "timeline_id": ""}
    payload = {**request.body, "scope": scope}
    if action == "remember":
        payload["metadata"] = {"source_app": "shinsekai", "session_id": "character-memory-editor", "event_id": uuid4().hex, "occurred_at": datetime.now(timezone.utc).isoformat(), "record_kind": "curated", "category": "manual", "status": "stable", "edited_by_user": True}
    result = _scoped_memory_operation(request.state, action, payload)
    if result.get("status") in {"loading", "not_started", "starting"}:
        return JsonResponse({"status": result["status"], "errorCode": "doki_memory_preparing", "error": "正在准备长期记忆。首次使用需要下载并加载模型，可能需要几分钟；准备完成后会自动显示记忆，无需反复刷新。"}, HTTPStatus.SERVICE_UNAVAILABLE)
    if result.get("error") or result.get("status") in {"error", "loading", "missing_dependency", "not_started", "starting", "unknown"}:
        return JsonResponse({**result, "error": result.get("error") or result.get("message") or "记忆服务正在准备，请稍后刷新。"}, HTTPStatus.SERVICE_UNAVAILABLE)
    if action in {"remember", "forget"}:
        result = _scoped_memory_operation(request.state, "list", {"scope": scope})
    return JsonResponse({**result, "agentId": name})


def _character_memory_status(_request: ApiRequest) -> JsonResponse:
    return JsonResponse(_get_mem0_status())


def _character_memory_list(request: ApiRequest) -> JsonResponse:
    if request.body.get("timeline") == "daily":
        return _daily_memory(request, "list")
    return JsonResponse(_list_character_memories(str(request.body.get("name") or "")))


def _character_memory_add(request: ApiRequest) -> JsonResponse:
    if request.body.get("timeline") == "daily":
        return _daily_memory(request, "remember")
    return JsonResponse(
        _add_character_memory(
            str(request.body.get("name") or ""),
            str(request.body.get("content") or ""),
        )
    )


def _character_memory_delete(request: ApiRequest) -> JsonResponse:
    if request.body.get("timeline") == "daily":
        return _daily_memory(request, "forget")
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
    if "scope" in request.body:
        return _scoped(request, "list")
    return JsonResponse(
        _list_character_memories(
            str(request.body.get("name") or request.body.get("characterName") or "")
        )
    )


def _memory_search(request: ApiRequest) -> JsonResponse:
    if request.body.get("timeline") == "daily":
        return _daily_memory(request, "search")
    if "scope" in request.body:
        return _scoped(request, "search")
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
    if "scope" in request.body:
        return _scoped(request, "remember")
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
    if "scope" in request.body:
        return _scoped(request, "forget")
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
        pattern="/api/memory/extract",
        handler=_memory_extract,
        name="memory.extract",
    ),
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
