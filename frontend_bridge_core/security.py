from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+$")
_SAFE_COMMAND_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
_SAFE_SEARCH_RE = re.compile(r"^[\w\s.,:;!?()\[\]'\"+&/@#-]{1,200}$", re.UNICODE)


def reject_control_chars(value: str, *, field: str = "value") -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    if _CONTROL_CHARS_RE.search(text):
        raise ValueError(f"{field} contains control characters")
    return text


def safe_header_value(value: str) -> str:
    return reject_control_chars(value, field="header")


def safe_content_disposition(filename: str) -> str:
    safe_name = Path(reject_control_chars(filename, field="filename")).name
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", safe_name).strip("._") or "download"
    encoded = quote(safe_name, safe="")
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'


def _safe_host(host: str) -> str:
    host = reject_control_chars(host, field="host").lower().rstrip(".")
    if not _HOST_RE.fullmatch(host):
        raise ValueError("URL host is invalid")
    return host


def host_matches(host: str, allowed_hosts: set[str]) -> bool:
    safe_host = _safe_host(host)
    normalized_allowed = {_safe_host(item) for item in allowed_hosts}
    return any(safe_host == allowed or safe_host.endswith(f".{allowed}") for allowed in normalized_allowed)


def validated_http_url(
    raw_url: str,
    *,
    allowed_hosts: set[str] | None = None,
    allow_localhost: bool = False,
    allow_private_hosts: bool = False,
    field: str = "url",
) -> str:
    url = reject_control_chars(raw_url, field=field)
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{field} must use http or https")
    if not parsed.hostname:
        raise ValueError(f"{field} must include a host")

    host = _safe_host(parsed.hostname)
    if allowed_hosts is not None and not host_matches(host, allowed_hosts):
        raise ValueError(f"{field} host is not allowed")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_loopback and not allow_localhost:
            raise ValueError(f"{field} loopback IP is not allowed")
        if ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(f"{field} special-use IP is not allowed")
        if ip.is_private and not allow_private_hosts:
            raise ValueError(f"{field} private IP is not allowed")
    elif host in {"localhost", "localhost.localdomain"} and not allow_localhost:
        raise ValueError(f"{field} localhost is not allowed")

    netloc = host
    if parsed.port is not None:
        netloc = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path or "", parsed.query or "", ""))


def validated_origin(raw_origin: str, *, allowed_ports: set[int]) -> str:
    origin = validated_http_url(
        raw_origin,
        allow_localhost=True,
        allow_private_hosts=True,
        field="origin",
    )
    parsed = urlsplit(origin)
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("origin must not include path, query, or fragment")
    if parsed.port not in allowed_ports:
        raise ValueError("origin port is not allowed")
    return safe_header_value(origin)


def safe_project_path(raw_path: str | os.PathLike[str], root: Path | None = None) -> Path:
    base = (root or Path.cwd()).resolve()
    raw = reject_control_chars(os.fspath(raw_path), field="path")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve(strict=False)
    if os.path.commonpath([str(base), str(resolved)]) != str(base):
        raise PermissionError("path is outside project root")
    return resolved


def safe_child_path(base: Path, raw_path: str | os.PathLike[str]) -> Path:
    root = base.resolve()
    raw = reject_control_chars(os.fspath(raw_path), field="path")
    resolved = (root / raw.lstrip("/\\")).resolve(strict=False)
    if os.path.commonpath([str(root), str(resolved)]) != str(root):
        raise PermissionError("path is outside base path")
    return resolved


def safe_existing_path(raw_path: str | os.PathLike[str], *, field: str = "path") -> Path:
    raw = reject_control_chars(os.fspath(raw_path), field=field)
    return Path(raw).expanduser().resolve(strict=True)


def safe_existing_file_path(raw_path: str | os.PathLike[str], *, field: str = "path") -> Path:
    path = safe_existing_path(raw_path, field=field)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def safe_existing_dir_path(raw_path: str | os.PathLike[str], *, field: str = "path") -> Path:
    path = safe_existing_path(raw_path, field=field)
    if not path.is_dir():
        raise NotADirectoryError(path)
    return path


def safe_filename(raw_name: str, *, default_suffix: str = "") -> str:
    raw = reject_control_chars(raw_name, field="filename")
    if "/" in raw or "\\" in raw:
        raise ValueError("filename must not contain path separators")
    name = Path(raw).name
    if not name or name in {".", ".."}:
        raise ValueError("filename is invalid")
    if name != raw:
        raise ValueError("filename must not contain path separators")
    if default_suffix and not name.endswith(default_suffix):
        name = f"{name}{default_suffix}"
    return name


def safe_executable(raw_executable: str, *, default: str) -> str:
    raw = str(raw_executable or "").strip() or default
    raw = reject_control_chars(raw, field="executable")
    if "/" not in raw and "\\" not in raw:
        if not _SAFE_COMMAND_RE.fullmatch(raw):
            raise ValueError("executable name is invalid")
        return raw
    path = Path(raw).expanduser().resolve(strict=False)
    if not path.is_file():
        raise FileNotFoundError(path)
    return str(path)


def safe_search_query(query: str) -> str:
    text = reject_control_chars(query, field="search query")
    if not _SAFE_SEARCH_RE.fullmatch(text):
        raise ValueError("search query contains unsupported characters")
    return text
