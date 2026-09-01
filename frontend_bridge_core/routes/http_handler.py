from __future__ import annotations

import hmac
import ipaddress
import json
import threading
from contextlib import nullcontext
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse, urlunparse

from sdk.logging import get_logger, log_context, new_log_id
from sdk.path_utils import reject_control_chars

from application.chat.templates import NoValidCharactersError
from application.runtime.state import BridgeState, _jsonify
from application.runtime.tasks import (
    _create_task,
    _get_task,
    _run_background_task,
    _update_task,
)
from frontend_bridge_core.routes.plugin_routes import inject_bridge_token
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    Router,
    TaskResponse,
)
from frontend_bridge_core.routes.uploads import UploadedFiles, read_uploaded_files
from frontend_bridge_core.security import safe_header_value

logger = get_logger("frontend_bridge_core.routes.api")

BRIDGE_AUTH_HEADER = "X-Shinsekai-Bridge-Token"
BRIDGE_AUTH_QUERY = "shinsekai_bridge_token"
BRIDGE_AUTH_COOKIE = "shinsekai_bridge_token"

_ALLOWED_CUSTOM_ORIGIN_SCHEMES = {"shinsekai", "tauri"}
_ALLOWED_LOCAL_ORIGIN_HOSTS = {"127.0.0.1", "::1", "localhost", "tauri.localhost"}
_POLLING_PATHS = {
    "/api/characters/memories/status",
    "/api/health",
    "/api/chat/runtime-status",
    "/api/chat/snapshot",
    "/api/memory/status",
    "/api/model-assets/status",
    "/api/plugins/status",
}


class BridgeHttpHandler(BaseHTTPRequestHandler):
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

        is_polling_request = path in _POLLING_PATHS or (
            method in {"GET", "HEAD", "OPTIONS"}
            and path.startswith("/api/tasks/")
            and not path.endswith("/cancel")
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
            (KeyError, FileExistsError, FileNotFoundError, PermissionError, ValueError),
        ):
            logger.warning("Frontend bridge request failed: %s", exc, extra=extra)
        else:
            logger.exception("Frontend bridge request failed", extra=extra)

    def _origin_allowed(self, origin: str) -> bool:
        return self._allowed_origin_header(origin) is not None

    def _allowed_origin_header(self, origin: str) -> str | None:
        value = str(origin or "").strip()
        if not value:
            return ""
        try:
            value = reject_control_chars(value, field="origin")
        except ValueError:
            return None
        parsed = urlparse(value)
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower()
        if scheme in _ALLOWED_CUSTOM_ORIGIN_SCHEMES:
            if host not in _ALLOWED_LOCAL_ORIGIN_HOSTS:
                return None
            if (
                parsed.path not in {"", "/"}
                or parsed.params
                or parsed.query
                or parsed.fragment
            ):
                return None
            netloc = host
            if parsed.port is not None:
                netloc = f"{host}:{parsed.port}"
            return safe_header_value(urlunparse((scheme, netloc, "", "", "", "")))
        if scheme in {"http", "https"}:
            if (
                parsed.path not in {"", "/"}
                or parsed.params
                or parsed.query
                or parsed.fragment
            ):
                return None
            if (
                host not in _ALLOWED_LOCAL_ORIGIN_HOSTS
                and not self._origin_matches_request_host(parsed)
            ):
                return None
            netloc = host
            if parsed.port is not None:
                netloc = f"{host}:{parsed.port}"
            return safe_header_value(urlunparse((scheme, netloc, "", "", "", "")))
        return None

    def _origin_matches_request_host(self, parsed_origin) -> bool:
        try:
            raw_host = reject_control_chars(
                str(self.headers.get("Host") or ""),
                field="host",
            )
            request = urlparse(f"//{raw_host}")
            request_host = str(request.hostname or "").lower()
            origin_host = str(parsed_origin.hostname or "").lower()
            if not request_host or request_host != origin_host:
                return False
            request_port = request.port or (
                443 if parsed_origin.scheme == "https" else 80
            )
            origin_port = parsed_origin.port or (
                443 if parsed_origin.scheme == "https" else 80
            )
            return request_port == origin_port
        except (TypeError, ValueError):
            return False

    def _request_origin_allowed(self) -> bool:
        origin = self.headers.get("Origin", "")
        if not str(origin or "").strip():
            return True
        return self._allowed_origin_header(origin) is not None

    def _auth_token_from_request(self) -> str:
        header_token = str(self.headers.get(BRIDGE_AUTH_HEADER) or "").strip()
        if header_token:
            return header_token
        parsed = urlparse(getattr(self, "path", ""))
        query = parse_qs(parsed.query)
        query_token = str(
            (query.get(BRIDGE_AUTH_QUERY) or query.get("token") or [""])[0]
        ).strip()
        if query_token:
            return query_token
        cookie = SimpleCookie()
        try:
            cookie.load(str(self.headers.get("Cookie") or ""))
        except Exception:
            return ""
        morsel = cookie.get(BRIDGE_AUTH_COOKIE)
        return str(morsel.value if morsel is not None else "").strip()

    def _has_valid_auth_token(self) -> bool:
        required = str(getattr(self.state, "auth_token", "") or "").strip()
        if not required:
            return True
        supplied = self._auth_token_from_request()
        return bool(supplied) and hmac.compare_digest(supplied, required)

    def _is_loopback_client(self) -> bool:
        client_address = getattr(self, "client_address", None)
        if not client_address:
            # Directly constructed handlers are used by internal integrations
            # and unit tests without a network peer.
            return True
        try:
            return ipaddress.ip_address(str(client_address[0])).is_loopback
        except (IndexError, TypeError, ValueError):
            return False

    def _require_authorized_read(self, path: str) -> None:
        # Project-backed static roots share the same LAN authorization boundary
        # as APIs. Protecting /assets/ also closes alternate spellings such as
        # /assets/../data/... before path normalization reaches file transport.
        protected_path = path.startswith(("/api/", "/assets/", "/data/"))
        if (
            protected_path
            and not self._is_loopback_client()
            and not self._has_valid_auth_token()
        ):
            raise PermissionError("invalid bridge auth token")

    def _inject_bridge_token(self, detail: dict[str, Any]) -> dict[str, Any]:
        return inject_bridge_token(self.state, detail)

    def _require_authorized_write(self, path: str) -> None:
        if not self._request_origin_allowed():
            raise PermissionError("request origin is not allowed")
        if path.startswith("/api/") and not self._has_valid_auth_token():
            raise PermissionError("invalid bridge auth token")

    def _require_authorized_media_read(self) -> None:
        if not self._request_origin_allowed():
            raise PermissionError("request origin is not allowed")
        if not self._has_valid_auth_token():
            raise PermissionError("invalid bridge auth token")

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
    ) -> None:
        payload = {"error": str(exc), "type": exc.__class__.__name__}
        if error_code:
            payload["errorCode"] = error_code
        self._send_json(payload, status)

    def _send_exception_json(self, exc: Exception) -> None:
        if isinstance(exc, NoValidCharactersError):
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
            request = ApiRequest(
                state=self.state,
                method=method,
                path=path,
                query=parse_qs(query_string),
                params=matched.params,
                body=body,
                uploads=uploads,
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
