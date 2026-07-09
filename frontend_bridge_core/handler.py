from __future__ import annotations

import hmac
import json
import mimetypes
import shutil
import tempfile
import threading
from email.parser import BytesParser
from email.policy import default as default_email_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urlparse, urlunparse

from sdk.logging import get_logger, log_context, new_log_id
from core.sprite.chat_branch_storage import remove_chat_history_storage

from frontend_bridge_core.backgrounds import (
    _delete_all_background_bgm,
    _delete_all_background_images,
    _delete_background_bgm,
    _delete_background_image,
    _save_background,
    _save_background_bgm_tags,
    _save_background_image_tags,
    _translate_background_fields,
    _upload_background_bgm,
    _upload_background_images,
)
from frontend_bridge_core.effects import (
    _build_effect_usage_guide,
    _delete_all_effect_audio,
    _delete_effect,
    _delete_effect_audio,
    _effect_dir,
    _save_effect,
    _save_effect_audio_tags,
    _upload_effect_audio,
    _validate_effect_storage_name,
)
from frontend_bridge_core.chat import (
    _chat_history,
    _close_chat,
    TRANSPARENT_BACKGROUND_NAME,
    _chat_history_path,
    _chat_process_running,
    _chat_runtime_closing,
    _chat_runtime_mode,
    _chat_snapshot,
    _chat_theme_payload,
    _handle_chat_command,
    _launch_chat,
    _sanitize_user_display_name,
    _sprite_path,
)
from frontend_bridge_core.chat_themes import (
    delete_chat_theme,
    get_active_chat_theme_id,
    get_chat_theme_manifest,
    install_theme_from_zip,
    list_chat_themes,
    set_active_chat_theme,
)
from frontend_bridge_core.characters import (
    _as_character_config,
    _delete_all_character_sprites,
    _delete_character_sprite,
    _delete_sprite_voice,
    _generate_character_setting,
    _save_character,
    _save_character_emotion_tags,
    _save_sprite_scale,
    _save_sprite_voice_text,
    _save_sprite_voice_type,
    _translate_character_fields,
    _upload_character_sprites,
    _upload_sprite_voice,
)
from frontend_bridge_core.memory import (
    _add_character_memory,
    _delete_character_memory,
    _get_mem0_status,
    _list_character_memories,
    _memory_tool_forget,
    _memory_tool_remember,
    _memory_tool_search,
)
from frontend_bridge_core.config import _app_config_response, _fetch_llm_models, _save_api_config, _test_llm_connection
from frontend_bridge_core.logs import _default_log_snapshot, _diagnostic_bundle, _log_file_list, _log_snapshot
from frontend_bridge_core.media import _media_thumbnail, _media_thumbnail_batch
from frontend_bridge_core.mcp import (
    _mcp_config_response,
    _open_mcp_config_file,
    _preview_mcp_tools_from_payload,
    _save_and_apply_mcp_config,
)
from frontend_bridge_core.music import _music_cover_search, _run_music_cover, _save_music_cover_config
from frontend_bridge_core.plugin_catalog import (
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
from frontend_bridge_core.plugin_ui import _plugin_ui_detail, _resolve_plugin_frontend_file, _run_plugin_ui_action, _save_plugin_ui_config
from frontend_bridge_core.plugin_updates import (
    _app_update_info,
    _app_update_tags,
    _install_plugin_source,
    _repo_tags,
    _run_app_update,
)
from frontend_bridge_core.runtime_dependencies import install_runtime_dependency, runtime_dependency_error_from_text
from frontend_bridge_core.security import (
    reject_control_chars,
    safe_child_path,
    safe_content_disposition,
    safe_filename,
    safe_header_value,
    safe_project_path,
)
from frontend_bridge_core.state import BridgeState, _jsonify, plugin_load_snapshot
from frontend_bridge_core.static import _frontend_dist_root
from frontend_bridge_core.tasks import _create_task, _get_task, _is_running_task, _request_task_cancel, _run_background_task, _update_task
from frontend_bridge_core.templates import (
    _compose_for_llm,
    _latest_history_json,
    _list_templates,
    _repair_template_parts_from_session_if_needed,
    _resume_template_parts,
    _scenario_from_template_like,
    _save_template_session_payload,
    _save_template_summary,
    _generate_template_summary,
    _load_template_session_payload,
)
from frontend_bridge_core.tools import (
    _browse_local_files,
    _crop_sprites,
    _generate_sprite_prompts,
    _generate_sprites,
    _remove_sprite_background,
)
from frontend_bridge_core.tts import _download_tts_bundle, _tts_bundle_recommendation

logger = get_logger(__name__)
BRIDGE_AUTH_HEADER = "X-Shinsekai-Bridge-Token"
BRIDGE_AUTH_QUERY = "shinsekai_bridge_token"
_ALLOWED_CUSTOM_ORIGIN_SCHEMES = {"shinsekai", "tauri"}
_ALLOWED_LOCAL_ORIGIN_HOSTS = {"127.0.0.1", "::1", "localhost", "tauri.localhost"}

CHAT_RUNTIME_READY_TIMEOUT_SECONDS = 20.0


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
        logger.info(
            fmt,
            *args,
            extra={
                "event": "http.request.completed",
                "method": getattr(self, "command", ""),
                "path": urlparse(getattr(self, "path", "")).path,
            },
        )

    def _log_request_exception(self, exc: Exception) -> None:
        extra = {
            "event": "http.request.failed",
            "method": getattr(self, "command", ""),
            "path": urlparse(getattr(self, "path", "")).path,
            "error_type": exc.__class__.__name__,
        }
        if isinstance(exc, (KeyError, FileNotFoundError, PermissionError, ValueError)):
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
        if host not in _ALLOWED_LOCAL_ORIGIN_HOSTS:
            return None
        if scheme in _ALLOWED_CUSTOM_ORIGIN_SCHEMES:
            if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
                return None
            netloc = host
            if parsed.port is not None:
                netloc = f"{host}:{parsed.port}"
            return safe_header_value(urlunparse((scheme, netloc, "", "", "", "")))
        if scheme in {"http", "https"}:
            if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
                return None
            netloc = host
            if parsed.port is not None:
                netloc = f"{host}:{parsed.port}"
            return safe_header_value(urlunparse((scheme, netloc, "", "", "", "")))
        return None

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
        return str((query.get(BRIDGE_AUTH_QUERY) or query.get("token") or [""])[0]).strip()

    def _has_valid_auth_token(self) -> bool:
        required = str(getattr(self.state, "auth_token", "") or "").strip()
        if not required:
            return True
        supplied = self._auth_token_from_request()
        return bool(supplied) and hmac.compare_digest(supplied, required)

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

    def _send_cors(self) -> None:
        origin = self._allowed_origin_header(str(self.headers.get("Origin") or ""))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", f"Content-Type, Range, X-Task-Id, {BRIDGE_AUTH_HEADER}")
        self.send_header("Access-Control-Expose-Headers", "Accept-Ranges, Content-Length, Content-Range")

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

    def _send_error_json(self, exc: Exception, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self._send_json({"error": str(exc), "type": exc.__class__.__name__}, status)

    def _send_exception_json(self, exc: Exception) -> None:
        if isinstance(exc, (KeyError, FileNotFoundError)):
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
            if path == "/api/health":
                self._send_json({"ok": True, "plugins": plugin_load_snapshot(self.state)})
            elif path == "/api/config":
                self._send_json(_app_config_response(self.state))
            elif path == "/api/config/network-proxy/detect":
                from config.network_proxy import detect_network_proxy_configuration

                self._send_json(detect_network_proxy_configuration().as_payload())
            elif path == "/api/config/tts-bundle/recommendation":
                self._send_json(_tts_bundle_recommendation())
            elif path == "/api/characters":
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
                self._send_json(_app_update_info())
            elif path == "/api/plugins/registry":
                self._send_json(_plugin_registry_rows())
            elif path == "/api/mcp/config":
                self._send_json(_mcp_config_response())
            elif path.startswith("/api/tasks/"):
                task_id = unquote(path.rsplit("/", 1)[-1])
                self._send_json(_get_task(self.state, task_id))
            elif path == "/api/chat/snapshot":
                self._send_json(_chat_snapshot(self.state))
            elif path == "/api/chat/history":
                self._send_json(_chat_history(self.state))
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
                query = parse_qs(parsed.query)
                target = unquote((query.get("path") or [""])[0])
                self._send_file(target, attachment=False)
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
            if path == "/api/download":
                query = parse_qs(parsed.query)
                target = unquote((query.get("path") or [""])[0])
                self._send_file(target, attachment=True, send_body=False)
            elif path == "/api/media":
                query = parse_qs(parsed.query)
                target = unquote((query.get("path") or [""])[0])
                self._send_file(target, attachment=False, send_body=False)
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
            path = urlparse(self.path).path
            self._require_authorized_write(path)
            is_upload = method == "POST" and path in {
                "/api/characters/import-upload",
                "/api/backgrounds/import-upload",
                "/api/logs/import-upload",
                "/api/chat/themes/upload",
            }
            body = {} if method == "DELETE" or is_upload else self._read_json()
            if method in {"POST", "PUT"} and path == "/api/config/api":
                self._send_json(_save_api_config(self.state, body))
            elif method in {"POST", "PUT"} and path == "/api/config/system":
                from config.schema import SystemConfig
                from config.mirror_env import REGION_AUTO

                config = SystemConfig.model_validate(body)
                config.mirror_region = REGION_AUTO
                self.state.config_manager.config.system_config = config
                self.state.config_manager.save_system_config()
                try:
                    from i18n import init_i18n

                    init_i18n(config.ui_language)
                except Exception:
                    pass
                self._send_json(config)
            elif method == "POST" and path == "/api/config/llm-models":
                try:
                    self._send_json(_fetch_llm_models(body))
                except Exception as exc:
                    from sdk.exception.presenter import format_llm_exception_message

                    message = format_llm_exception_message(exc, fallback_message="获取模型列表失败。")
                    self._send_json({"error": message, "type": exc.__class__.__name__}, HTTPStatus.BAD_REQUEST)
            elif method == "POST" and path == "/api/config/llm-connection-test":
                try:
                    self._send_json(_test_llm_connection(body))
                except Exception as exc:
                    from sdk.exception.presenter import format_llm_exception_message

                    message = format_llm_exception_message(exc, fallback_message="LLM 连通检测失败。")
                    self._send_json({"error": message, "type": exc.__class__.__name__}, HTTPStatus.BAD_REQUEST)
            elif method == "POST" and path == "/api/files/browse":
                self._send_json(_browse_local_files(self.state, body))
            elif method == "POST" and path == "/api/media/thumbnails":
                self._send_json(self._media_thumbnail_batch_response(body))
            elif method == "POST" and path == "/api/logs/read":
                self._send_json(_log_snapshot(self._resolve_project_path(str(body.get("path") or ""))))
            elif method == "POST" and path == "/api/logs/import-upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    self._send_json(_log_snapshot(paths[0]))
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
            elif method == "POST" and path.startswith("/api/tasks/") and path.endswith("/cancel"):
                task_id = unquote(path[len("/api/tasks/") : -len("/cancel")])
                self._send_json(_request_task_cancel(self.state, task_id))
            elif method in {"POST", "PUT"} and path == "/api/characters":
                self._send_json(_save_character(self.state, body))
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
                self._send_json(_upload_sprite_voice(self.state, body))
            elif method == "POST" and path == "/api/characters/sprites/upload":
                self._send_json(_upload_character_sprites(self.state, body))
            elif method == "POST" and path == "/api/characters/emotion-tags":
                self._send_json(_save_character_emotion_tags(self.state, body))
            elif method == "POST" and path == "/api/characters/sprites/delete":
                self._send_json(_delete_character_sprite(self.state, body))
            elif method == "POST" and path == "/api/characters/sprites/delete-all":
                self._send_json(_delete_all_character_sprites(self.state, body))
            elif method == "POST" and path == "/api/characters/sprite-scale":
                self._send_json(_save_sprite_scale(self.state, body))
            elif method == "POST" and path == "/api/characters/sprite-voice/text":
                self._send_json(_save_sprite_voice_text(self.state, body))
            elif method == "POST" and path == "/api/characters/sprite-voice/voice-type":
                self._send_json(_save_sprite_voice_type(self.state, body))
            elif method == "POST" and path == "/api/characters/sprite-voice/delete":
                self._send_json(_delete_sprite_voice(self.state, body))
            elif method == "DELETE" and path.startswith("/api/chat/themes/"):
                theme_id = unquote(path[len("/api/chat/themes/"):])
                self._send_json(delete_chat_theme(self.state, theme_id))
            elif method == "DELETE" and path.startswith("/api/characters/"):
                name = unquote(path.rsplit("/", 1)[-1])
                message, names = self.state.character_manager.delete_character(name)
                self._send_json({"message": message, "names": names})
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
                output = Path("output") / f"{name}.char"
                output.parent.mkdir(parents=True, exist_ok=True)
                import tools.file_util as file_util

                file_util.export_character([_as_character_config(character)], output.as_posix(), open_folder=False)
                self._send_json({"downloadUrl": f"/api/download?path={output.as_posix()}", "path": output.as_posix()})
            elif method == "POST" and path == "/api/backgrounds/translate":
                self._send_json(_translate_background_fields(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/images/upload":
                self._send_json(_upload_background_images(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/bgm/upload":
                self._send_json(_upload_background_bgm(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/images/delete":
                self._send_json(_delete_background_image(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/images/delete-all":
                self._send_json(_delete_all_background_images(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/bgm/delete":
                self._send_json(_delete_background_bgm(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/bgm/delete-all":
                self._send_json(_delete_all_background_bgm(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/tags":
                self._send_json(_save_background_image_tags(self.state, body))
            elif method == "POST" and path == "/api/backgrounds/bgm-tags":
                self._send_json(_save_background_bgm_tags(self.state, body))
            elif method in {"POST", "PUT"} and path == "/api/backgrounds":
                self._send_json(_save_background(self.state, body))
            elif method == "DELETE" and path.startswith("/api/backgrounds/"):
                name = unquote(path.rsplit("/", 1)[-1])
                message, names = self.state.background_manager.delete_background(name)
                if message.startswith("找不到") or message.startswith("请选择") or "失败" in message:
                    raise RuntimeError(message)
                self._send_json({"message": message, "names": names})
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
                output = Path("output") / f"{name}.bg"
                import tools.file_util as file_util

                file_util.export_background([background], output.as_posix(), open_folder=False)
                self._send_json({"downloadUrl": f"/api/download?path={output.as_posix()}", "path": output.as_posix()})
            # --- effects ---
            elif method == "POST" and path == "/api/effects/audio/upload":
                self._send_json(_upload_effect_audio(self.state, body))
            elif method == "POST" and path == "/api/effects/audio/delete":
                self._send_json(_delete_effect_audio(self.state, body))
            elif method == "POST" and path == "/api/effects/audio/delete-all":
                self._send_json(_delete_all_effect_audio(self.state, body))
            elif method == "POST" and path == "/api/effects/audio-tags":
                self._send_json(_save_effect_audio_tags(self.state, body))
            elif method in {"POST", "PUT"} and path == "/api/effects":
                self._send_json(_save_effect(self.state, body))
            elif method == "DELETE" and path.startswith("/api/effects/"):
                name = unquote(path.rsplit("/", 1)[-1])
                self._send_json(_delete_effect(self.state, name))
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
                output = Path("output") / f"{name}.ef"
                import tools.file_util as file_util

                file_util.export_effect([effect], output.as_posix(), open_folder=False)
                self._send_json({"downloadUrl": f"/api/download?path={output.as_posix()}", "path": output.as_posix()})
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
                    worker=lambda task_id: _install_plugin_source(
                        self.state,
                        task_id,
                        plugin_id,
                        ref_kind=ref_kind,
                        tag_name=tag_name,
                        overwrite=overwrite,
                    ),
                )
            elif method == "POST" and path == "/api/plugins/repo-tags":
                self._send_json(_repo_tags(body))
            elif method == "POST" and path == "/api/plugins/publisher/scan":
                self._send_json(_scan_local_plugin(body))
            elif method == "POST" and path == "/api/plugins/publisher/validate":
                self._send_json(_validate_plugin_submission(body))
            elif method == "POST" and path == "/api/plugins/publisher/issue-url":
                self._send_json(_build_plugin_submission_issue_url(body))
            elif method == "POST" and path == "/api/plugins/publisher/copy-json":
                self._send_json(_copy_plugin_submission_json(body))
            elif method == "POST" and path == "/api/plugins/app-update/tags":
                self._send_json(_app_update_tags())
            elif method == "POST" and path == "/api/plugins/app-update/run":
                ref_kind = str(body.get("refKind") or "latest").strip()
                tag_name = str(body.get("tagName") or "").strip()
                self._enqueue_background_task(
                    kind="app-update",
                    message="主程序更新任务已排队。",
                    title="更新主程序",
                    task_updates={"refKind": ref_kind, "tagName": tag_name},
                    worker=lambda task_id: _run_app_update(self.state, task_id, body),
                )
            elif method == "POST" and path.startswith("/api/plugins/") and path.endswith("/enabled"):
                plugin_id = unquote(path[len("/api/plugins/") : -len("/enabled")])
                self._send_json(_set_plugin_enabled(plugin_id, bool(body.get("enabled"))))
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
            elif method == "POST" and path == "/api/chat/close":
                self._send_json(_close_chat(self.state))
            elif method == "POST" and path == "/api/chat/command":
                self._send_json(_handle_chat_command(self.state, body))
            elif method == "POST" and path == "/api/chat/themes/active":
                self._send_json(set_active_chat_theme(self.state, body))
            elif method == "POST" and path == "/api/chat/themes/upload":
                temp_dir, paths = self._read_upload_files()
                try:
                    if not paths:
                        raise ValueError("未收到主题压缩包")
                    self._send_json(install_theme_from_zip(self.state, paths[0]))
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

    def _launch_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        if _chat_runtime_closing(self.state):
            raise RuntimeError("聊天会话正在关闭，请稍后再启动。")
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
        characters = body.get("characters") or []
        first_character = ""
        if isinstance(characters, list) and characters:
            first_character = str(characters[0])
        init_sprite_path = ""
        character = self.state.config_manager.get_character_by_name(first_character)
        if character and character.sprites:
            sprite = character.sprites[0]
            init_sprite_path = _sprite_path(sprite)
        init_sprite_path = str(body.get("initSpritePath") or init_sprite_path)
        room_id = str(body.get("roomId") or self.state.config_manager.config.system_config.live_room_id or "")
        history_path = _chat_history_path(self.state, body, row)
        default_history_path = _chat_history_path(
            self.state,
            {"historyPath": "", "characters": characters if isinstance(characters, list) else []},
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
            return _chat_snapshot(self.state, None, "", extra={"statusMessage": "进程已经在运行中。"})
        self.state.chat_session = {**self.state.chat_session, **session_base}
        initial_snapshot = _chat_snapshot(self.state, "idle", "")
        use_react_runtime = _chat_runtime_mode(self.state) == "react"
        stream_info = (
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
            character_names=characters if isinstance(characters, list) else [],
            effect_names=effect_names_str,
            history_file=(default_history_path if reset_history else history_path).as_posix(),
            init_sprite_path=init_sprite_path,
            room_id=room_id,
            selected_bg=str(body.get("backgroundName") or ""),
            system_template=system_template,
            use_cg=bool(body.get("useCg")),
            user_scenario=user_scenario,
            stream_endpoint=str(stream_info.get("producerEndpoint") or ""),
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
            "sessionId": str(stream_info.get("sessionId") or ""),
        }
        if stream_info.get("sessionId") and self.state.chat_stream is not None:
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
        return _chat_snapshot(self.state, "idle", "", extra={"statusMessage": message})

    def _resume_last_chat(self) -> dict[str, Any]:
        if _chat_runtime_closing(self.state):
            raise RuntimeError("聊天会话正在关闭，请稍后再启动。")
        session = _load_template_session_payload(self.state) or {}
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
        selected_characters = session.get("selectedCharacters") or []
        first_character = (
            str(selected_characters[0])
            if isinstance(selected_characters, list) and selected_characters
            else ""
        )
        init_sprite_path = str(session.get("initSpritePath") or "")
        if not init_sprite_path and first_character:
            character = self.state.config_manager.get_character_by_name(first_character)
            if character and character.sprites:
                init_sprite_path = _sprite_path(character.sprites[0])
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
            return _chat_snapshot(self.state, None, "", extra={"statusMessage": "进程已经在运行中。"})
        self.state.chat_session = {**self.state.chat_session, **session_base}
        initial_snapshot = _chat_snapshot(self.state, "idle", "")
        use_react_runtime = _chat_runtime_mode(self.state) == "react"
        stream_info = (
            self.state.chat_stream.create_session(initial_snapshot)
            if use_react_runtime and self.state.chat_stream is not None
            else {}
        )
        message = _launch_chat(
            self.state,
            character_names=selected_characters if isinstance(selected_characters, list) else [],
            history_file=history_path.resolve().as_posix(),
            init_sprite_path=init_sprite_path,
            room_id=room_id,
            selected_bg=selected_bg,
            system_template=system_template,
            use_cg=bool(session.get("useCg", False)),
            user_scenario=scenario,
            stream_endpoint=str(stream_info.get("producerEndpoint") or ""),
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
            "sessionId": str(stream_info.get("sessionId") or ""),
        }
        if stream_info.get("sessionId") and self.state.chat_stream is not None:
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
        return _chat_snapshot(self.state, "idle", "", extra={"statusMessage": message})

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
