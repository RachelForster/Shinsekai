from __future__ import annotations

from frontend_bridge_core.routes.router import ApiRequest, BodyKind, JsonResponse, Route
from frontend_bridge_core.knowledge import (
    _get_knowledge_status,
    _knowledge_binding_operation,
    _knowledge_browse,
    _knowledge_operation,
    _knowledge_search,
)


def _bindings(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_knowledge_binding_operation(
        "list",
        character_name=(request.query.get("character_name") or [""])[0],
        page=int((request.query.get("page") or ["1"])[0]),
    ))


def _browse(request: ApiRequest) -> JsonResponse:
    operation = request.path.rsplit("/", 1)[-1]
    query = request.query
    knowledge_id = (query.get("knowledge_id") or [""])[0]
    if operation == "instances":
        result = _knowledge_browse(
            operation, query=(query.get("query") or [""])[0],
            page=int((query.get("page") or ["1"])[0]),
            refresh=(query.get("refresh") or [""])[0] == "true",
        )
    else:
        result = _knowledge_browse(operation, knowledge_id=knowledge_id)
    return JsonResponse(result)


def _status(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_get_knowledge_status(
        start_loading=bool(request.body.get("startLoading", False)),
        retry=bool(request.body.get("retry", False)),
    ))


def _knowledge_list(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_knowledge_operation(
        "list", knowledge_id=str(request.body.get("knowledge_id") or ""),
        limit=int(request.body.get("limit") or 200),
    ))


def _knowledge_remember(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_knowledge_operation(
        "remember", knowledge_id=str(request.body.get("knowledge_id") or ""),
        content=str(request.body.get("content") or ""),
    ))


def _knowledge_forget(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_knowledge_operation(
        "forget", memory_id=str(request.body.get("memory_id") or ""),
    ))


def _knowledge_delete(request: ApiRequest) -> JsonResponse:
    knowledge_id = request.body.get("knowledge_id")
    if not isinstance(knowledge_id, str) or not knowledge_id.strip():
        raise ValueError("knowledge_id must be a non-empty string")
    return JsonResponse(_knowledge_operation("delete", knowledge_id=knowledge_id.strip()))


def _knowledge_remember_and_list(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_knowledge_operation(
        "remember-and-list", knowledge_id=str(request.body.get("knowledge_id") or ""),
        content=str(request.body.get("content") or ""),
    ))


def _knowledge_forget_and_list(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_knowledge_operation(
        "forget-and-list", knowledge_id=str(request.body.get("knowledge_id") or ""),
        memory_id=str(request.body.get("memory_id") or ""),
    ))


def _change_binding(request: ApiRequest) -> JsonResponse:
    operation = request.path.rsplit("/", 1)[-1]
    fields = ["character_name", "knowledge_id"]
    kwargs = {}
    for field in fields:
        value = request.body.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        kwargs[field] = value.strip()
    return JsonResponse(_knowledge_binding_operation(operation, **kwargs))


def _knowledge_bindings(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_knowledge_binding_operation(
        "knowledge", knowledge_id=(request.query.get("knowledge_id") or [""])[0],
    ))


def _batch_bindings(request: ApiRequest) -> JsonResponse:
    knowledge_id = request.body.get("knowledge_id")
    if not isinstance(knowledge_id, str) or not knowledge_id.strip():
        raise ValueError("knowledge_id must be a non-empty string")
    changes = {}
    for field in ("add", "remove"):
        values = request.body.get(field)
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(f"{field} must be a list of non-empty character names")
        changes[field] = sorted({v.strip() for v in values})
    if set(changes["add"]) & set(changes["remove"]):
        raise ValueError("a character cannot be added and removed in the same request")
    return JsonResponse(_knowledge_binding_operation("batch", knowledge_id=knowledge_id.strip(), **changes))


def _search_entries(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_knowledge_browse(
        "entries/search", knowledge_id=str(request.body.get("knowledge_id") or ""),
        query=str(request.body.get("query") or ""),
        limit=int(request.body.get("limit") or 200),
    ))


def _search(request: ApiRequest) -> JsonResponse:
    raw_names = request.body.get("characterNames") or []
    if not isinstance(raw_names, list):
        raise ValueError("characterNames must be a list")
    return JsonResponse(_knowledge_search(
        str(request.body.get("query") or ""),
        [str(name) for name in raw_names],
        int(request.body.get("limit") or 5),
    ))


KNOWLEDGE_ROUTES = (
    Route(methods=frozenset({"GET"}), pattern="/api/knowledge/bindings/knowledge",
          handler=_knowledge_bindings, body_kind=BodyKind.NONE, name="knowledge.bindings.knowledge"),
    Route(methods=frozenset({"POST"}), pattern="/api/knowledge/bindings/batch",
          handler=_batch_bindings, name="knowledge.bindings.batch"),
    Route(methods=frozenset({"GET"}), pattern="/api/knowledge/bindings",
          handler=_bindings, body_kind=BodyKind.NONE, name="knowledge.bindings.list"),
    *(Route(methods=frozenset({"GET"}), pattern=f"/api/knowledge/{operation}",
            handler=_browse, body_kind=BodyKind.NONE, name=f"knowledge.{operation}")
      for operation in ("instances", "entries")),
    Route(methods=frozenset({"POST"}), pattern="/api/knowledge/status",
          handler=_status, name="knowledge.status"),
    Route(methods=frozenset({"POST"}), pattern="/api/knowledge/list",
          handler=_knowledge_list, name="knowledge.list"),
    Route(methods=frozenset({"POST"}), pattern="/api/knowledge/remember",
          handler=_knowledge_remember, name="knowledge.remember"),
    Route(methods=frozenset({"POST"}), pattern="/api/knowledge/forget",
          handler=_knowledge_forget, name="knowledge.forget"),
    Route(methods=frozenset({"POST"}), pattern="/api/knowledge/delete",
          handler=_knowledge_delete, name="knowledge.delete"),
    Route(methods=frozenset({"POST"}), pattern="/api/knowledge/remember-and-list",
          handler=_knowledge_remember_and_list, name="knowledge.remember-and-list"),
    Route(methods=frozenset({"POST"}), pattern="/api/knowledge/forget-and-list",
          handler=_knowledge_forget_and_list, name="knowledge.forget-and-list"),
    *(Route(methods=frozenset({"POST"}), pattern=f"/api/knowledge/bindings/{operation}",
            handler=_change_binding, name=f"knowledge.bindings.{operation}")
      for operation in ("add", "remove")),
    Route(methods=frozenset({"POST"}), pattern="/api/knowledge/entries/search",
          handler=_search_entries, name="knowledge.entries.search"),
    Route(methods=frozenset({"POST"}), pattern="/api/knowledge/search",
          handler=_search, name="knowledge.search"),
)
