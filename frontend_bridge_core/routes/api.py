from __future__ import annotations

from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from frontend_bridge_core.chat_session import (
    CHAT_RUNTIME_READY_TIMEOUT_SECONDS,
    launch_chat as launch_chat_session,
    resume_last_chat as resume_last_chat_session,
    start_chat_initialization,
    wait_for_chat_runtime_ready,
)
from frontend_bridge_core.routes.background_routes import BACKGROUND_ROUTES
from frontend_bridge_core.routes.character_routes import CHARACTER_ROUTES
from frontend_bridge_core.routes.chat_routes import CHAT_ROUTES
from frontend_bridge_core.routes.effect_routes import EFFECT_ROUTES
from frontend_bridge_core.routes.file_transport import (
    FileTransport,
    dispatch_file_request,
)
from frontend_bridge_core.routes.http_handler import (
    BRIDGE_AUTH_COOKIE,
    BRIDGE_AUTH_HEADER,
    BRIDGE_AUTH_QUERY,
    BridgeHttpHandler,
)
from frontend_bridge_core.routes.memory_routes import MEMORY_ROUTES
from frontend_bridge_core.routes.model_asset_routes import MODEL_ASSET_ROUTES
from frontend_bridge_core.routes.operation_routes import OPERATION_ROUTES
from frontend_bridge_core.routes.plugin_routes import PLUGIN_ROUTES
from frontend_bridge_core.routes.router import Router
from frontend_bridge_core.routes.system_routes import SYSTEM_ROUTES
from frontend_bridge_core.routes.story_routes import STORY_ROUTES
from frontend_bridge_core.routes.template_routes import TEMPLATE_ROUTES
from frontend_bridge_core.routes.transfer_routes import TRANSFER_ROUTES
from frontend_bridge_core.routes.utility_routes import UTILITY_ROUTES

__all__ = [
    "BRIDGE_AUTH_COOKIE",
    "BRIDGE_AUTH_HEADER",
    "BRIDGE_AUTH_QUERY",
    "FrontendBridgeHandler",
]

_API_ROUTER = Router(
    [
        *SYSTEM_ROUTES,
        *STORY_ROUTES,
        *CHARACTER_ROUTES,
        *CHAT_ROUTES,
        *BACKGROUND_ROUTES,
        *EFFECT_ROUTES,
        *MEMORY_ROUTES,
        *MODEL_ASSET_ROUTES,
        *TEMPLATE_ROUTES,
        *OPERATION_ROUTES,
        *PLUGIN_ROUTES,
        *TRANSFER_ROUTES,
        *UTILITY_ROUTES,
    ]
)


class FrontendBridgeHandler(BridgeHttpHandler):
    api_router = _API_ROUTER

    def _wait_for_chat_runtime_ready(
        self,
        stream_info: dict[str, Any],
        *,
        timeout: float = CHAT_RUNTIME_READY_TIMEOUT_SECONDS,
    ) -> None:
        wait_for_chat_runtime_ready(self.state, stream_info, timeout=timeout)

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            self._require_authorized_read(path)
            if self._try_dispatch_registered_route("GET", path, parsed.query):
                return
            if dispatch_file_request(
                self,
                path,
                parsed.query,
                send_body=True,
            ):
                return
            self._send_error_json(FileNotFoundError(path), HTTPStatus.NOT_FOUND)
        except Exception as exc:
            if self._is_client_disconnect(exc):
                return
            self._log_request_exception(exc)
            self._send_exception_json(exc)

    def do_HEAD(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            self._require_authorized_read(path)
            if dispatch_file_request(
                self,
                path,
                parsed.query,
                send_body=False,
            ):
                return
            self._send_empty_response(HTTPStatus.NOT_FOUND)
        except FileNotFoundError:
            self._send_empty_response(HTTPStatus.NOT_FOUND)
        except PermissionError:
            self._send_empty_response(HTTPStatus.FORBIDDEN)
        except Exception as exc:
            if self._is_client_disconnect(exc):
                return
            self._log_request_exception(exc)
            self._send_empty_response(HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        self._handle_write("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._handle_write("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle_write("DELETE")

    def _handle_write(self, method: str) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            self._require_authorized_write(path)
            if self._try_dispatch_registered_route(method, path, parsed.query):
                return
            self._send_error_json(FileNotFoundError(path), HTTPStatus.NOT_FOUND)
        except Exception as exc:
            if self._is_client_disconnect(exc):
                return
            self._log_request_exception(exc)
            self._send_exception_json(exc)

    def _start_chat_init(self, body: dict[str, Any]) -> dict[str, Any]:
        return start_chat_initialization(self.state, body)

    def _launch_chat(
        self,
        body: dict[str, Any],
        *,
        init_stream_info: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return launch_chat_session(
            self.state,
            body,
            init_stream_info=init_stream_info,
        )

    def _resume_last_chat(
        self,
        *,
        init_stream_info: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return resume_last_chat_session(
            self.state,
            init_stream_info=init_stream_info,
        )

    def _resolve_project_path(self, raw_path: str) -> Path:
        return FileTransport(self).resolve_project_path(raw_path)

    def _resolve_media_path(self, raw_path: str) -> Path:
        return FileTransport(self).resolve_media_path(raw_path)

    def _resolve_static_path(self, root: Path, request_path: str) -> Path:
        return FileTransport.resolve_static_path(root, request_path)

    def _media_thumbnail_batch_response(self, body: dict[str, Any]) -> dict[str, Any]:
        return FileTransport.media_thumbnail_batch_response(body)

    def _send_local_file(
        self,
        path: Path,
        *,
        attachment: bool = False,
        send_body: bool = True,
    ) -> None:
        FileTransport(self).send_local_file(
            path,
            attachment=attachment,
            send_body=send_body,
        )

    def _send_range_not_satisfiable(self, file_size: int) -> None:
        FileTransport(self).send_range_not_satisfiable(file_size)

    def _parse_byte_range(
        self, range_header: str | None, file_size: int
    ) -> tuple[int, int] | None:
        return FileTransport.parse_byte_range(range_header, file_size)

    def _try_send_frontend(self, request_path: str, *, send_body: bool = True) -> bool:
        return FileTransport(self).try_send_frontend(
            request_path,
            send_body=send_body,
        )

    def _send_file(
        self,
        relative_path: str,
        *,
        attachment: bool = False,
        send_body: bool = True,
    ) -> None:
        FileTransport(self).send_file(
            relative_path,
            attachment=attachment,
            send_body=send_body,
        )

    def _send_media_file(
        self,
        path: str,
        *,
        send_body: bool = True,
    ) -> None:
        FileTransport(self).send_media_file(
            path,
            send_body=send_body,
        )

    def _send_media_thumbnail(
        self,
        relative_path: str,
        size: str,
        *,
        send_body: bool = True,
    ) -> None:
        FileTransport(self).send_media_thumbnail(
            relative_path,
            size,
            send_body=send_body,
        )
