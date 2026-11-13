"""HTTP bridge routes for game state / frame ingestion and perception diagnostics."""

from __future__ import annotations

from http import HTTPStatus
import secrets
from typing import Any

from application.perception.server_launcher import (
    get_perception_server_manager,
    probe_perception,
    resolve_perception_config,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
)


def _forward_perception_command(
    state: Any,
    command_type: str,
    payload: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    session_id = str(getattr(state, "chat_session", {}).get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)
    if not session_id or chat_stream is None:
        return False, None
    ok = chat_stream.send_command(
        session_id,
        {
            "cmdId": secrets.token_hex(16),
            "type": command_type,
            "payload": payload or {},
        },
    )
    snapshot = chat_stream.get_snapshot(session_id)
    perception_state = (
        snapshot.get("perception")
        if isinstance(snapshot, dict) and isinstance(snapshot.get("perception"), dict)
        else None
    )
    return bool(ok), perception_state


def forward_plugin_perception_from_bridge(state: Any, payload: dict[str, Any]) -> bool:
    """Forward bridge-hosted plugin perception payloads to the active Chat runtime."""
    ok, _ = _forward_perception_command(state, "perception-ingest", payload)
    return ok


def _perception_probe_image(request: ApiRequest) -> JsonResponse:
    cfg = resolve_perception_config(request.state.config_manager.config.api_config)
    return JsonResponse(probe_perception(cfg, request.body, image=True))


def _perception_status(request: ApiRequest) -> JsonResponse:
    state = request.state
    cfg = resolve_perception_config(state.config_manager.config.api_config)
    session_id = str(getattr(state, "chat_session", {}).get("sessionId") or "").strip()
    chat_stream = getattr(state, "chat_stream", None)
    snapshot = chat_stream.get_snapshot(session_id) if (session_id and chat_stream) else None
    runtime_perception = (
        snapshot.get("perception")
        if isinstance(snapshot, dict) and isinstance(snapshot.get("perception"), dict)
        else None
    )

    probe_flag = str((request.query.get("probe") or [""])[0]).strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if probe_flag:
        overrides = {key: (request.query.get(key) or [""])[0] for key in ("baseUrl", "model", "apiKey")}
        health = probe_perception(cfg, overrides)
    else:
        health = None

    http_base = getattr(chat_stream, "http_base", "http://127.0.0.1:8787")
    auth_token = str(getattr(state, "auth_token", "") or "").strip()
    ingest_url = (
        f"{http_base}/api/perception/ingest?token={auth_token}"
        if auth_token
        else f"{http_base}/api/perception/ingest"
    )

    api_config = state.config_manager.config.api_config
    configured_python = str(getattr(api_config, "perception_python_path", "") or "").strip()
    local_server = get_perception_server_manager().status(explicit_python_path=configured_python)

    return JsonResponse(
        {
            "chatSessionActive": bool(session_id),
            "config": {
                "enabled": cfg.enabled,
                "baseUrl": cfg.base_url,
                "model": cfg.model,
                "intervalSec": cfg.interval_sec,
                "captureIntervalSec": cfg.capture_interval_sec,
                "ocrIntervalSec": cfg.ocr_interval_sec,
                "frameMaxSide": cfg.frame_max_side,
                "diffThreshold": cfg.diff_threshold,
                "reflexEnabled": cfg.reflex_enabled,
                "reflexCooldownSec": cfg.reflex_cooldown_sec,
                "proactiveEnabled": cfg.proactive_enabled,
                "salienceThreshold": cfg.salience_threshold,
                "proactiveCooldownSec": cfg.proactive_cooldown_sec,
            },
            "ingestUrl": ingest_url,
            "localServer": local_server,
            "runtime": runtime_perception,
            **({"health": health} if health is not None else {}),
        }
    )


def _perception_ingest(request: ApiRequest) -> JsonResponse:
    body = request.body
    if not isinstance(body, dict) or not body:
        raise ValueError("perception ingest body must be a non-empty JSON object")
    accepted, runtime_state = _forward_perception_command(
        request.state,
        "perception-ingest",
        body,
    )
    if not accepted:
        return JsonResponse(
            {
                "ok": False,
                "accepted": False,
                "reason": "no_active_chat_session",
            },
            HTTPStatus.ACCEPTED,
        )
    return JsonResponse(
        {
            "ok": True,
            "accepted": True,
            "perception": runtime_state,
        }
    )


def _perception_clear(request: ApiRequest) -> JsonResponse:
    accepted, runtime_state = _forward_perception_command(
        request.state,
        "perception-clear",
        {},
    )
    return JsonResponse(
        {
            "ok": True,
            "accepted": accepted,
            "perception": runtime_state,
        }
    )


def _perception_server_start(request: ApiRequest) -> JsonResponse:
    api_config = request.state.config_manager.config.api_config
    cfg = resolve_perception_config(api_config)
    body = request.body if isinstance(request.body, dict) else {}

    base_url = str(body.get("baseUrl") or cfg.base_url).strip() or cfg.base_url
    model = str(body.get("model") or cfg.model).strip() or cfg.model
    python_path = str(
        body.get("pythonPath")
        if "pythonPath" in body
        else getattr(api_config, "perception_python_path", "") or ""
    ).strip()
    device = str(body.get("device") or "cuda:0").strip() or "cuda:0"

    status = get_perception_server_manager().start(
        base_url=base_url,
        model=model,
        python_path=python_path,
        device=device,
    )
    return JsonResponse({"ok": True, "localServer": status})


def _perception_server_stop(_request: ApiRequest) -> JsonResponse:
    status = get_perception_server_manager().stop()
    return JsonResponse({"ok": True, "localServer": status})


PERCEPTION_ROUTES = (
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/perception/status",
        handler=_perception_status,
        body_kind=BodyKind.NONE,
        name="perception.status",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/perception/probe-image",
        handler=_perception_probe_image,
        body_kind=BodyKind.JSON,
        name="perception.probe-image",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/perception/ingest",
        handler=_perception_ingest,
        body_kind=BodyKind.JSON,
        name="perception.ingest",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/perception/clear",
        handler=_perception_clear,
        body_kind=BodyKind.JSON,
        name="perception.clear",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/perception/server/start",
        handler=_perception_server_start,
        body_kind=BodyKind.JSON,
        name="perception.server.start",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/perception/server/stop",
        handler=_perception_server_stop,
        body_kind=BodyKind.JSON,
        name="perception.server.stop",
    ),
)
