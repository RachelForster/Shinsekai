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
from urllib.parse import parse_qs, quote, unquote, urlparse, urlunparse

from application.chat.build_effect_context import build_effect_context
from application.chat.launch_history import (
    persist_confirmed_history_path,
    plan_chat_history_launch,
    resolve_chat_history_path,
)
from application.characters import CharacterOperation
from application.backgrounds import BackgroundOperation
from sdk.logging import get_logger, log_context, new_log_id

from frontend_bridge_core.backgrounds import (
    _execute_background_request,
    _save_background_bgm_tags,
    _save_background_image_tags,
    _translate_background_fields,
    background_response_payload,
)
from application.effects import EffectOperation
from frontend_bridge_core.effects import (
    EffectConfigAdapter,
    effect_response_payload,
    effect_use_case,
    parse_effect_request,
)
from application.chat.runtime_process import (
    _chat_history,
    _chat_history_download_file,
    TRANSPARENT_BACKGROUND_NAME,
    _chat_process_running,
    _chat_runtime_closing,
    _chat_runtime_mode,
    _chat_runtime_status,
    _chat_snapshot,
    _chat_stream_initial_snapshot,
    _chat_theme_payload,
    _handle_chat_command,
    _launch_chat,
    _sanitize_user_display_name,
)
from application.chat.stop_chat import stop_chat
from frontend_bridge_core.chat_themes import (
    delete_chat_theme,
    get_active_chat_theme_id,
    get_chat_theme_manifest,
    install_theme_from_zip,
    list_chat_themes,
    save_chat_theme,
    set_active_chat_theme,
)
from application.chat.start_chat import start_chat
from application.chat.mobile_access import configure_mobile_access
from frontend_bridge_core.characters import (
    _execute_character_request,
    _generate_character_setting,
    _save_character_emotion_tags,
    _save_sprite_scale,
    _translate_character_fields,
    character_response_payload,
)
from frontend_bridge_core.memory import (
    _add_character_memory,
    _delete_character_memory,
    _get_mem0_status,
    _list_character_memories,
    _memory_tool_forget,
    _memory_tool_remember,
    _memory_tool_search,
    _preview_character_memory_import,
    _run_character_memory_import,
)
from application.model_assets.download_model import (
    download_model,
    inspect_model,
    resolve_model_asset,
)
from frontend_bridge_core.model_assets import (
    configured_asr_model,
    find_running_model_download,
    huggingface_token,
    model_download_enqueue_guard,
    model_download_progress,
    parse_model_asset_request,
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
from frontend_bridge_core.image_annotations import (
    run_background_image_auto_label,
    run_character_sprite_auto_label,
)
from frontend_bridge_core.mcp import (
    _mcp_config_response,
    _open_mcp_config_file,
    _preview_mcp_tools_from_payload,
    _save_and_apply_mcp_config,
)
from frontend_bridge_core.music import _music_cover_search, _run_music_cover, _save_music_cover_config
from application.plugins.catalog import (
    _plugin_registry_rows,
    _plugin_rows,
    _set_plugin_enabled,
    _uninstall_plugin,
)
from frontend_bridge_core.plugin_publisher import (
    _build_plugin_submission_issue_url,
    _copy_plugin_submission_json,
    _scan_local_plugin,
    _validate_plugin_submission,
)
from frontend_bridge_core.plugin_ui import (
    _frontend_chat_ui_contribution_payloads,
    _plugin_ui_detail,
    _resolve_plugin_frontend_file,
    _run_frontend_chat_ui_contribution,
    _run_plugin_ui_action,
    _save_plugin_ui_config,
)
from application.plugins.install_plugin import install_plugin
from application.plugins.update_application import (
    get_application_update_info,
    list_application_update_tags,
    list_plugin_repository_tags,
    update_application,
)
from frontend_bridge_core.plugin_install import BridgePluginInstallProgress
from application.runtime.dependencies import (
    install_runtime_dependency,
    runtime_dependency_error_from_text,
)
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
from application.runtime.state import BridgeState, _jsonify, plugin_load_snapshot
from application.story.coordinator import (
    clear_story_session,
    publish_story_transition,
    release_unbound_story_session,
    start_or_recover_story_session,
)
from application.story.generation import (
    StoryGenerationStage,
    run_story_generation_background,
    story_generation_service_for_state,
)
from frontend_bridge_core.static import _frontend_dist_root
from application.runtime.tasks import (
    _create_task,
    _get_task,
    _is_running_task,
    _run_background_task,
    _update_task,
)
from application.chat.initial_sprite import initial_sprite_path_for_characters
from application.chat.templates import (
    NoValidCharactersError,
    _compose_for_llm,
    _latest_history_json,
    _list_templates,
    _repair_template_parts_from_session_if_needed,
    _resolve_template_character_names,
    _resume_template_parts,
    _scenario_from_template_like,
    _save_template_session_payload,
    _save_template_summary,
    _generate_template_summary,
    _load_template_session_payload,
)
from application.media.attachments import stage_uploaded_chat_attachments
from frontend_bridge_core.tools import (
    _browse_local_files,
    _crop_sprites,
    _generate_sprite_prompts,
    _generate_sprites,
    _remove_sprite_background,
)
from application.model_assets.tts_bundle import (
    _download_tts_bundle,
)
from frontend_bridge_core.routes.router import ApiRequest, BodyKind, Router
from frontend_bridge_core.routes.system_routes import SYSTEM_ROUTES

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
_API_ROUTER = Router(list(SYSTEM_ROUTES))


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
        token = str(getattr(self.state, "auth_token", "") or "").strip()
        if not token:
            return detail
        for page in detail.get("pages") or []:
            url = str(page.get("frontendUrl") or "")
            if url.startswith("/api/") and BRIDGE_AUTH_QUERY not in url:
                sep = "&" if "?" in url else "?"
                page["frontendUrl"] = f"{url}{sep}{BRIDGE_AUTH_QUERY}={quote(token, safe='')}"
        return detail

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
            stop_chat(self.state, reason="聊天会话启动超时。")
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
            if path == "/api/characters":
                self._send_json(self.state.config_manager.config.characters)
            elif path == "/api/backgrounds":
                self._send_json(self.state.config_manager.config.background_list)
            elif path == "/api/effects":
                self._send_json(self.state.config_manager.config.effect_list)
            elif path == "/api/templates":
                self._send_json(_list_templates(self.state))
            elif path == "/api/templates/session":
                self._send_json(_load_template_session_payload(self.state))
            elif path == "/api/logs/default":
                self._send_json(_default_log_snapshot(Path.cwd().resolve()))
            elif path == "/api/logs":
                self._send_json(_log_file_list(Path.cwd().resolve()))
            elif path == "/api/plugins":
                self._send_json(_plugin_rows(plugin_load_snapshot(self.state)))
            elif path == "/api/plugins/chat-ui-contributions":
                self._send_json(_frontend_chat_ui_contribution_payloads())
            elif path == "/api/plugins/status":
                self._send_json(plugin_load_snapshot(self.state))
            elif path.startswith("/api/plugins/") and path.endswith("/ui"):
                plugin_id = unquote(path[len("/api/plugins/") : -len("/ui")])
                self._send_json(self._inject_bridge_token(_plugin_ui_detail(plugin_id)))
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
            elif path == "/api/plugins/app-update/info":
                self._send_json(get_application_update_info())
            elif path == "/api/plugins/registry":
                self._send_json(_plugin_registry_rows())
            elif path == "/api/mcp/config":
                self._send_json(_mcp_config_response())
            elif path.startswith("/api/story/generation/"):
                generation_task_id = unquote(path[len("/api/story/generation/") :])
                self._send_json(
                    story_generation_service_for_state(self.state).get(
                        generation_task_id
                    )
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
            elif method == "POST" and path == "/api/music-cover/search":
                self._send_json(_music_cover_search(self.state, body))
            elif method == "POST" and path == "/api/music-cover/config":
                self._send_json(_save_music_cover_config(self.state, body))
            elif method == "POST" and path == "/api/music-cover/run":
                self._enqueue_background_task(
                    kind="music-cover",
                    title="音乐翻唱流水线",
                    message="音乐翻唱流水线已排队。",
                    worker=lambda task_id: _run_music_cover(self.state, task_id, body),
                )
            elif method == "POST" and path == "/api/config/tts-bundle/download":
                self._enqueue_background_task(
                    kind="tts-bundle",
                    title="TTS 整合包下载",
                    message="TTS 整合包下载已排队。",
                    worker=lambda task_id: _download_tts_bundle(self.state, task_id, body),
                )
            elif method == "POST" and path == "/api/model-assets/status":
                request = parse_model_asset_request(body)
                self._send_json(
                    inspect_model(
                        request,
                        configured_asr_model=configured_asr_model(self.state),
                    )
                )
            elif method == "POST" and path == "/api/model-assets/download":
                request = parse_model_asset_request(body)
                spec = resolve_model_asset(
                    request,
                    configured_asr_model=configured_asr_model(self.state),
                )
                with model_download_enqueue_guard():
                    existing = find_running_model_download(self.state, spec.task_key)
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
                            worker=lambda task_id: download_model(
                                spec,
                                token=huggingface_token(self.state),
                                update_task=model_download_progress(self.state, task_id),
                            ),
                        )
            elif method in {"POST", "PUT"} and path == "/api/characters":
                self._send_json(_execute_character_request(self.state, CharacterOperation.SAVE, body))
            elif method == "POST" and path == "/api/characters/ai-setting":
                self._send_json(_generate_character_setting(self.state, body))
            elif method == "POST" and path == "/api/characters/translate":
                self._send_json(_translate_character_fields(self.state, body))
            elif method == "POST" and path == "/api/characters/memories/status":
                self._send_json(_get_mem0_status())
            elif method == "POST" and path == "/api/characters/memories/list":
                self._send_json(_list_character_memories(str(body.get("name") or "")))
            elif method == "POST" and path == "/api/characters/memories/add":
                self._send_json(_add_character_memory(str(body.get("name") or ""), str(body.get("content") or "")))
            elif method == "POST" and path == "/api/characters/memories/delete":
                self._send_json(
                    _delete_character_memory(str(body.get("name") or ""), str(body.get("memoryId") or ""))
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
            elif method == "POST" and path == "/api/memory/status":
                self._send_json(_get_mem0_status(start_loading=bool(body.get("startLoading", True))))
            elif method == "POST" and path == "/api/memory/list":
                self._send_json(_list_character_memories(str(body.get("name") or body.get("characterName") or "")))
            elif method == "POST" and path == "/api/memory/search":
                self._send_json(
                    _memory_tool_search(
                        str(body.get("query") or ""),
                        str(body.get("characterName") or body.get("character_name") or ""),
                        int(body.get("limit") or 10),
                    )
                )
            elif method == "POST" and path == "/api/memory/remember":
                self._send_json(
                    _memory_tool_remember(
                        str(body.get("content") or ""),
                        str(body.get("characterName") or body.get("character_name") or ""),
                    )
                )
            elif method == "POST" and path == "/api/memory/forget":
                self._send_json(_memory_tool_forget(str(body.get("memoryId") or body.get("memory_id") or "")))
            elif method == "POST" and path == "/api/characters/sprite-voice/upload":
                self._send_json(
                    _execute_character_request(self.state, CharacterOperation.UPLOAD_SPRITE_VOICE, body)
                )
            elif method == "POST" and path == "/api/characters/sprites/upload":
                self._send_json(_execute_character_request(self.state, CharacterOperation.UPLOAD_SPRITES, body))
            elif method == "POST" and path == "/api/characters/sprites/auto-label":
                name = str(body.get("name") or "").strip()
                if not name:
                    raise ValueError("角色名称不能为空")
                self._enqueue_background_task(
                    kind="moondream-character-auto-label",
                    title=f"标注 {name} 的角色立绘",
                    message="Moondream 图片标注任务已排队。",
                    worker=lambda task_id: run_character_sprite_auto_label(self.state, task_id, name),
                )
            elif method == "POST" and path == "/api/characters/emotion-tags":
                self._send_json(_save_character_emotion_tags(self.state, body))
            elif method == "POST" and path == "/api/characters/sprites/delete":
                self._send_json(_execute_character_request(self.state, CharacterOperation.DELETE_SPRITE, body))
            elif method == "POST" and path == "/api/characters/sprites/delete-all":
                self._send_json(_execute_character_request(self.state, CharacterOperation.DELETE_ALL_SPRITES, body))
            elif method == "POST" and path == "/api/characters/sprite-scale":
                self._send_json(_save_sprite_scale(self.state, body))
            elif method == "POST" and path == "/api/characters/sprite-voice/text":
                self._send_json(
                    _execute_character_request(self.state, CharacterOperation.SAVE_SPRITE_VOICE_TEXT, body)
                )
            elif method == "POST" and path == "/api/characters/sprite-voice/voice-type":
                self._send_json(
                    _execute_character_request(self.state, CharacterOperation.SAVE_SPRITE_VOICE_TYPE, body)
                )
            elif method == "POST" and path == "/api/characters/sprite-voice/delete":
                self._send_json(
                    _execute_character_request(self.state, CharacterOperation.DELETE_SPRITE_VOICE, body)
                )
            elif method == "DELETE" and path.startswith("/api/chat/themes/"):
                theme_id = unquote(path[len("/api/chat/themes/"):])
                self._send_json(delete_chat_theme(self.state, theme_id))
            elif method == "DELETE" and path.startswith("/api/characters/"):
                name = unquote(path.rsplit("/", 1)[-1])
                self._send_json(
                    _execute_character_request(self.state, CharacterOperation.DELETE, {"name": name})
                )
            elif method == "POST" and path == "/api/characters/import":
                self._send_json(_execute_character_request(self.state, CharacterOperation.IMPORT, body))
            elif method == "POST" and path == "/api/characters/import-upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    self._send_json(
                        _execute_character_request(
                            self.state,
                            CharacterOperation.IMPORT,
                            {"paths": paths},
                            extra_file_access_roots=(temp_dir,),
                        )
                    )
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            elif method == "POST" and path == "/api/characters/export":
                self._send_json(
                    character_response_payload(
                        _execute_character_request(
                            self.state,
                            CharacterOperation.EXPORT,
                            body,
                        )
                    )
                )
            elif method == "POST" and path == "/api/backgrounds/translate":
                self._send_json(_translate_background_fields(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/images/upload":
                self._send_json(_execute_background_request(self.state, BackgroundOperation.UPLOAD_IMAGES, body))
            elif method == "POST" and path == "/api/backgrounds/images/auto-label":
                name = str(body.get("name") or "").strip()
                if not name:
                    raise ValueError("背景名称不能为空")
                self._enqueue_background_task(
                    kind="moondream-background-auto-label",
                    title=f"标注 {name} 的背景图片",
                    message="Moondream 图片标注任务已排队。",
                    worker=lambda task_id: run_background_image_auto_label(self.state, task_id, name),
                )
            elif method == "POST" and path == "/api/backgrounds/bgm/upload":
                self._send_json(_execute_background_request(self.state, BackgroundOperation.UPLOAD_BGM, body))
            elif method == "POST" and path == "/api/backgrounds/images/delete":
                self._send_json(_execute_background_request(self.state, BackgroundOperation.DELETE_IMAGE, body))
            elif method == "POST" and path == "/api/backgrounds/images/delete-all":
                self._send_json(
                    _execute_background_request(self.state, BackgroundOperation.DELETE_ALL_IMAGES, body)
                )
            elif method == "POST" and path == "/api/backgrounds/bgm/delete":
                self._send_json(_execute_background_request(self.state, BackgroundOperation.DELETE_BGM, body))
            elif method == "POST" and path == "/api/backgrounds/bgm/delete-all":
                self._send_json(_execute_background_request(self.state, BackgroundOperation.DELETE_ALL_BGM, body))
            elif method == "POST" and path == "/api/backgrounds/tags":
                self._send_json(_save_background_image_tags(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/bgm-tags":
                self._send_json(_save_background_bgm_tags(self.state, body))
            elif method in {"POST", "PUT"} and path == "/api/backgrounds":
                self._send_json(_execute_background_request(self.state, BackgroundOperation.SAVE, body))
            elif method == "DELETE" and path.startswith("/api/backgrounds/"):
                name = unquote(path.rsplit("/", 1)[-1])
                self._send_json(
                    _execute_background_request(self.state, BackgroundOperation.DELETE, {"name": name})
                )
            elif method == "POST" and path == "/api/backgrounds/import":
                self._send_json(_execute_background_request(self.state, BackgroundOperation.IMPORT, body))
            elif method == "POST" and path == "/api/backgrounds/import-upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    self._send_json(
                        _execute_background_request(
                            self.state,
                            BackgroundOperation.IMPORT,
                            {"paths": paths},
                            extra_file_access_roots=(temp_dir,),
                        )
                    )
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            elif method == "POST" and path == "/api/backgrounds/export":
                self._send_json(
                    background_response_payload(
                        _execute_background_request(
                            self.state,
                            BackgroundOperation.EXPORT,
                            body,
                        )
                    )
                )
            # --- effects ---
            elif method == "POST" and path == "/api/effects/audio/upload":
                self._send_json(
                    self._execute_effect_request(EffectOperation.UPLOAD_AUDIO, body)
                )
            elif method == "POST" and path == "/api/effects/audio/delete":
                self._send_json(
                    self._execute_effect_request(EffectOperation.DELETE_AUDIO, body)
                )
            elif method == "POST" and path == "/api/effects/audio/delete-all":
                self._send_json(
                    self._execute_effect_request(EffectOperation.DELETE_ALL_AUDIO, body)
                )
            elif method == "POST" and path == "/api/effects/audio-tags":
                self._send_json(
                    self._execute_effect_request(EffectOperation.SAVE_AUDIO_TAGS, body)
                )
            elif method in {"POST", "PUT"} and path == "/api/effects":
                self._send_json(self._execute_effect_request(EffectOperation.SAVE, body))
            elif method == "DELETE" and path.startswith("/api/effects/"):
                name = unquote(path.rsplit("/", 1)[-1])
                self._send_json(
                    self._execute_effect_request(EffectOperation.DELETE, name=name)
                )
            elif method == "POST" and path == "/api/effects/import":
                self._send_json(self._execute_effect_request(EffectOperation.IMPORT, body))
            elif method == "POST" and path == "/api/effects/import-upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    self._send_json(
                        self._execute_effect_request(
                            EffectOperation.IMPORT,
                            {"paths": [str(item) for item in paths]},
                            additional_file_roots=(str(temp_dir),),
                        )
                    )
                finally:
                    shutil.rmtree(temp_dir, ignore_errors=True)
            elif method == "POST" and path == "/api/effects/export":
                self._send_json(self._execute_effect_request(EffectOperation.EXPORT, body))
            # --- templates ---
            elif method in {"POST", "PUT"} and path == "/api/templates":
                self._send_json(_save_template_summary(self.state, body))
            elif method == "POST" and path == "/api/templates/session":
                self._send_json(_save_template_session_payload(self.state, body))
            elif method == "POST" and path == "/api/templates/generate":
                self._send_json(_generate_template_summary(self.state, body))
            elif method == "POST" and path == "/api/tools/sprite-prompts":
                self._enqueue_background_task(
                    kind="tools-prompts",
                    message="立绘提示词生成任务已排队。",
                    title="生成立绘提示词",
                    worker=lambda task_id: _generate_sprite_prompts(self.state, task_id, body),
                )
            elif method == "POST" and path == "/api/tools/sprites/generate":
                self._enqueue_background_task(
                    kind="tools-sprites",
                    message="立绘批量生成任务已排队。",
                    title="批量生成立绘",
                    worker=lambda task_id: _generate_sprites(self.state, task_id, body),
                )
            elif method == "POST" and path == "/api/tools/sprites/crop":
                self._enqueue_background_task(
                    kind="tools-crop",
                    message="立绘裁剪任务已排队。",
                    title="批量裁剪立绘",
                    worker=lambda task_id: _crop_sprites(self.state, task_id, body),
                )
            elif method == "POST" and path == "/api/tools/sprites/remove-background":
                self._enqueue_background_task(
                    kind="tools-rmbg",
                    message="立绘抠图任务已排队。",
                    title="批量抠出立绘",
                    worker=lambda task_id: _remove_sprite_background(self.state, task_id, body),
                )
            elif method == "POST" and path == "/api/mcp/config/open":
                self._send_json(_open_mcp_config_file())
            elif method == "POST" and path == "/api/mcp/config/apply":
                self._enqueue_background_task(
                    kind="mcp-apply",
                    message="MCP 保存应用任务已排队。",
                    title="保存并应用 MCP 配置",
                    worker=lambda task_id: _save_and_apply_mcp_config(self.state, task_id, body),
                )
            elif method == "POST" and path == "/api/mcp/preview":
                self._enqueue_background_task(
                    kind="mcp-preview",
                    message="MCP 工具预览任务已排队。",
                    title="刷新 MCP 工具列表",
                    worker=lambda task_id: _preview_mcp_tools_from_payload(self.state, task_id, body),
                )
            elif method == "POST" and path == "/api/plugins/install":
                plugin_id = str(body.get("source") or body.get("id") or "").strip()
                if not plugin_id:
                    raise ValueError("plugin id is required")
                ref_kind = str(body.get("refKind") or "latest").strip()
                tag_name = str(body.get("tagName") or "").strip()
                overwrite = bool(body.get("overwrite"))
                with self.state.task_lock:
                    running = [
                        dict(task)
                        for task in self.state.tasks.values()
                        if task.get("kind") == "plugin-install"
                        and task.get("source") == plugin_id
                        and _is_running_task(task)
                    ]
                if running:
                    self._send_json(running[0], HTTPStatus.ACCEPTED)
                    return
                self._enqueue_background_task(
                    kind="plugin-install",
                    message="插件安装任务已排队。",
                    title=f"安装插件 {plugin_id}",
                    task_updates={"source": plugin_id},
                    worker=lambda task_id: install_plugin(
                        BridgePluginInstallProgress(self.state, task_id),
                        plugin_id,
                        ref_kind=ref_kind,
                        tag_name=tag_name,
                        overwrite=overwrite,
                    ),
                )
            elif method == "POST" and path == "/api/plugins/repo-tags":
                self._send_json(list_plugin_repository_tags(body))
            elif method == "POST" and path == "/api/plugins/publisher/scan":
                self._send_json(_scan_local_plugin(body))
            elif method == "POST" and path == "/api/plugins/publisher/validate":
                self._send_json(_validate_plugin_submission(body))
            elif method == "POST" and path == "/api/plugins/publisher/issue-url":
                self._send_json(_build_plugin_submission_issue_url(body))
            elif method == "POST" and path == "/api/plugins/publisher/copy-json":
                self._send_json(_copy_plugin_submission_json(body))
            elif method == "POST" and path == "/api/plugins/app-update/tags":
                self._send_json(list_application_update_tags())
            elif method == "POST" and path == "/api/plugins/app-update/run":
                ref_kind = str(body.get("refKind") or "latest").strip()
                tag_name = str(body.get("tagName") or "").strip()
                self._enqueue_background_task(
                    kind="app-update",
                    message="主程序更新任务已排队。",
                    title="更新主程序",
                    task_updates={"refKind": ref_kind, "tagName": tag_name},
                    worker=lambda task_id: update_application(self.state, task_id, body),
                )
            elif method == "POST" and path.startswith("/api/plugins/") and path.endswith("/enabled"):
                plugin_id = unquote(path[len("/api/plugins/") : -len("/enabled")])
                self._send_json(_set_plugin_enabled(plugin_id, bool(body.get("enabled"))))
            elif method == "POST" and path.startswith("/api/plugins/") and "/chat-ui/" in path and path.endswith("/run"):
                rest = path[len("/api/plugins/") :]
                plugin_part, _, contribution_tail = rest.partition("/chat-ui/")
                contribution_part = contribution_tail[: -len("/run")]
                self._send_json(
                    _run_frontend_chat_ui_contribution(
                        unquote(plugin_part),
                        unquote(contribution_part),
                    )
                )
            elif method == "POST" and path.startswith("/api/plugins/") and "/ui/" in path and "/actions/" in path:
                # /api/plugins/{plugin_id}/ui/{page_id}/actions/{action_id}
                rest = path[len("/api/plugins/") :]
                plugin_part, _, ui_tail = rest.partition("/ui/")
                page_part, _, action_tail = ui_tail.partition("/actions/")
                self._send_json(
                    _run_plugin_ui_action(
                        unquote(plugin_part),
                        unquote(page_part),
                        unquote(action_tail),
                        body,
                    )
                )
            elif method == "POST" and path.startswith("/api/plugins/") and "/ui/" in path and path.endswith("/config"):
                rest = path[len("/api/plugins/") :]
                plugin_part, _, page_tail = rest.partition("/ui/")
                page_part = page_tail[: -len("/config")]
                self._send_json(
                    _save_plugin_ui_config(
                        unquote(plugin_part),
                        unquote(page_part),
                        body,
                    )
                )
            elif method == "DELETE" and path.startswith("/api/plugins/"):
                plugin_id = unquote(path[len("/api/plugins/") :])
                self._send_json(_uninstall_plugin(plugin_id))
            elif method == "POST" and path == "/api/runtime/install-missing-dependency":
                module_name = str(body.get("moduleName") or "").strip()
                if not module_name:
                    raise ValueError("moduleName is required")
                self._enqueue_background_task(
                    kind="runtime-dependency-install",
                    message=f"Installing dependency for {module_name}",
                    title=f"Install {module_name}",
                    task_updates={"source": module_name, "phase": "pip", "progress": 0},
                    worker=lambda task_id: install_runtime_dependency(
                        module_name,
                        _task_id=task_id,
                        _state=self.state,
                    ),
                )
            elif method == "POST" and path == "/api/chat/launch":
                self._send_json(self._launch_chat(body))
            elif method == "POST" and path == "/api/chat/resume-last":
                self._send_json(self._resume_last_chat())
            elif method == "POST" and path == "/api/chat/init":
                self._send_json(self._start_chat_init(body), HTTPStatus.ACCEPTED)
            elif method == "POST" and path == "/api/chat/close":
                self._send_json(stop_chat(self.state))
            elif method == "POST" and path == "/api/chat/command":
                self._send_json(_handle_chat_command(self.state, body))
            elif method == "POST" and path == "/api/story/start":
                story_path = str(body.get("storyPath") or "").strip()
                if not story_path:
                    raise ValueError("storyPath is required")
                session = start_or_recover_story_session(
                    self.state,
                    story_path,
                    command_id=str(body.get("commandId") or new_log_id()),
                )
                patch = session.chat_snapshot()
                publish_story_transition(self.state, patch)
                self._send_json(
                    _chat_snapshot(self.state, "idle", extra=patch)
                )
            elif method == "POST" and path == "/api/story/generation/start":
                service = story_generation_service_for_state(self.state)
                generation_task = service.create(
                    str(body.get("synopsis") or ""),
                    options=body.get("options") if isinstance(body.get("options"), dict) else {},
                    resource_catalog=(
                        body.get("resourceCatalog")
                        if isinstance(body.get("resourceCatalog"), dict)
                        else {}
                    ),
                )
                generation_task_id = str(generation_task["id"])
                self._enqueue_background_task(
                    kind="story-generation",
                    title="AI story compiler",
                    message="Story generation queued.",
                    task_updates={
                        "generationTaskId": generation_task_id,
                        "generationTask": generation_task,
                    },
                    worker=lambda task_id: run_story_generation_background(
                        self.state, task_id, generation_task_id
                    ),
                )
            elif (
                method == "POST"
                and path.startswith("/api/story/generation/")
                and path.endswith("/resume")
            ):
                generation_task_id = unquote(
                    path[len("/api/story/generation/") : -len("/resume")]
                )
                service = story_generation_service_for_state(self.state)
                generation_task = service.get(generation_task_id)
                self._enqueue_background_task(
                    kind="story-generation",
                    title="Resume AI story compiler",
                    message="Story generation resume queued.",
                    task_updates={
                        "generationTaskId": generation_task_id,
                        "generationTask": generation_task,
                    },
                    worker=lambda task_id: run_story_generation_background(
                        self.state, task_id, generation_task_id, resume=True
                    ),
                )
            elif (
                method == "POST"
                and path.startswith("/api/story/generation/")
                and path.endswith("/regenerate")
            ):
                generation_task_id = unquote(
                    path[len("/api/story/generation/") : -len("/regenerate")]
                )
                service = story_generation_service_for_state(self.state)
                generation_task = service.regenerate_from(
                    generation_task_id,
                    StoryGenerationStage(str(body.get("stage") or "")),
                )
                self._enqueue_background_task(
                    kind="story-generation",
                    title="Regenerate story stage",
                    message="Partial story regeneration queued.",
                    task_updates={
                        "generationTaskId": generation_task_id,
                        "generationTask": generation_task,
                    },
                    worker=lambda task_id: run_story_generation_background(
                        self.state, task_id, generation_task_id
                    ),
                )
            elif (
                method == "POST"
                and path.startswith("/api/story/generation/")
                and path.endswith("/cancel")
            ):
                generation_task_id = unquote(
                    path[len("/api/story/generation/") : -len("/cancel")]
                )
                self._send_json(
                    story_generation_service_for_state(self.state).cancel(
                        generation_task_id
                    )
                )
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

    def _execute_effect_request(
        self,
        operation: EffectOperation,
        body: dict[str, Any] | None = None,
        *,
        name: str = "",
        additional_file_roots: tuple[str, ...] = (),
    ) -> Any:
        request = parse_effect_request(operation, body, name=name)
        result = effect_use_case(
            self.state,
            additional_file_roots=additional_file_roots,
        ).execute(request)
        return effect_response_payload(result)

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
        return start_chat(self.state, mode=mode, launch=launch)

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
        if _chat_process_running():
            configure_mobile_access(
                self.state,
                enabled=mobile_access_enabled,
            )
            return _chat_snapshot(
                self.state,
                None,
                "",
                extra={"statusMessage": "进程已经在运行中。"},
            )
        start_fresh_history = bool(body.get("resetHistory"))
        history_target = plan_chat_history_launch(
            self.state,
            {**body, "characters": characters},
            row,
            start_fresh=start_fresh_history,
        )
        history_path = history_target.history_path
        user_scenario = _scenario_from_template_like(row)
        system_template = str(row.get("system") or "")
        user_scenario, system_template = _repair_template_parts_from_session_if_needed(
            self.state,
            user_scenario,
            system_template,
        )
        if start_fresh_history:
            clear_story_session(self.state)
        user_display_name = _sanitize_user_display_name(body.get("userDisplayName"))
        session_base = {
            "backgroundName": str(body.get("backgroundName") or ""),
            "characterName": first_character,
            "historyPath": history_path.as_posix(),
            "sessionId": "",
            "templateId": template_id,
            "userDisplayName": user_display_name,
            "voiceLanguage": str(self.state.config_manager.config.system_config.voice_language or "ja"),
            "workflowPath": str(body.get("workflowPath") or ""),
        }
        release_unbound_story_session(self.state, session_base["historyPath"])
        self.state.chat_session = {**self.state.chat_session, **session_base}
        initial_snapshot = _chat_stream_initial_snapshot(_chat_snapshot(self.state, "idle", ""))
        use_react_runtime = _chat_runtime_mode(self.state) == "react"
        stream_info = init_stream_info or (
            self.state.chat_stream.create_session(initial_snapshot)
            if use_react_runtime and self.state.chat_stream is not None
            else {}
        )
        effect_context = build_effect_context(
            EffectConfigAdapter(self.state.config_manager),
            body.get("effectNames") if isinstance(body.get("effectNames"), list) else [],
        )
        effect_names_str = ",".join(effect_context.selected_names)
        system_template = effect_context.append_prompt_catalog(system_template)
        message = _launch_chat(
            self.state,
            character_names=characters,
            effect_names=effect_names_str,
            history_file=history_path.as_posix(),
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
        if init_stream_info is None and not persist_confirmed_history_path(
            self.state,
            history_path,
        ):
            logger.warning(
                "Chat launched but the selected history path could not be persisted",
                extra={"history_path": history_path.as_posix()},
            )
        return _chat_snapshot(
            self.state,
            "idle",
            "",
            extra={
                "statusMessage": message,
                **({"_chatInitStreamAttached": True} if init_stream_info else {}),
                **(
                    {"_pendingHistoryPath": history_path.as_posix()}
                    if init_stream_info
                    else {}
                ),
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
            resolve_chat_history_path(
                self.state,
                {"historyPath": session_history_path},
                session,
            )
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
        release_unbound_story_session(self.state, session_base["historyPath"])
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
