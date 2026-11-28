"""Origin checking, loopback detection, and token authorization mixin for HTTP bridge handlers."""

from __future__ import annotations

import hmac
import ipaddress
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse

from frontend_bridge_core.plugin_auth import (
    PLUGIN_AUTH_COOKIE,
    is_plugin_route_allowed,
    is_sensitive_master_only_read,
    verify_plugin_token,
)
from frontend_bridge_core.routes.plugin_routes import inject_bridge_token
from frontend_bridge_core.security import safe_header_value
from sdk.path_utils import reject_control_chars

BRIDGE_AUTH_HEADER = "X-Shinsekai-Bridge-Token"
BRIDGE_AUTH_QUERY = "shinsekai_bridge_token"
BRIDGE_AUTH_COOKIE = "shinsekai_bridge_token"

_ALLOWED_CUSTOM_ORIGIN_SCHEMES = {"shinsekai", "tauri"}
# WebView2 exposes registered Tauri protocols as http(s)://<scheme>.localhost.
_ALLOWED_LOCAL_ORIGIN_HOSTS = {
    "127.0.0.1",
    "::1",
    "localhost",
    "tauri.localhost",
    "shinsekai.localhost",
}


class BridgeHttpAuthMixin:
    """Shared origin validation, token parsing, and scoped route authorization checks."""

    state: Any
    headers: Any

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

    def _auth_context(self) -> tuple[str, str | None]:
        required = str(getattr(self.state, "auth_token", "") or "").strip()
        if not required:
            return ("master", None)

        header_token = str(self.headers.get(BRIDGE_AUTH_HEADER) or "").strip()
        if header_token:
            if hmac.compare_digest(header_token, required):
                return ("master", None)
            plugin_id = verify_plugin_token(required, header_token)
            return ("plugin", plugin_id) if plugin_id is not None else ("invalid", None)

        parsed = urlparse(getattr(self, "path", ""))
        query = parse_qs(parsed.query)
        query_token = str(
            (query.get(BRIDGE_AUTH_QUERY) or query.get("token") or [""])[0]
        ).strip()
        if query_token:
            if hmac.compare_digest(query_token, required):
                return ("master", None)
            plugin_id = verify_plugin_token(required, query_token)
            return ("plugin", plugin_id) if plugin_id is not None else ("invalid", None)

        cookie = SimpleCookie()
        try:
            cookie.load(str(self.headers.get("Cookie") or ""))
        except Exception:
            return ("none", None)
        plugin_morsel = cookie.get(PLUGIN_AUTH_COOKIE)
        if plugin_morsel is not None and str(plugin_morsel.value or "").strip():
            plugin_id = verify_plugin_token(required, str(plugin_morsel.value).strip())
            return ("plugin", plugin_id) if plugin_id is not None else ("invalid", None)
        morsel = cookie.get(BRIDGE_AUTH_COOKIE)
        master_cookie = str(morsel.value if morsel is not None else "").strip()
        if master_cookie:
            if hmac.compare_digest(master_cookie, required):
                return ("master", None)
            return ("invalid", None)
        return ("none", None)

    def _has_valid_auth_token(self) -> bool:
        return self._has_master_auth_token()

    def _has_master_auth_token(self) -> bool:
        kind, _plugin_id = self._auth_context()
        return kind == "master"

    def _authenticated_plugin_id(self) -> str | None:
        if getattr(self, "server", None) is None:
            return None
        kind, plugin_id = self._auth_context()
        return plugin_id if kind == "plugin" else None

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
        auth_kind, plugin_id = self._auth_context()
        if auth_kind == "invalid":
            if path.startswith("/api/agent/"):
                raise PermissionError("invalid Agent bridge authorization")
            raise PermissionError("invalid bridge auth token")
        if is_sensitive_master_only_read(path):
            if not self._request_origin_allowed() or auth_kind != "master":
                if path.startswith("/api/agent/"):
                    raise PermissionError("invalid Agent bridge authorization")
                raise PermissionError("invalid bridge auth token")
            return
        if path.startswith("/api/plugins/") and path.endswith("/tools"):
            allowed = self._request_origin_allowed() and (
                auth_kind == "master"
                or (
                    auth_kind == "plugin"
                    and plugin_id is not None
                    and is_plugin_route_allowed("GET", path, plugin_id)
                )
            )
            if not allowed:
                raise PermissionError("invalid Agent bridge authorization")
            return
        if auth_kind == "plugin":
            if plugin_id is None or not is_plugin_route_allowed("GET", path, plugin_id):
                raise PermissionError("plugin token is not authorized for this route")
            return
        # Project-backed static roots share the same LAN authorization boundary
        # as APIs. Protecting /assets/ also closes alternate spellings such as
        # /assets/../data/... before path normalization reaches file transport.
        protected_path = path.startswith(("/api/", "/assets/", "/data/"))
        if (
            protected_path
            and not self._is_loopback_client()
            and auth_kind != "master"
        ):
            raise PermissionError("invalid bridge auth token")

    def _inject_bridge_token(self, detail: dict[str, Any]) -> dict[str, Any]:
        return inject_bridge_token(self.state, detail)

    def _require_authorized_write(self, path: str, method: str = "POST") -> None:
        if not self._request_origin_allowed():
            raise PermissionError("request origin is not allowed")
        if path.startswith("/api/"):
            auth_kind, plugin_id = self._auth_context()
            if auth_kind == "master":
                return
            if (
                auth_kind == "plugin"
                and plugin_id is not None
                and is_plugin_route_allowed(
                    str(getattr(self, "command", method) or method),
                    path,
                    plugin_id,
                )
            ):
                return
            raise PermissionError("invalid bridge auth token")

    def _require_authorized_media_read(self) -> None:
        if not self._request_origin_allowed():
            raise PermissionError("request origin is not allowed")
        auth_kind, plugin_id = self._auth_context()
        if auth_kind == "master":
            return
        if auth_kind == "plugin" and plugin_id is not None:
            raw_path = urlparse(getattr(self, "path", "")).path
            if is_plugin_route_allowed("GET", raw_path, plugin_id):
                return
        raise PermissionError("invalid bridge auth token")


__all__ = [
    "BRIDGE_AUTH_COOKIE",
    "BRIDGE_AUTH_HEADER",
    "BRIDGE_AUTH_QUERY",
    "BridgeHttpAuthMixin",
]
