from __future__ import annotations

import mimetypes
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote

from application.chat.runtime_process import _chat_history_download_file
from frontend_bridge_core.media import _media_thumbnail, _media_thumbnail_batch
from frontend_bridge_core.media_paths import (
    is_absolute_local_media_path_text,
    iter_configured_external_media_paths,
    resolve_external_media_file,
    validate_readable_media_file,
)
from frontend_bridge_core.plugin_ui import _resolve_plugin_frontend_file
from frontend_bridge_core.security import (
    safe_content_disposition,
    safe_header_value,
)
from frontend_bridge_core.static import _frontend_dist_root
from sdk.logging import get_logger
from sdk.path_utils import safe_child_path, safe_project_path

logger = get_logger(__name__)


class RangeNotSatisfiable(Exception):
    pass


def resolve_project_path(raw_path: str) -> Path:
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


def resolve_media_path(state: Any, raw_path: str) -> Path:
    raw = str(raw_path or "").strip()
    if not raw:
        raise FileNotFoundError(raw_path)
    if is_absolute_local_media_path_text(raw):
        config_manager = getattr(state, "config_manager", None)
        config = getattr(config_manager, "config", None)
        approved_paths = list(iter_configured_external_media_paths(config))
        chat_stream = getattr(state, "chat_stream", None)
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
        resolve_project_path(raw),
        roots=[Path.cwd()],
    )


def media_thumbnail_batch_response(body: dict[str, Any]) -> dict[str, Any]:
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
            items.append((raw_path, resolve_project_path(raw_path)))
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


class FileTransport:
    def __init__(self, handler: Any) -> None:
        self.handler = handler

    @property
    def state(self) -> Any:
        return self.handler.state

    def resolve_project_path(self, raw_path: str) -> Path:
        return resolve_project_path(raw_path)

    def resolve_media_path(self, raw_path: str) -> Path:
        return resolve_media_path(self.state, raw_path)

    @staticmethod
    def resolve_static_path(root: Path, request_path: str) -> Path:
        return safe_child_path(root, request_path)

    @staticmethod
    def media_thumbnail_batch_response(body: dict[str, Any]) -> dict[str, Any]:
        return media_thumbnail_batch_response(body)

    def send_local_file(
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
            byte_range = (
                self.handler._parse_byte_range(
                    self.handler.headers.get("Range"),
                    file_size,
                )
                if not attachment
                else None
            )
        except RangeNotSatisfiable:
            self.handler._send_range_not_satisfiable(file_size)
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
        self.handler.send_response(response_status)
        self.handler._send_cors()
        self.handler.send_header("Content-Type", content_type)
        self.handler.send_header("Accept-Ranges", "bytes")
        self.handler.send_header("Content-Length", str(content_length))
        if byte_range is not None:
            self.handler.send_header(
                "Content-Range",
                f"bytes {start}-{end}/{file_size}",
            )
        if attachment:
            self.handler.send_header(
                "Content-Disposition",
                safe_content_disposition(safe_name),
            )
        try:
            self.handler.end_headers()
            if not send_body:
                return
            with path.open("rb") as file:
                file.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk = file.read(min(1024 * 512, remaining))
                    if not chunk:
                        break
                    self.handler.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def send_range_not_satisfiable(self, file_size: int) -> None:
        self.handler.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
        self.handler._send_cors()
        self.handler.send_header("Accept-Ranges", "bytes")
        self.handler.send_header("Content-Range", f"bytes */{file_size}")
        self.handler.send_header("Content-Length", "0")
        try:
            self.handler.end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    @staticmethod
    def parse_byte_range(
        range_header: str | None,
        file_size: int,
    ) -> tuple[int, int] | None:
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
            raise RangeNotSatisfiable
        return start, min(end, file_size - 1)

    def try_send_frontend(
        self,
        request_path: str,
        *,
        send_body: bool = True,
    ) -> bool:
        dist_root = _frontend_dist_root(self.state)
        if dist_root is None or not dist_root.is_dir():
            return False
        index_path = dist_root / "index.html"
        if not index_path.is_file():
            return False

        if request_path in {"", "/", "/index.html"}:
            self.send_local_file(index_path, send_body=send_body)
            return True

        candidate = self.resolve_static_path(dist_root, request_path)
        if candidate.is_file():
            self.send_local_file(candidate, send_body=send_body)
            return True

        if request_path.startswith("/web-assets/"):
            raise FileNotFoundError(request_path)

        self.send_local_file(index_path, send_body=send_body)
        return True

    def send_file(
        self,
        relative_path: str,
        *,
        attachment: bool = False,
        send_body: bool = True,
    ) -> None:
        self.send_local_file(
            self.resolve_project_path(relative_path),
            attachment=attachment,
            send_body=send_body,
        )

    def send_media_file(
        self,
        path: str,
        *,
        send_body: bool = True,
    ) -> None:
        self.send_local_file(
            self.resolve_media_path(path),
            attachment=False,
            send_body=send_body,
        )

    def send_media_thumbnail(
        self,
        relative_path: str,
        size: str,
        *,
        send_body: bool = True,
    ) -> None:
        source = self.resolve_project_path(relative_path)
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
        self.send_local_file(
            thumbnail,
            attachment=False,
            send_body=send_body,
        )


def dispatch_file_request(
    handler: Any,
    path: str,
    query_string: str,
    *,
    send_body: bool,
) -> bool:
    if path.startswith("/api/plugins/") and "/frontend/" in path:
        rest = path[len("/api/plugins/") :]
        plugin_part, _, frontend_tail = rest.partition("/frontend/")
        page_part, _, asset_part = frontend_tail.partition("/")
        handler._send_local_file(
            _resolve_plugin_frontend_file(
                unquote(plugin_part),
                unquote(page_part),
                unquote(asset_part),
            ),
            send_body=send_body,
        )
        return True
    if path == "/api/chat/history-file":
        if not handler._request_origin_allowed():
            raise PermissionError("request origin is not allowed")
        query = parse_qs(query_string)
        capability = str((query.get("cap") or [""])[0])
        history_file = _chat_history_download_file(handler.state, capability)
        if send_body:
            handler._send_local_file(history_file, attachment=True)
        else:
            handler._send_local_file(
                history_file,
                attachment=True,
                send_body=False,
            )
        return True
    if path == "/api/download":
        query = parse_qs(query_string)
        target = unquote((query.get("path") or [""])[0])
        if send_body:
            handler._send_file(target, attachment=True)
        else:
            handler._send_file(target, attachment=True, send_body=False)
        return True
    if path == "/api/media":
        handler._require_authorized_media_read()
        query = parse_qs(query_string)
        target = unquote((query.get("path") or [""])[0])
        if send_body:
            handler._send_media_file(target)
        else:
            handler._send_media_file(target, send_body=False)
        return True
    if path == "/api/media/thumbnail":
        query = parse_qs(query_string)
        target = unquote((query.get("path") or [""])[0])
        size = (query.get("size") or ["160"])[0]
        if send_body:
            handler._send_media_thumbnail(target, size)
        else:
            handler._send_media_thumbnail(target, size, send_body=False)
        return True
    if path.startswith("/assets/") or path.startswith("/data/"):
        if send_body:
            handler._send_file(path.lstrip("/"))
        else:
            handler._send_file(path.lstrip("/"), send_body=False)
        return True
    if path.startswith("/api/"):
        return False
    if send_body:
        return handler._try_send_frontend(path)
    return handler._try_send_frontend(path, send_body=False)
