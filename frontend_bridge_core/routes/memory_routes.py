from __future__ import annotations

from frontend_bridge_core.memory import (
    _add_character_memory,
    _awaken_character_memory,
    _delete_character_memory,
    _get_mem0_status,
    _list_character_memories,
    _memory_asset_index,
    _memory_asset_search,
    _memory_tool_awaken,
    _memory_tool_forget,
    _memory_tool_pin,
    _memory_tool_recall,
    _memory_tool_remember,
    _memory_tool_rollback,
    _memory_tool_search,
    _pin_character_memory,
)
from frontend_bridge_core.routes.router import ApiRequest, JsonResponse, Route


def _character_memory_status(_request: ApiRequest) -> JsonResponse:
    return JsonResponse(_get_mem0_status())


def _character_memory_list(request: ApiRequest) -> JsonResponse:
    sid = str(request.body.get("sessionId") or request.body.get("session_id") or "")
    name = str(request.body.get("name") or "")
    if sid:
        return JsonResponse(_list_character_memories(name, session_id=sid))
    return JsonResponse(_list_character_memories(name))


def _character_memory_add(request: ApiRequest) -> JsonResponse:
    extra: dict = {}
    if bool(request.body.get("pinned", False)):
        extra["pinned"] = True
    gist = str(request.body.get("gist") or request.body.get("gistText") or "")
    if gist:
        extra["gist_text"] = gist
    slot = str(request.body.get("slotKey") or request.body.get("slot_key") or "")
    if slot:
        extra["slot_key"] = slot
    kind = str(request.body.get("kind") or "")
    if kind:
        extra["kind"] = kind
    sid = str(request.body.get("sessionId") or request.body.get("session_id") or "")
    if sid:
        extra["session_id"] = sid
    return JsonResponse(
        _add_character_memory(
            str(request.body.get("name") or ""),
            str(request.body.get("content") or ""),
            **extra,
        )
    )


def _character_memory_delete(request: ApiRequest) -> JsonResponse:
    sid = str(request.body.get("sessionId") or request.body.get("session_id") or "")
    extra = {"session_id": sid} if sid else {}
    return JsonResponse(
        _delete_character_memory(
            str(request.body.get("name") or ""),
            str(request.body.get("memoryId") or ""),
            **extra,
        )
    )


def _character_memory_pin(request: ApiRequest) -> JsonResponse:
    sid = str(request.body.get("sessionId") or request.body.get("session_id") or "")
    return JsonResponse(
        _pin_character_memory(
            str(request.body.get("name") or ""),
            str(request.body.get("memoryId") or request.body.get("memory_id") or ""),
            bool(request.body.get("pinned", True)),
            session_id=sid,
        )
    )


def _character_memory_awaken(request: ApiRequest) -> JsonResponse:
    sid = str(request.body.get("sessionId") or request.body.get("session_id") or "")
    return JsonResponse(
        _awaken_character_memory(
            str(request.body.get("name") or ""),
            str(request.body.get("memoryId") or request.body.get("memory_id") or ""),
            session_id=sid,
        )
    )


def _memory_status(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _get_mem0_status(start_loading=bool(request.body.get("startLoading", True)))
    )


def _memory_list(request: ApiRequest) -> JsonResponse:
    sid = str(request.body.get("sessionId") or request.body.get("session_id") or "")
    name = str(request.body.get("name") or request.body.get("characterName") or "")
    if sid:
        return JsonResponse(_list_character_memories(name, session_id=sid))
    return JsonResponse(_list_character_memories(name))


def _memory_search(request: ApiRequest) -> JsonResponse:
    query = str(request.body.get("query") or "")
    character_name = str(
        request.body.get("characterName")
        or request.body.get("character_name")
        or ""
    )
    limit = int(request.body.get("limit") or 10)
    session_id = str(
        request.body.get("sessionId") or request.body.get("session_id") or ""
    )
    memory_mode = str(
        request.body.get("memoryMode") or request.body.get("memory_mode") or ""
    )
    if session_id or memory_mode:
        return JsonResponse(
            _memory_tool_search(
                query,
                character_name,
                limit,
                session_id=session_id,
                memory_mode=memory_mode,
            )
        )
    return JsonResponse(_memory_tool_search(query, character_name, limit))


def _memory_recall(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_memory_tool_recall(dict(request.body or {})))


def _memory_remember(request: ApiRequest) -> JsonResponse:
    raw_seq = request.body.get("sourceTurnSeq", request.body.get("source_turn_seq"))
    parsed_seq = None if raw_seq is None or raw_seq == "" else int(raw_seq)
    raw_event = request.body.get("eventAt", request.body.get("event_at"))
    parsed_event = None if raw_event is None or raw_event == "" else float(raw_event)
    raw_imp = request.body.get("importance")
    parsed_imp = 0.5 if raw_imp is None or raw_imp == "" else float(raw_imp)
    raw_topics = request.body.get("topicTags", request.body.get("topic_tags")) or ()
    topics = tuple(str(x) for x in raw_topics) if isinstance(raw_topics, (list, tuple)) else ()
    raw_entities = request.body.get("entities") or ()
    entities = (
        tuple(str(x) for x in raw_entities)
        if isinstance(raw_entities, (list, tuple))
        else ()
    )
    return JsonResponse(
        _memory_tool_remember(
            str(request.body.get("content") or ""),
            str(
                request.body.get("characterName")
                or request.body.get("character_name")
                or ""
            ),
            gist_text=str(
                request.body.get("gistText") or request.body.get("gist_text") or ""
            ),
            slot_key=str(
                request.body.get("slotKey") or request.body.get("slot_key") or ""
            ),
            kind=str(request.body.get("kind") or "episodic"),
            topic_tags=topics,
            entities=entities,
            importance=parsed_imp,
            pinned=bool(request.body.get("pinned", False)),
            event_at=parsed_event,
            memory_mode=str(
                request.body.get("memoryMode") or request.body.get("memory_mode") or ""
            ),
            player_character=str(
                request.body.get("playerCharacter")
                or request.body.get("player_character")
                or ""
            ),
            source_session_id=str(
                request.body.get("sourceSessionId")
                or request.body.get("source_session_id")
                or ""
            ),
            source_turn_seq=parsed_seq,
        )
    )


def _memory_rollback(request: ApiRequest) -> JsonResponse:
    raw_seq = request.body.get("turnSeq", request.body.get("turn_seq", 0))
    return JsonResponse(
        _memory_tool_rollback(
            str(
                request.body.get("sessionId")
                or request.body.get("session_id")
                or ""
            ),
            int(raw_seq or 0),
        )
    )


def _memory_forget(request: ApiRequest) -> JsonResponse:
    sid = str(request.body.get("sessionId") or request.body.get("session_id") or "")
    mid = str(request.body.get("memoryId") or request.body.get("memory_id") or "")
    if sid:
        return JsonResponse(_memory_tool_forget(mid, session_id=sid))
    return JsonResponse(_memory_tool_forget(mid))


def _memory_pin(request: ApiRequest) -> JsonResponse:
    sid = str(request.body.get("sessionId") or request.body.get("session_id") or "")
    return JsonResponse(
        _memory_tool_pin(
            str(request.body.get("memoryId") or request.body.get("memory_id") or ""),
            bool(request.body.get("pinned", True)),
            session_id=sid,
        )
    )


def _memory_awaken(request: ApiRequest) -> JsonResponse:
    sid = str(request.body.get("sessionId") or request.body.get("session_id") or "")
    return JsonResponse(
        _memory_tool_awaken(
            str(request.body.get("memoryId") or request.body.get("memory_id") or ""),
            session_id=sid,
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
        pattern="/api/characters/memories/pin",
        handler=_character_memory_pin,
        name="characters.memories.pin",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/characters/memories/awaken",
        handler=_character_memory_awaken,
        name="characters.memories.awaken",
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
        pattern="/api/memory/recall",
        handler=_memory_recall,
        name="memory.recall",
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
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/memory/rollback",
        handler=_memory_rollback,
        name="memory.rollback",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/memory/pin",
        handler=_memory_pin,
        name="memory.pin",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/memory/awaken",
        handler=_memory_awaken,
        name="memory.awaken",
    ),
)
