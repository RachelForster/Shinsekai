from __future__ import annotations

import hmac
import json
import threading
from contextlib import nullcontext
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from sdk.logging import get_logger, log_context, new_log_id
from sdk.agent import AgentRequestError
from sdk.exception import AppError

from application.chat.templates import NoValidCharactersError
from application.runtime.state import BridgeState, _jsonify
from application.runtime.tasks import (
    _create_task,
    _get_task,
    _run_background_task,
    _update_task,
)
from frontend_bridge_core.plugin_auth import resolve_issued_plugin_cookie_header
from frontend_bridge_core.routes.http_auth import (
    BRIDGE_AUTH_COOKIE,
    BRIDGE_AUTH_HEADER,
    BRIDGE_AUTH_QUERY,
    BridgeHttpAuthMixin,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    Router,
    TaskResponse,
)
from frontend_bridge_core.routes.uploads import UploadedFiles, read_uploaded_files
from frontend_bridge_core.security import safe_header_value

logger = get_logger("frontend_bridge_core.routes.api")

_AGENT_ERROR_HTTP_STATUS = {
    "BACKEND_UNAVAILABLE": HTTPStatus.SERVICE_UNAVAILABLE,
    "WORKER_LOST": HTTPStatus.SERVICE_UNAVAILABLE,
    "AUTH_REQUIRED": HTTPStatus.FORBIDDEN,
    "TOOL_DENIED": HTTPStatus.FORBIDDEN,
    "SESSION_BUSY": HTTPStatus.CONFLICT,
    "SESSION_BACKEND_MISMATCH": HTTPStatus.CONFLICT,
    "SESSION_RESUME_UNAVAILABLE": HTTPStatus.CONFLICT,
    "IDEMPOTENCY_CONFLICT": HTTPStatus.CONFLICT,
    "LIMIT_EXCEEDED": HTTPStatus.TOO_MANY_REQUESTS,
}

_POLLING_PATHS = {
    "/api/characters/memories/status",
    "/api/health",
    "/api/chat/runtime-status",
    "/api/chat/snapshot",
    "/api/memory/status",
    "/api/model-assets/status",
    "/api/perception/ingest",
    "/api/perception/status",
    "/api/plugins/status",
}


class BridgeHttpHandler(BridgeHttpAuthMixin, BaseHTTPRequestHandler):
    """Shared HTTP transport, authorization, and registered-route dispatch."""

    server_version = "ShinsekaiFrontendBridge/0.1"
    api_router: Router

    @property
    def state(self) -> BridgeState:
        return self.server.state  # type: ignore[attr-defined]

    def handle_one_request(self) -> None:
        with log_context(request_id=new_log_id("req_")):
            super().handle_one_request()

    def log_message(self, fmt: str, *args: Any) -> None:
        method = getattr(self, "command", "")
        path = urlparse(getattr(self, "path", "")).path
        try:
            status = int(args[1])
        except (IndexError, TypeError, ValueError):
            status = 0

        is_polling_request = (
            path in _POLLING_PATHS
            or (
                method in {"GET", "HEAD", "OPTIONS"}
                and path == "/api/characters"
                and parse_qs(urlparse(getattr(self, "path", "")).query).get("view") == ["revision"]
            )
            or (method in {"GET", "HEAD", "OPTIONS"} and path.startswith("/api/agent/"))
            or (
                method in {"GET", "HEAD", "OPTIONS"}
                and path.startswith("/api/tasks/")
                and not path.endswith("/cancel")
            )
        )
        if is_polling_request and 0 < status < 400:
            return

        log = (
            logger.error
            if status >= 500
            else logger.warning if status >= 400 else logger.info
        )
        log(
            fmt,
            *args,
            extra={
                "event": "http.request.completed",
                "method": method,
                "path": path,
                "status": status,
            },
        )

    def _log_request_exception(self, exc: Exception) -> None:
        extra = {
            "event": "http.request.failed",
            "method": getattr(self, "command", ""),
            "path": urlparse(getattr(self, "path", "")).path,
            "error_type": exc.__class__.__name__,
        }
        if isinstance(
            exc,
            (
                AppError,
                KeyError,
                FileExistsError,
                FileNotFoundError,
                PermissionError,
                ValueError,
                AgentRequestError,
            ),
        ):
            logger.warning("Frontend bridge request failed: %s", exc, extra=extra)
        else:
            logger.exception("Frontend bridge request failed", extra=extra)

    def _send_cors(self) -> None:
        origin = self._allowed_origin_header(str(self.headers.get("Origin") or ""))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header(
            "Access-Control-Allow-Methods", "GET, HEAD, POST, PUT, DELETE, OPTIONS"
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            f"Content-Type, Range, X-Task-Id, {BRIDGE_AUTH_HEADER}",
        )
        self.send_header(
            "Access-Control-Expose-Headers",
            "Accept-Ranges, Content-Length, Content-Range",
        )
        parsed = urlparse(getattr(self, "path", ""))
        query = parse_qs(parsed.query)
        query_token = str(
            (query.get(BRIDGE_AUTH_QUERY) or query.get("token") or [""])[0]
        ).strip()
        required = (
            str(getattr(self.state, "auth_token", "") or "").strip()
            if query_token
            else ""
        )
        if required and hmac.compare_digest(query_token, required):
            self.send_header(
                "Set-Cookie",
                f"{BRIDGE_AUTH_COOKIE}={safe_header_value(required)}; "
                "Path=/; HttpOnly; SameSite=Strict",
            )
        elif required and query_token:
            cookie_header = resolve_issued_plugin_cookie_header(
                required, parsed.path, query_token
            )
            if cookie_header:
                self.send_header("Set-Cookie", cookie_header)

    @staticmethod
    def _is_client_disconnect(exc: Exception) -> bool:
        return isinstance(
            exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
        )

    def _send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(_jsonify(data), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        try:
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def _send_error_json(
        self,
        exc: Exception,
        status: HTTPStatus = HTTPStatus.BAD_REQUEST,
        *,
        error_code: str = "",
        error_params: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"error": str(exc), "type": exc.__class__.__name__}
        resolved_code = error_code or str(getattr(exc, "error_code", "") or "")
        if resolved_code:
            payload["errorCode"] = resolved_code
        resolved_params = (
            error_params
            if error_params is not None
            else getattr(exc, "error_params", None)
        )
        if isinstance(resolved_params, dict) and resolved_params:
            payload["errorParams"] = dict(resolved_params)
        self._send_json(payload, status)

    def _send_exception_json(self, exc: Exception) -> None:
        if isinstance(exc, AgentRequestError):
            code = exc.error.code
            status = _AGENT_ERROR_HTTP_STATUS.get(code, HTTPStatus.BAD_REQUEST)
            self._send_json(
                {
                    "error": exc.error.message,
                    "errorCode": code,
                    "agentError": exc.error.to_wire(),
                },
                status,
            )
        elif isinstance(exc, AppError):
            try:
                app_status = HTTPStatus(exc.http_status)
            except ValueError:
                app_status = HTTPStatus.BAD_REQUEST
            self._send_error_json(
                exc,
                app_status,
                error_code=exc.error_code,
                error_params=exc.error_params,
            )
        elif isinstance(exc, NoValidCharactersError):
            self._send_error_json(
                exc,
                HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code=exc.error_code,
            )
        elif isinstance(exc, FileExistsError):
            self._send_error_json(exc, HTTPStatus.CONFLICT)
        elif isinstance(exc, (KeyError, FileNotFoundError)):
            self._send_error_json(exc, HTTPStatus.NOT_FOUND)
        elif isinstance(exc, PermissionError):
            self._send_error_json(exc, HTTPStatus.FORBIDDEN)
        else:
            self._send_error_json(exc)

    def _send_empty_response(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self._send_cors()
        self.send_header("Content-Length", "0")
        try:
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def _enqueue_background_task(
        self,
        *,
        kind: str,
        title: str,
        message: str,
        worker: Callable[[str], Any],
        task_updates: dict[str, Any] | None = None,
        cleanup: Callable[[], None] | None = None,
    ) -> None:
        try:
            task = _create_task(self.state, kind=kind, title=title, message=message)
            task_id = str(task["id"])
            if task_updates:
                _update_task(self.state, task_id, **task_updates)

            def run_task() -> None:
                try:
                    _run_background_task(
                        self.state,
                        task_id,
                        lambda: worker(task_id),
                    )
                finally:
                    if cleanup is not None:
                        cleanup()

            thread = threading.Thread(target=run_task, daemon=True)
            thread.start()
        except Exception:
            if cleanup is not None:
                cleanup()
            raise
        self._send_json(_get_task(self.state, task_id), HTTPStatus.ACCEPTED)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("request body must be a JSON object")
        return data

    def _try_dispatch_registered_route(
        self,
        method: str,
        path: str,
        query_string: str,
    ) -> bool:
        matched = self.api_router.match(method, path)
        if matched is None:
            return False

        uploads: UploadedFiles | None = None
        try:
            if matched.route.body_kind is BodyKind.JSON:
                body = self._read_json()
            else:
                body = {}
            if matched.route.body_kind is BodyKind.MULTIPART:
                uploads = self._read_upload_files()
            auth_plugin_id = (
                self._authenticated_plugin_id()
                if hasattr(self, "_authenticated_plugin_id")
                else None
            )
            request = ApiRequest(
                state=self.state,
                method=method,
                path=path,
                query=parse_qs(query_string),
                params=matched.params,
                body=body,
                uploads=uploads,
                auth_plugin_id=auth_plugin_id,
            )
            response = matched.route.handler(request)
            if isinstance(response, TaskResponse):
                guard = (
                    response.enqueue_guard()
                    if response.enqueue_guard is not None
                    else nullcontext()
                )
                with guard:
                    existing = (
                        response.find_existing()
                        if response.find_existing is not None
                        else None
                    )
                    if existing is not None:
                        self._send_json(existing, HTTPStatus.ACCEPTED)
                    else:
                        cleanup = (
                            uploads.transfer_cleanup() if uploads is not None else None
                        )
                        self._enqueue_background_task(
                            kind=response.kind,
                            title=response.title,
                            message=response.message,
                            worker=response.worker,
                            task_updates=(
                                dict(response.task_updates)
                                if response.task_updates is not None
                                else None
                            ),
                            cleanup=cleanup,
                        )
            else:
                self._send_json(response.data, response.status)
        finally:
            if uploads is not None:
                uploads.cleanup()
        return True

    def _read_upload_files(self) -> UploadedFiles:
        return read_uploaded_files(
            self.headers.get("Content-Type", ""),
            self.headers.get("Content-Length", ""),
            self.rfile,
        )

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._request_origin_allowed():
            self.send_response(HTTPStatus.FORBIDDEN)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors()
        self.end_headers()
