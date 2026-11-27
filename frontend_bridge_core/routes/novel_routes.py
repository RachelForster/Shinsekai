from __future__ import annotations

from typing import Any

from application.chat.composition import _chat_snapshot, _handle_chat_command
from application.novel_theater import (
    build_novel_system_template,
    delete_novel_document,
    extract_novel_cast,
    get_novel_document_detail,
    import_novel_document,
    list_novel_documents,
    prepare_novel_launch,
    save_novel_casting,
)
from frontend_bridge_core.chat_session import _usable_media_selection_mode
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
)
from sdk.exception.types import AppError
from sdk.logging import new_log_id


def _list_documents(request: ApiRequest) -> JsonResponse:
    return JsonResponse({"documents": list_novel_documents(request.state)})


def _import_document(request: ApiRequest) -> JsonResponse:
    uploads = request.uploads
    paths = uploads.paths if uploads is not None else ()
    if not paths:
        raise AppError(
            "novel.document_file_required",
            fallback_message="A document file is required.",
            http_status=400,
        )
    detail = import_novel_document(request.state, paths[0])
    return JsonResponse({"document": detail})


def _get_document(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        {"document": get_novel_document_detail(request.state, request.params["doc_id"])}
    )


def _delete_document(request: ApiRequest) -> JsonResponse:
    return JsonResponse(delete_novel_document(request.state, request.params["doc_id"]))


def _extract_cast(request: ApiRequest) -> JsonResponse:
    return JsonResponse(extract_novel_cast(request.state, request.params["doc_id"]))


def _save_casting(request: ApiRequest) -> JsonResponse:
    body = request.body if isinstance(request.body, dict) else {}
    conversation_id = str(body.get("conversationId") or "").strip()
    bindings = body.get("bindings")
    if not conversation_id or not isinstance(bindings, list):
        raise AppError(
            "novel.invalid_launch_request",
            fallback_message="conversationId and bindings are required.",
            http_status=400,
        )
    raw_name_mode = body.get("nameMode")
    name_mode = (
        raw_name_mode.strip()
        if isinstance(raw_name_mode, str) and raw_name_mode.strip()
        else None
    )
    summary = (
        save_novel_casting(
            request.state,
            conversation_id,
            bindings,
            name_mode=name_mode,
        )
        if name_mode is not None
        else save_novel_casting(request.state, conversation_id, bindings)
    )
    return JsonResponse({"conversation": summary})


def _prepare_launch_payload(request: ApiRequest) -> JsonResponse:
    body = request.body if isinstance(request.body, dict) else {}
    payload = prepare_novel_launch(request.state, body)
    payload["mediaSelectionMode"] = _usable_media_selection_mode(
        payload.get("mediaSelectionMode")
    )
    payload["system"] = build_novel_system_template(request.state, payload)
    return JsonResponse({"payload": payload})


def _parse_non_negative_int(value: Any, *, field_name: str, error_code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AppError(
            error_code,
            params={"field": field_name},
            fallback_message=f"{field_name} must be a non-negative integer.",
            http_status=400,
        )
    return value


def _jump_chapter(request: ApiRequest) -> JsonResponse:
    body = request.body if isinstance(request.body, dict) else {}
    chapter_index = _parse_non_negative_int(
        body.get("chapterIndex"),
        field_name="chapterIndex",
        error_code="novel.invalid_chapter",
    )
    expected_version = _parse_non_negative_int(
        body.get("expectedStateVersion"),
        field_name="expectedStateVersion",
        error_code="behavior.invalid_command",
    )
    command_id = str(body.get("commandId") or "").strip() or new_log_id()
    _handle_chat_command(
        request.state,
        {
            "type": "behavior-command",
            "payload": {
                "commandId": command_id,
                "action": "jump_chapter",
                "expectedStateVersion": expected_version,
                "payload": {"chapterIndex": chapter_index},
            },
        },
    )
    return JsonResponse({"ok": True, "chat": _chat_snapshot(request.state)})


NOVEL_ROUTES = (
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/novel/documents",
        handler=_list_documents,
        body_kind=BodyKind.NONE,
        name="novel.documents.list",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/novel/documents/import",
        handler=_import_document,
        body_kind=BodyKind.MULTIPART,
        name="novel.documents.import",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/novel/documents/{doc_id}",
        handler=_get_document,
        body_kind=BodyKind.NONE,
        name="novel.documents.get",
    ),
    Route(
        methods=frozenset({"DELETE"}),
        pattern="/api/novel/documents/{doc_id}",
        handler=_delete_document,
        body_kind=BodyKind.NONE,
        name="novel.documents.delete",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/novel/documents/{doc_id}/extract-cast",
        handler=_extract_cast,
        name="novel.documents.extract_cast",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/novel/casting",
        handler=_save_casting,
        name="novel.casting.save",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/novel/launch-payload",
        handler=_prepare_launch_payload,
        name="novel.launch_payload",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/novel/jump-chapter",
        handler=_jump_chapter,
        name="novel.jump_chapter",
    ),
)

__all__ = ["NOVEL_ROUTES"]
