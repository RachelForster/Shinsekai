from __future__ import annotations

import hmac
import ipaddress
import json
import mimetypes
import shutil
import tempfile
import threading
from http.cookies import SimpleCookie
from email.parser import BytesParser
from email.policy import default as default_email_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

from sdk.logging import get_logger, log_context, new_log_id

from frontend_bridge_core.effects import (
    _build_effect_usage_guide,
    _effect_dir,
    _validate_effect_storage_name,
)
from application.chat.runtime_process import (
    _chat_history,
    _chat_history_download_file,
    _close_chat,
    TRANSPARENT_BACKGROUND_NAME,
    _chat_history_path,
    _chat_process_running,
    _chat_runtime_closing,
    _chat_runtime_mode,
    _chat_runtime_status,
    _chat_snapshot,
    _chat_stream_initial_snapshot,
    _chat_theme_payload,
    _handle_chat_command,
    _launch_chat,
    remove_chat_history_storage,
    _sanitize_user_display_name,
)
from frontend_bridge_core.chat_themes import (
    delete_chat_theme,
    get_active_chat_theme_id,
    get_chat_theme_manifest,
    install_theme_from_zip,
    list_chat_themes,
    save_chat_theme,
    set_active_chat_theme,
)
from application.chat.initialization import start_chat_init
from application.chat.mobile_access import configure_mobile_access
from frontend_bridge_core.characters import _as_character_config
from frontend_bridge_core.memory import (
    _preview_character_memory_import,
    _run_character_memory_import,
)
from application.model_assets.service import (
    _download_model_asset,
    _find_running_model_asset_task,
    _model_asset_enqueue_guard,
    _resolve_model_asset,
)
from application.diagnostics.logs import (
    _default_log_snapshot,
    _diagnostic_bundle,
    _log_file_list,
    _log_snapshot,
)
from frontend_bridge_core.media import _media_thumbnail, _media_thumbnail_batch
from frontend_bridge_core.media_paths import (
    is_absolute_local_media_path_text,
    iter_configured_external_media_paths,
    resolve_external_media_file,
    validate_readable_media_file,
)
from frontend_bridge_core.plugin_ui import _resolve_plugin_frontend_file
from application.runtime.dependencies import runtime_dependency_error_from_text
from frontend_bridge_core.security import (
    safe_content_disposition,
    safe_header_value,
)
from sdk.path_utils import (
    reject_control_chars,
    safe_child_path,
    safe_filename,
    safe_project_path,
)
from application.runtime.state import BridgeState, _jsonify
from frontend_bridge_core.static import _frontend_dist_root
from application.runtime.tasks import (
    _create_task,
    _get_task,
    _run_background_task,
    _update_task,
)
from application.chat.templates import (
    NoValidCharactersError,
    _compose_for_llm,
    _latest_history_json,
    _list_templates,
    _repair_template_parts_from_session_if_needed,
    _resolve_template_character_names,
    _resume_template_parts,
    _scenario_from_template_like,
    _load_template_session_payload,
    initial_sprite_path_for_characters,
)
from application.media.attachments import stage_uploaded_chat_attachments
from frontend_bridge_core.tools import _browse_local_files
from frontend_bridge_core.routes.background_routes import BACKGROUND_ROUTES
from frontend_bridge_core.routes.character_routes import CHARACTER_ROUTES
from frontend_bridge_core.routes.effect_routes import EFFECT_ROUTES
from frontend_bridge_core.routes.memory_routes import MEMORY_ROUTES
from frontend_bridge_core.routes.operation_routes import OPERATION_ROUTES
from frontend_bridge_core.routes.plugin_routes import (
    PLUGIN_ROUTES,
    inject_bridge_token,
)
from frontend_bridge_core.routes.router import ApiRequest, BodyKind, Router, TaskResponse
from frontend_bridge_core.routes.system_routes import SYSTEM_ROUTES
from frontend_bridge_core.routes.template_routes import TEMPLATE_ROUTES

logger = get_logger("frontend_bridge_core.routes.api")
BRIDGE_AUTH_HEADER = "X-Shinsekai-Bridge-Token"
BRIDGE_AUTH_QUERY = "shinsekai_bridge_token"
BRIDGE_AUTH_COOKIE = "shinsekai_bridge_token"
_ALLOWED_CUSTOM_ORIGIN_SCHEMES = {"shinsekai", "tauri"}
_ALLOWED_LOCAL_ORIGIN_HOSTS = {"127.0.0.1", "::1", "localhost", "tauri.localhost"}

CHAT_RUNTIME_READY_TIMEOUT_SECONDS = 20.0
_POLLING_PATHS = {
    "/api/characters/memories/status",
    "/api/health",
    "/api/chat/runtime-status",
    "/api/chat/snapshot",
    "/api/memory/status",
    "/api/model-assets/status",
    "/api/plugins/status",
}
_API_ROUTER = Router(
    [
        *SYSTEM_ROUTES,
        *CHARACTER_ROUTES,
        *BACKGROUND_ROUTES,
        *EFFECT_ROUTES,
        *MEMORY_ROUTES,
        *TEMPLATE_ROUTES,
        *OPERATION_ROUTES,
        *PLUGIN_ROUTES,
    ]
)


def _safe_export_output_path(name: str, suffix: str) -> tuple[Path, str]:
    project_root = Path.cwd().resolve(strict=False)
    output_root = safe_project_path("output", root=project_root)
    output_root.mkdir(parents=True, exist_ok=True)
    output = safe_child_path(output_root, safe_filename(f"{name}{suffix}"))
    return output, output.relative_to(project_root).as_posix()


class _RangeNotSatisfiable(Exception):
    pass


class FrontendBridgeHandler(BaseHTTPRequestHandler):
    server_version = "ShinsekaiFrontendBridge/0.1"

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

        log = logger.error if status >= 500 else logger.warning if status >= 400 else logger.info
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
            if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
                return None
            netloc = host
            if parsed.port is not None:
                netloc = f"{host}:{parsed.port}"
            return safe_header_value(urlunparse((scheme, netloc, "", "", "", "")))
        if scheme in {"http", "https"}:
            if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
                return None
            if host not in _ALLOWED_LOCAL_ORIGIN_HOSTS and not self._origin_matches_request_host(parsed):
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
            request_port = request.port or (443 if parsed_origin.scheme == "https" else 80)
            origin_port = parsed_origin.port or (443 if parsed_origin.scheme == "https" else 80)
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
        # /assets/../data/... before path normalization reaches _send_file.
        protected_path = path.startswith(("/api/", "/assets/", "/data/"))
        if protected_path and not self._is_loopback_client() and not self._has_valid_auth_token():
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
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", f"Content-Type, Range, X-Task-Id, {BRIDGE_AUTH_HEADER}")
        self.send_header("Access-Control-Expose-Headers", "Accept-Ranges, Content-Length, Content-Range")
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
                f"{BRIDGE_AUTH_COOKIE}={safe_header_value(query_token)}; Path=/; HttpOnly; SameSite=Strict",
            )

    @staticmethod
    def _is_client_disconnect(exc: Exception) -> bool:
        return isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError))

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

    def _wait_for_chat_runtime_ready(
        self,
        stream_info: dict[str, Any],
        *,
        timeout: float = CHAT_RUNTIME_READY_TIMEOUT_SECONDS,
    ) -> None:
        session_id = str(stream_info.get("sessionId") or "").strip()
        chat_stream = getattr(self.state, "chat_stream", None)
        if not session_id or chat_stream is None:
            return
        wait_for_producer = getattr(chat_stream, "wait_for_producer", None)
        if wait_for_producer is None:
            return
        if wait_for_producer(session_id, timeout=timeout):
            return
        try:
            _close_chat(self.state, reason="聊天会话启动超时。")
        finally:
            chat_stream.delete_session(session_id)
            self.state.chat_session = {**self.state.chat_session, "sessionId": ""}
        raise RuntimeError("启动失败: 实时聊天会话未就绪，请稍后重试。")

    def _enqueue_background_task(
        self,
        *,
        kind: str,
        title: str,
        message: str,
        worker: Callable[[str], Any],
        task_updates: dict[str, Any] | None = None,
    ) -> None:
        task = _create_task(self.state, kind=kind, title=title, message=message)
        task_id = str(task["id"])
        if task_updates:
            _update_task(self.state, task_id, **task_updates)
        thread = threading.Thread(
            target=_run_background_task,
            args=(self.state, task_id, lambda: worker(task_id)),
            daemon=True,
        )
        thread.start()
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
        matched = _API_ROUTER.match(method, path)
        if matched is None:
            return False

        body = self._read_json() if matched.route.body_kind is BodyKind.JSON else {}
        request = ApiRequest(
            state=self.state,
            method=method,
            path=path,
            query=parse_qs(query_string),
            params=matched.params,
            body=body,
        )
        response = matched.route.handler(request)
        if isinstance(response, TaskResponse):
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
            )
        else:
            self._send_json(response.data, response.status)
        return True

    def _read_upload_files(self) -> tuple[Path, list[Path]]:
        ctype = self.headers.get("Content-Type", "")
        if not ctype.lower().startswith("multipart/form-data"):
            raise ValueError("request must be multipart/form-data")
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            raise ValueError("request body is empty")
        temp_dir = Path(tempfile.mkdtemp(prefix="shinsekai-frontend-upload-"))
        body = self.rfile.read(length)
        message = BytesParser(policy=default_email_policy).parsebytes(
            f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
        )
        paths: list[Path] = []
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            if part.get_param("name", header="content-disposition") != "files":
                continue
            try:
                filename = safe_filename(str(part.get_filename() or ""))
            except ValueError:
                continue
            dest = safe_child_path(temp_dir, filename)
            dest.write_bytes(part.get_payload(decode=True) or b"")
            paths.append(dest)
        if not paths:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise ValueError("no files uploaded")
        return temp_dir, paths

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._request_origin_allowed():
            self.send_response(HTTPStatus.FORBIDDEN)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            self._require_authorized_read(path)
            if self._try_dispatch_registered_route("GET", path, parsed.query):
                return
            if path == "/api/logs/default":
                self._send_json(_default_log_snapshot(Path.cwd().resolve()))
            elif path == "/api/logs":
                self._send_json(_log_file_list(Path.cwd().resolve()))
            elif path.startswith("/api/plugins/") and "/frontend/" in path:
                rest = path[len("/api/plugins/") :]
                plugin_part, _, frontend_tail = rest.partition("/frontend/")
                page_part, _, asset_part = frontend_tail.partition("/")
                self._send_local_file(
                    _resolve_plugin_frontend_file(
                        unquote(plugin_part),
                        unquote(page_part),
                        unquote(asset_part),
                    ),
                    send_body=True,
                )
            elif path == "/api/chat/runtime-status":
                self._send_json(_chat_runtime_status(self.state))
            elif path == "/api/chat/snapshot":
                query = parse_qs(parsed.query)
                renderer_id = str((query.get("rendererId") or [""])[0]).strip()[:128]
                self._send_json(_chat_snapshot(self.state, renderer_id=renderer_id))
            elif path == "/api/chat/history":
                self._send_json(_chat_history(self.state))
            elif path == "/api/chat/history-file":
                if not self._request_origin_allowed():
                    raise PermissionError("request origin is not allowed")
                query = parse_qs(parsed.query)
                capability = str((query.get("cap") or [""])[0])
                self._send_local_file(
                    _chat_history_download_file(self.state, capability),
                    attachment=True,
                )
            elif path == "/api/chat/theme":
                self._send_json(_chat_theme_payload(self.state))
            elif path == "/api/chat/themes":
                self._send_json(list_chat_themes(self.state))
            elif path == "/api/chat/themes/active":
                self._send_json(get_active_chat_theme_id(self.state))
            elif path.startswith("/api/chat/themes/"):
                theme_id = unquote(path[len("/api/chat/themes/"):])
                self._send_json(get_chat_theme_manifest(self.state, theme_id))
            elif path == "/api/download":
                query = parse_qs(parsed.query)
                target = unquote((query.get("path") or [""])[0])
                self._send_file(target, attachment=True)
            elif path == "/api/media":
                self._require_authorized_media_read()
                query = parse_qs(parsed.query)
                target = unquote((query.get("path") or [""])[0])
                self._send_media_file(target)
            elif path == "/api/media/thumbnail":
                query = parse_qs(parsed.query)
                target = unquote((query.get("path") or [""])[0])
                size = (query.get("size") or ["160"])[0]
                self._send_media_thumbnail(target, size)
            elif path.startswith("/assets/") or path.startswith("/data/"):
                self._send_file(path.lstrip("/"))
            elif self._try_send_frontend(path):
                return
            else:
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
            if path == "/api/chat/history-file":
                if not self._request_origin_allowed():
                    raise PermissionError("request origin is not allowed")
                query = parse_qs(parsed.query)
                capability = str((query.get("cap") or [""])[0])
                self._send_local_file(
                    _chat_history_download_file(self.state, capability),
                    attachment=True,
                    send_body=False,
                )
            elif path == "/api/download":
                query = parse_qs(parsed.query)
                target = unquote((query.get("path") or [""])[0])
                self._send_file(target, attachment=True, send_body=False)
            elif path == "/api/media":
                self._require_authorized_media_read()
                query = parse_qs(parsed.query)
                target = unquote((query.get("path") or [""])[0])
                self._send_media_file(target, send_body=False)
            elif path == "/api/media/thumbnail":
                query = parse_qs(parsed.query)
                target = unquote((query.get("path") or [""])[0])
                size = (query.get("size") or ["160"])[0]
                self._send_media_thumbnail(target, size, send_body=False)
            elif path.startswith("/api/plugins/") and "/frontend/" in path:
                rest = path[len("/api/plugins/") :]
                plugin_part, _, frontend_tail = rest.partition("/frontend/")
                page_part, _, asset_part = frontend_tail.partition("/")
                self._send_local_file(
                    _resolve_plugin_frontend_file(
                        unquote(plugin_part),
                        unquote(page_part),
                        unquote(asset_part),
                    ),
                    send_body=False,
                )
            elif path.startswith("/assets/") or path.startswith("/data/"):
                self._send_file(path.lstrip("/"), send_body=False)
            elif self._try_send_frontend(path, send_body=False):
                return
            else:
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
            is_upload = method == "POST" and path in {
                "/api/characters/import-upload",
                "/api/characters/memories/import-preview-upload",
                "/api/characters/memories/import-upload",
                "/api/backgrounds/import-upload",
                "/api/logs/import-upload",
                "/api/chat/themes/upload",
                "/api/chat/attachments/upload",
            }
            body = {} if method == "DELETE" or is_upload else self._read_json()
            if method == "POST" and path == "/api/files/browse":
                self._send_json(_browse_local_files(self.state, body))
            elif method == "POST" and path == "/api/media/thumbnails":
                self._send_json(self._media_thumbnail_batch_response(body))
            elif method == "POST" and path == "/api/logs/read":
                project_root = Path.cwd().resolve()
                self._send_json(
                    _log_snapshot(
                        self._resolve_project_path(str(body.get("path") or "")),
                        roots=(project_root,),
                    )
                )
            elif method == "POST" and path == "/api/logs/import-upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    self._send_json(_log_snapshot(paths[0], roots=(temp_dir,)))
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            elif method == "POST" and path == "/api/logs/diagnostic-bundle":
                self._send_json(_diagnostic_bundle(Path.cwd().resolve()))
            elif method == "POST" and path == "/api/model-assets/download":
                spec = _resolve_model_asset(self.state, body)
                with _model_asset_enqueue_guard():
                    existing = _find_running_model_asset_task(self.state, spec.task_key)
                    if existing is not None:
                        self._send_json(existing, HTTPStatus.ACCEPTED)
                    else:
                        self._enqueue_background_task(
                            kind="model-download",
                            title=spec.title,
                            message=f"{spec.title} download queued.",
                            task_updates={
                                "assetId": spec.asset_id,
                                "assetKey": spec.task_key,
                                "variant": spec.variant,
                            },
                            worker=lambda task_id: _download_model_asset(self.state, task_id, spec),
                        )
            elif method == "POST" and path == "/api/characters/memories/import-preview-upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    query = parse_qs(urlparse(self.path).query)
                    name = str((query.get("name") or [""])[0])
                    self._send_json(
                        _preview_character_memory_import(
                            self.state,
                            name,
                            paths,
                            source_root=temp_dir,
                        )
                    )
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            elif method == "POST" and path == "/api/characters/memories/import-upload":
                temp_dir, paths = self._read_upload_files()
                query = parse_qs(urlparse(self.path).query)
                name = str((query.get("name") or [""])[0]).strip()

                def run_uploaded_memory_import(task_id: str) -> dict[str, Any]:
                    try:
                        return _run_character_memory_import(
                            self.state,
                            task_id,
                            name,
                            paths,
                            source_root=temp_dir,
                        )
                    finally:
                        shutil.rmtree(temp_dir, ignore_errors=True)

                try:
                    self._enqueue_background_task(
                        kind="memory-import",
                        title=f"导入 {name or '角色'} 的长期记忆",
                        message="长期记忆导入任务已排队。",
                        worker=run_uploaded_memory_import,
                    )
                except Exception:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    raise
            elif method == "DELETE" and path.startswith("/api/chat/themes/"):
                theme_id = unquote(path[len("/api/chat/themes/"):])
                self._send_json(delete_chat_theme(self.state, theme_id))
            elif method == "POST" and path == "/api/characters/import":
                paths = body.get("paths") or []
                if not isinstance(paths, list):
                    raise ValueError("paths must be a list")
                import tools.file_util as file_util

                imported = []
                for item in paths:
                    imported.extend(file_util.import_character(str(item)))
                self.state.config_manager.reload()
                self._send_json([item.__dict__ for item in imported])
            elif method == "POST" and path == "/api/characters/import-upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    import tools.file_util as file_util

                    imported = []
                    for item in paths:
                        imported.extend(file_util.import_character(str(item)))
                    self.state.config_manager.reload()
                    self._send_json([item.__dict__ for item in imported])
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            elif method == "POST" and path == "/api/characters/export":
                name = str(body.get("name") or "")
                character = self.state.config_manager.get_character_by_name(name)
                if character is None:
                    raise KeyError(f"character not found: {name}")
                output, output_relative = _safe_export_output_path(name, ".char")
                import tools.file_util as file_util

                file_util.export_character([_as_character_config(character)], output.as_posix(), open_folder=False)
                self._send_json(
                    {
                        "downloadUrl": f"/api/download?path={output_relative}",
                        "path": output_relative,
                    }
                )
            elif method == "POST" and path == "/api/backgrounds/import":
                paths = body.get("paths") or []
                if not isinstance(paths, list):
                    raise ValueError("paths must be a list")
                self._send_json(self._import_background_paths([str(item) for item in paths]))
            elif method == "POST" and path == "/api/backgrounds/import-upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    self._send_json(self._import_background_paths([str(item) for item in paths]))
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            elif method == "POST" and path == "/api/backgrounds/export":
                name = str(body.get("name") or "")
                background = self.state.config_manager.get_background_by_name(name)
                if background is None:
                    raise KeyError(f"background not found: {name}")
                output, output_relative = _safe_export_output_path(name, ".bg")
                import tools.file_util as file_util

                file_util.export_background([background], output.as_posix(), open_folder=False)
                self._send_json(
                    {
                        "downloadUrl": f"/api/download?path={output_relative}",
                        "path": output_relative,
                    }
                )
            elif method == "POST" and path == "/api/effects/import":
                paths = body.get("paths") or []
                if not isinstance(paths, list):
                    raise ValueError("paths must be a list")
                self._send_json(self._import_effect_paths([str(item) for item in paths]))
            elif method == "POST" and path == "/api/effects/import-upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    self._send_json(self._import_effect_paths([str(item) for item in paths]))
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            elif method == "POST" and path == "/api/effects/export":
                name = _validate_effect_storage_name(str(body.get("name") or ""))
                effect = self.state.config_manager.get_effect_by_name(name)
                if effect is None:
                    raise KeyError(f"effect not found: {name}")
                output, output_relative = _safe_export_output_path(name, ".ef")
                import tools.file_util as file_util

                file_util.export_effect([effect], output.as_posix(), open_folder=False)
                self._send_json(
                    {
                        "downloadUrl": f"/api/download?path={output_relative}",
                        "path": output_relative,
                    }
                )
            elif method == "POST" and path == "/api/chat/launch":
                self._send_json(self._launch_chat(body))
            elif method == "POST" and path == "/api/chat/resume-last":
                self._send_json(self._resume_last_chat())
            elif method == "POST" and path == "/api/chat/init":
                self._send_json(self._start_chat_init(body), HTTPStatus.ACCEPTED)
            elif method == "POST" and path == "/api/chat/close":
                self._send_json(_close_chat(self.state))
            elif method == "POST" and path == "/api/chat/command":
                self._send_json(_handle_chat_command(self.state, body))
            elif method == "POST" and path == "/api/chat/themes/active":
                self._send_json(set_active_chat_theme(self.state, body))
            elif method == "POST" and path == "/api/chat/themes/save":
                self._send_json(save_chat_theme(self.state, body))
            elif method == "POST" and path == "/api/chat/themes/upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    if not paths:
                        raise ValueError("未收到主题压缩包")
                    self._send_json(install_theme_from_zip(self.state, paths[0]))
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            elif method == "POST" and path == "/api/chat/attachments/upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    self._send_json({"attachments": stage_uploaded_chat_attachments(paths)})
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            else:
                self._send_error_json(FileNotFoundError(path), HTTPStatus.NOT_FOUND)
        except Exception as exc:
            if self._is_client_disconnect(exc):
                return
            self._log_request_exception(exc)
            self._send_exception_json(exc)

    def _import_background_paths(self, paths: list[str]) -> list[dict[str, Any]]:
        import tools.file_util as file_util

        existing = self.state.config_manager.config.background_list
        imported = []
        for item in paths:
            batch = file_util.import_background(str(item), existing)
            imported.extend(batch)
            for background in batch:
                if background not in existing:
                    existing.append(background)
        self.state.config_manager.save_background_config()
        self.state.config_manager.reload()
        return [_jsonify(item) for item in imported]

    def _import_effect_paths(self, paths: list[str]) -> list[dict[str, Any]]:
        import tools.file_util as file_util

        existing = self.state.config_manager.config.effect_list
        imported = []
        for item in paths:
            batch = file_util.import_effect(str(item), existing)
            imported.extend(batch)
            for effect in batch:
                if effect not in existing:
                    existing.append(effect)
                # Ensure managed directory exists for each imported effect
                ef_dir = _effect_dir(effect.name)
                ef_dir.mkdir(parents=True, exist_ok=True)
        self.state.config_manager.save_effect_config()
        self.state.config_manager.reload()
        return [_jsonify(item) for item in imported]

    def _start_chat_init(self, body: dict[str, Any]) -> dict[str, Any]:
        mode = str(body.get("mode") or "").strip().lower()
        if mode == "launch":
            payload = body.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object when mode is 'launch'")

            def launch_request(stream_info: dict[str, str]) -> dict[str, Any]:
                return self._launch_chat(payload, init_stream_info=stream_info)

            launch = launch_request
        elif mode == "resume-last":

            def resume_request(stream_info: dict[str, str]) -> dict[str, Any]:
                return self._resume_last_chat(init_stream_info=stream_info)

            launch = resume_request
        else:
            raise ValueError("mode must be 'launch' or 'resume-last'")
        return start_chat_init(self.state, mode=mode, launch=launch)

    def _launch_chat(
        self,
        body: dict[str, Any],
        *,
        init_stream_info: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if _chat_runtime_closing(self.state):
            raise RuntimeError("聊天会话正在关闭，请稍后再启动。")
        mobile_access_enabled = bool(body.get("enableMobileAccess", False))
        if not mobile_access_enabled:
            configure_mobile_access(self.state, enabled=False)
        template_id = str(body.get("templateId") or "")
        rows = _list_templates(self.state)
        row = next((item for item in rows if item["id"] == template_id), None)
        has_inline_template = "scenario" in body or "system" in body
        if has_inline_template:
            scenario = str(body.get("scenario") or "")
            system_template = str(body.get("system") or "")
            row = {
                "content": _compose_for_llm(scenario, system_template),
                "id": template_id or "_temp.txt",
                "name": str(body.get("templateName") or template_id or "_temp"),
                "scenario": scenario,
                "system": system_template,
            }
        elif row is None:
            raise KeyError(f"template not found: {template_id}")
        characters = _resolve_template_character_names(
            self.state,
            body.get("characters") or [],
        )
        first_character = characters[0] if characters else ""
        init_sprite_path = initial_sprite_path_for_characters(
            self.state.config_manager,
            str(body.get("initSpritePath") or ""),
            characters,
        )
        room_id = str(body.get("roomId") or self.state.config_manager.config.system_config.live_room_id or "")
        normalized_history_payload = {**body, "characters": characters}
        history_path = _chat_history_path(self.state, normalized_history_payload, row)
        default_history_path = _chat_history_path(
            self.state,
            {"historyPath": "", "characters": characters},
            row,
        )
        reset_history = bool(body.get("resetHistory"))
        if reset_history:
            for item in {history_path, default_history_path}:
                remove_chat_history_storage(item)
        user_scenario = _scenario_from_template_like(row)
        system_template = str(row.get("system") or "")
        user_scenario, system_template = _repair_template_parts_from_session_if_needed(
            self.state,
            user_scenario,
            system_template,
        )
        user_display_name = _sanitize_user_display_name(body.get("userDisplayName"))
        session_base = {
            "backgroundName": str(body.get("backgroundName") or ""),
            "characterName": first_character,
            "historyPath": (default_history_path if reset_history else history_path).as_posix(),
            "sessionId": "",
            "templateId": template_id,
            "userDisplayName": user_display_name,
            "voiceLanguage": str(self.state.config_manager.config.system_config.voice_language or "ja"),
            "workflowPath": str(body.get("workflowPath") or ""),
        }
        if _chat_process_running():
            self.state.chat_session = {**self.state.chat_session, **session_base}
            configure_mobile_access(
                self.state,
                enabled=mobile_access_enabled,
            )
            return _chat_snapshot(self.state, None, "", extra={"statusMessage": "进程已经在运行中。"})
        self.state.chat_session = {**self.state.chat_session, **session_base}
        initial_snapshot = _chat_stream_initial_snapshot(_chat_snapshot(self.state, "idle", ""))
        use_react_runtime = _chat_runtime_mode(self.state) == "react"
        stream_info = init_stream_info or (
            self.state.chat_stream.create_session(initial_snapshot)
            if use_react_runtime and self.state.chat_stream is not None
            else {}
        )
        effect_names_list = body.get("effectNames") or []
        if isinstance(effect_names_list, list):
            effect_names_str = ",".join(str(n) for n in effect_names_list)
        else:
            effect_names_str = ""
        # 将选中特效方案的关键词和用法注入系统模板
        effect_guide = _build_effect_usage_guide(self.state, effect_names_list if isinstance(effect_names_list, list) else [])
        if effect_guide:
            system_template = system_template.rstrip() + "\n\n" + effect_guide
        message = _launch_chat(
            self.state,
            character_names=characters,
            effect_names=effect_names_str,
            history_file=(default_history_path if reset_history else history_path).as_posix(),
            init_sprite_path=init_sprite_path,
            room_id=room_id,
            selected_bg=str(body.get("backgroundName") or ""),
            system_template=system_template,
            use_cg=bool(body.get("useCg")),
            user_scenario=user_scenario,
            stream_endpoint=str(stream_info.get("producerEndpoint") or "") if use_react_runtime else "",
            init_stream_endpoint=str(stream_info.get("producerEndpoint") or "") if not use_react_runtime else "",
            workflow_path=str(body.get("workflowPath") or ""),
        )
        dependency_error = runtime_dependency_error_from_text(message)
        if dependency_error:
            session_id = str(stream_info.get("sessionId") or "")
            if session_id and self.state.chat_stream is not None:
                self.state.chat_stream.delete_session(session_id)
            self.state.chat_session = {**self.state.chat_session, **session_base}
            return _chat_snapshot(
                self.state,
                "error",
                message,
                extra={"runtimeDependencyError": dependency_error},
            )
        if message.startswith("启动失败"):
            session_id = str(stream_info.get("sessionId") or "")
            if session_id and self.state.chat_stream is not None:
                self.state.chat_stream.delete_session(session_id)
            raise RuntimeError(message)
        self.state.chat_session = {
            **self.state.chat_session,
            **session_base,
            "sessionId": str(stream_info.get("sessionId") or "") if use_react_runtime else "",
        }
        if use_react_runtime and stream_info.get("sessionId") and self.state.chat_stream is not None:
            self.state.chat_stream.update_session_snapshot(
                str(stream_info["sessionId"]),
                {
                    "backgroundPath": _chat_snapshot(self.state).get("backgroundPath", ""),
                    "characterName": first_character,
                    "dialogText": "",
                    "historyPath": (default_history_path if reset_history else history_path).as_posix(),
                    "status": "idle",
                    "statusMessage": message,
                    "userDisplayName": user_display_name,
                    "voiceLanguage": str(self.state.chat_session.get("voiceLanguage") or "ja"),
                },
            )
            self._wait_for_chat_runtime_ready(stream_info)
        configure_mobile_access(
            self.state,
            enabled=mobile_access_enabled,
        )
        return _chat_snapshot(
            self.state,
            "idle",
            "",
            extra={
                "statusMessage": message,
                **({"_chatInitStreamAttached": True} if init_stream_info else {}),
            },
        )

    def _resume_last_chat(
        self,
        *,
        init_stream_info: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if _chat_runtime_closing(self.state):
            raise RuntimeError("聊天会话正在关闭，请稍后再启动。")
        session = _load_template_session_payload(self.state) or {}
        mobile_access_enabled = bool(session.get("enableMobileAccess", False))
        if not mobile_access_enabled:
            configure_mobile_access(self.state, enabled=False)
        session_history_path = str(session.get("historyPath") or "").strip()
        history_path = (
            _chat_history_path(self.state, {"historyPath": session_history_path}, session)
            if session_history_path
            else _latest_history_json(self.state.history_dir)
        )
        if history_path is None:
            raise FileNotFoundError("未找到聊天记录（*.json）。请先在主窗口进行过对话。")
        template_parts = _resume_template_parts(self.state)
        session_scenario = str(session.get("scenario") or "")
        session_system = str(session.get("system") or "")
        if session_scenario.strip() or session_system.strip():
            template_parts = (
                session_scenario,
                session_system,
                str(session.get("templateFileDropdown") or "_temp.txt"),
            )
        if template_parts is None:
            raise FileNotFoundError("未找到可用模板（.txt）。请先在聊天模板页生成、保存或启动过一次。")
        scenario, system_template, template_id = template_parts
        selected_characters = _resolve_template_character_names(
            self.state,
            session.get("selectedCharacters") or [],
        )
        first_character = selected_characters[0] if selected_characters else ""
        init_sprite_path = initial_sprite_path_for_characters(
            self.state.config_manager,
            str(session.get("initSpritePath") or ""),
            selected_characters,
        )
        room_id = str(session.get("roomId") or self.state.config_manager.config.system_config.live_room_id or "")
        selected_bg = str(session.get("background") or TRANSPARENT_BACKGROUND_NAME)
        user_display_name = _sanitize_user_display_name(session.get("userDisplayName"))
        session_base = {
            "backgroundName": selected_bg,
            "characterName": first_character,
            "historyPath": history_path.as_posix(),
            "sessionId": "",
            "templateId": template_id,
            "userDisplayName": user_display_name,
            "voiceLanguage": str(session.get("voiceLanguage") or self.state.config_manager.config.system_config.voice_language or "ja"),
            "workflowPath": str(session.get("workflowPath") or ""),
        }
        if _chat_process_running():
            self.state.chat_session = {**self.state.chat_session, **session_base}
            configure_mobile_access(
                self.state,
                enabled=mobile_access_enabled,
            )
            return _chat_snapshot(self.state, None, "", extra={"statusMessage": "进程已经在运行中。"})
        self.state.chat_session = {**self.state.chat_session, **session_base}
        initial_snapshot = _chat_stream_initial_snapshot(_chat_snapshot(self.state, "idle", ""))
        use_react_runtime = _chat_runtime_mode(self.state) == "react"
        stream_info = init_stream_info or (
            self.state.chat_stream.create_session(initial_snapshot)
            if use_react_runtime and self.state.chat_stream is not None
            else {}
        )
        message = _launch_chat(
            self.state,
            character_names=selected_characters,
            history_file=history_path.as_posix(),
            init_sprite_path=init_sprite_path,
            room_id=room_id,
            selected_bg=selected_bg,
            system_template=system_template,
            use_cg=bool(session.get("useCg", False)),
            user_scenario=scenario,
            stream_endpoint=str(stream_info.get("producerEndpoint") or "") if use_react_runtime else "",
            init_stream_endpoint=str(stream_info.get("producerEndpoint") or "") if not use_react_runtime else "",
            workflow_path=str(session.get("workflowPath") or ""),
        )
        dependency_error = runtime_dependency_error_from_text(message)
        if dependency_error:
            session_id = str(stream_info.get("sessionId") or "")
            if session_id and self.state.chat_stream is not None:
                self.state.chat_stream.delete_session(session_id)
            self.state.chat_session = {**self.state.chat_session, **session_base}
            return _chat_snapshot(
                self.state,
                "error",
                message,
                extra={"runtimeDependencyError": dependency_error},
            )
        if message.startswith("启动失败"):
            session_id = str(stream_info.get("sessionId") or "")
            if session_id and self.state.chat_stream is not None:
                self.state.chat_stream.delete_session(session_id)
            raise RuntimeError(message)
        self.state.chat_session = {
            **self.state.chat_session,
            **session_base,
            "sessionId": str(stream_info.get("sessionId") or "") if use_react_runtime else "",
        }
        if use_react_runtime and stream_info.get("sessionId") and self.state.chat_stream is not None:
            self.state.chat_stream.update_session_snapshot(
                str(stream_info["sessionId"]),
                {
                    "backgroundPath": _chat_snapshot(self.state).get("backgroundPath", ""),
                    "characterName": first_character,
                    "dialogText": "",
                    "historyPath": history_path.as_posix(),
                    "status": "idle",
                    "statusMessage": message,
                    "userDisplayName": user_display_name,
                    "voiceLanguage": str(self.state.chat_session.get("voiceLanguage") or "ja"),
                },
            )
            self._wait_for_chat_runtime_ready(stream_info)
        configure_mobile_access(
            self.state,
            enabled=mobile_access_enabled,
        )
        return _chat_snapshot(
            self.state,
            "idle",
            "",
            extra={
                "statusMessage": message,
                **({"_chatInitStreamAttached": True} if init_stream_info else {}),
            },
        )

    def _resolve_project_path(self, raw_path: str) -> Path:
        raw = str(raw_path or "").strip()
        if not raw:
            raise FileNotFoundError(raw_path)
        if Path(raw).is_absolute():
            return safe_project_path(raw)

        candidates: list[str] = [raw]
        slash_path = raw.replace("\\", "/")
        if slash_path != raw:
            candidates.append(slash_path)

        parts = [part for part in slash_path.split("/") if part and part != "."]
        if len(parts) >= 5 and parts[0] == "data":
            family, prefix = parts[1], parts[2]
            if parts[3] == family and parts[4] == prefix:
                candidates.append("/".join(parts[:3] + parts[5:]))
            if family in {"backgrounds", "bgm", "speech", "sprite"}:
                candidates.append("/".join(parts[:3] + [parts[-1]]))

        first_valid: Path | None = None
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            path = safe_project_path(candidate)
            if first_valid is None:
                first_valid = path
            if path.is_file():
                return path
        return first_valid if first_valid is not None else safe_project_path(raw)

    def _resolve_media_path(self, raw_path: str) -> Path:
        raw = str(raw_path or "").strip()
        if not raw:
            raise FileNotFoundError(raw_path)
        if is_absolute_local_media_path_text(raw):
            config_manager = getattr(self.state, "config_manager", None)
            config = getattr(config_manager, "config", None)
            approved_paths = list(iter_configured_external_media_paths(config))
            chat_stream = getattr(self.state, "chat_stream", None)
            runtime_paths = getattr(
                chat_stream,
                "approved_external_media_paths",
                None,
            )
            if callable(runtime_paths):
                approved_paths.extend(runtime_paths())
            return resolve_external_media_file(
                raw,
                approved_paths=approved_paths,
            )
        return validate_readable_media_file(
            self._resolve_project_path(raw),
            roots=[Path.cwd()],
        )

    def _resolve_static_path(self, root: Path, request_path: str) -> Path:
        return safe_child_path(root, request_path)

    def _media_thumbnail_batch_response(self, body: dict[str, Any]) -> dict[str, Any]:
        raw_paths = body.get("paths") or []
        if not isinstance(raw_paths, list):
            raise ValueError("paths must be a list")
        size = int(body.get("size") or "160")
        if len(raw_paths) > 1000:
            raise ValueError("too many thumbnail paths")
        mode = str(body.get("mode") or "").strip().lower()
        include_data_url = mode != "url" and body.get("embedDataUrls") is not False
        items: list[tuple[str, Path]] = []
        failures: list[dict[str, str]] = []
        for path in raw_paths:
            raw_path = str(path or "").strip()
            if not raw_path:
                continue
            try:
                items.append((raw_path, self._resolve_project_path(raw_path)))
            except Exception as exc:
                failures.append(
                    {
                        "error": str(exc),
                        "path": raw_path,
                        "type": exc.__class__.__name__,
                    }
                )
        payload = _media_thumbnail_batch(
            items,
            include_data_url=include_data_url,
            project_root=Path.cwd().resolve(),
            size=size,
        )
        payload["items"].extend(failures)
        return payload

    def _send_local_file(
        self,
        path: Path,
        *,
        attachment: bool = False,
        send_body: bool = True,
    ) -> None:
        if not path.is_file():
            raise FileNotFoundError(path.as_posix())
        file_size = path.stat().st_size
        try:
            byte_range = self._parse_byte_range(self.headers.get("Range"), file_size) if not attachment else None
        except _RangeNotSatisfiable:
            self._send_range_not_satisfiable(file_size)
            return
        safe_name = safe_header_value(path.name)
        content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        if byte_range is None:
            start = 0
            end = file_size - 1
            response_status = HTTPStatus.OK
            content_length = file_size
        else:
            start, end = byte_range
            response_status = HTTPStatus.PARTIAL_CONTENT
            content_length = end - start + 1
        self.send_response(response_status)
        self._send_cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(content_length))
        if byte_range is not None:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        if attachment:
            self.send_header("Content-Disposition", safe_content_disposition(safe_name))
        try:
            self.end_headers()
            if not send_body:
                return
            with path.open("rb") as file:
                file.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk = file.read(min(1024 * 512, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def _send_range_not_satisfiable(self, file_size: int) -> None:
        self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
        self._send_cors()
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes */{file_size}")
        self.send_header("Content-Length", "0")
        try:
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def _parse_byte_range(self, range_header: str | None, file_size: int) -> tuple[int, int] | None:
        if not range_header or not range_header.startswith("bytes=") or file_size <= 0:
            return None
        first_range = range_header.removeprefix("bytes=").split(",", 1)[0].strip()
        start_text, separator, end_text = first_range.partition("-")
        if separator != "-":
            return None
        try:
            if start_text:
                start = int(start_text)
                end = int(end_text) if end_text else file_size - 1
            else:
                suffix_length = int(end_text)
                if suffix_length <= 0:
                    return None
                start = max(0, file_size - suffix_length)
                end = file_size - 1
        except ValueError:
            return None
        if start < 0 or start >= file_size or end < start:
            raise _RangeNotSatisfiable
        return start, min(end, file_size - 1)

    def _try_send_frontend(self, request_path: str, *, send_body: bool = True) -> bool:
        dist_root = _frontend_dist_root(self.state)
        if dist_root is None or not dist_root.is_dir():
            return False
        index_path = dist_root / "index.html"
        if not index_path.is_file():
            return False

        if request_path in {"", "/", "/index.html"}:
            self._send_local_file(index_path, send_body=send_body)
            return True

        candidate = self._resolve_static_path(dist_root, request_path)
        if candidate.is_file():
            self._send_local_file(candidate, send_body=send_body)
            return True

        if request_path.startswith("/web-assets/"):
            raise FileNotFoundError(request_path)

        self._send_local_file(index_path, send_body=send_body)
        return True

    def _send_file(
        self,
        relative_path: str,
        *,
        attachment: bool = False,
        send_body: bool = True,
    ) -> None:
        self._send_local_file(
            self._resolve_project_path(relative_path),
            attachment=attachment,
            send_body=send_body,
        )

    def _send_media_file(
        self,
        path: str,
        *,
        send_body: bool = True,
    ) -> None:
        self._send_local_file(
            self._resolve_media_path(path),
            attachment=False,
            send_body=send_body,
        )

    def _send_media_thumbnail(
        self,
        relative_path: str,
        size: str,
        *,
        send_body: bool = True,
    ) -> None:
        source = self._resolve_project_path(relative_path)
        try:
            thumbnail = _media_thumbnail(
                source,
                project_root=Path.cwd().resolve(),
                size=int(size or "160"),
            )
        except Exception as exc:
            logger.warning(
                "Falling back to original media after thumbnail generation failed: %s",
                exc,
                extra={
                    "event": "media.thumbnail.failed",
                    "path": source.as_posix(),
                    "error_type": exc.__class__.__name__,
                },
            )
            thumbnail = source
        self._send_local_file(thumbnail, attachment=False, send_body=send_body)
