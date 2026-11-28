"""Scoped HMAC token issuance, verification, and route authorization for plugins."""

from __future__ import annotations

import base64
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import hmac
import posixpath
import re
import threading
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, unquote, urlparse

from frontend_bridge_core.security import safe_header_value
from sdk.path_utils import reject_control_chars

PLUGIN_AUTH_COOKIE = "shinsekai_plugin_token"
PLUGIN_TOKEN_PREFIX = "shp1."
BRIDGE_AUTH_QUERY = "shinsekai_bridge_token"

_SIGNING_KEY_DOMAIN = b"shinsekai:plugin-token-key:v1"
_TOKEN_PAYLOAD_DOMAIN = b"v1:"
_MAX_ISSUED_TOKENS = 4096


@dataclass(frozen=True)
class _IssuedPluginToken:
    signing_key_id: bytes
    plugin_id: str
    token: str
    cookie_header: str


_ISSUED_LOCK = threading.RLock()
_ISSUED_TOKENS: OrderedDict[tuple[bytes, str], _IssuedPluginToken] = OrderedDict()

_SAFE_PLUGIN_GET_EXACT = frozenset(
    {
        "/api/health",
        "/api/chat/snapshot",
        "/api/chat/runtime-status",
        "/api/chat/history",
        "/api/characters",
        "/api/plugins/session-behaviors",
        "/api/plugins/chat-ui-contributions",
        "/api/media",
        "/api/avatar/file",
        "/api/avatar/runtime/file",
    }
)
_SELF_PLUGIN_POST_SUFFIXES = (
    re.compile(r"^/tools/[^/]+/invoke$"),
    re.compile(r"^/ui/[^/]+/actions/[^/]+$"),
    re.compile(r"^/ui/[^/]+/config$"),
    re.compile(r"^/chat-ui/[^/]+/run$"),
)


def _derive_signing_key(master_token: str) -> bytes:
    return hmac.new(
        master_token.encode("utf-8"),
        _SIGNING_KEY_DOMAIN,
        hashlib.sha256,
    ).digest()


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(encoded: str) -> bytes:
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(f"{encoded}{padding}".encode("ascii"))


def _signing_key_id(signing_key: bytes) -> bytes:
    return hashlib.sha256(signing_key).digest()


def issue_plugin_token(master_token: str, plugin_id: str) -> str:
    """Issue an HMAC-signed token scoped to a single plugin_id."""
    secret = str(master_token or "").strip()
    cleaned_plugin = str(plugin_id or "").strip()
    if not secret or not cleaned_plugin:
        return ""
    cleaned_plugin = reject_control_chars(cleaned_plugin, field="plugin_id")
    signing_key = _derive_signing_key(secret)
    payload_b64 = _b64url_encode(cleaned_plugin.encode("utf-8"))
    signature = hmac.new(
        signing_key,
        _TOKEN_PAYLOAD_DOMAIN + payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    token = f"{PLUGIN_TOKEN_PREFIX}{payload_b64}.{_b64url_encode(signature)}"
    cookie_path = f"/api/plugins/{safe_header_value(quote(cleaned_plugin, safe=''))}/"
    cookie_header = (
        f"{PLUGIN_AUTH_COOKIE}={safe_header_value(token)}; "
        f"Path={cookie_path}; "
        "HttpOnly; SameSite=Strict"
    )
    key_id = _signing_key_id(signing_key)
    cache_key = (key_id, cleaned_plugin)
    with _ISSUED_LOCK:
        _ISSUED_TOKENS[cache_key] = _IssuedPluginToken(
            signing_key_id=key_id,
            plugin_id=cleaned_plugin,
            token=token,
            cookie_header=cookie_header,
        )
        _ISSUED_TOKENS.move_to_end(cache_key)
        while len(_ISSUED_TOKENS) > _MAX_ISSUED_TOKENS:
            _ISSUED_TOKENS.popitem(last=False)
    return token


def verify_plugin_token(master_token: str, supplied_token: str) -> str | None:
    """Validate a scoped plugin token and return its bound plugin_id, or None."""
    secret = str(master_token or "").strip()
    raw = str(supplied_token or "").strip()
    if not secret or not raw or not raw.startswith(PLUGIN_TOKEN_PREFIX):
        return None
    try:
        reject_control_chars(raw, field="plugin_token")
    except ValueError:
        return None
    parts = raw.split(".")
    if len(parts) != 3 or parts[0] != "shp1" or not parts[1] or not parts[2]:
        return None
    payload_b64, supplied_sig = parts[1], parts[2]
    expected_sig = _b64url_encode(
        hmac.new(
            _derive_signing_key(secret),
            _TOKEN_PAYLOAD_DOMAIN + payload_b64.encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    if not hmac.compare_digest(supplied_sig, expected_sig):
        return None
    try:
        plugin_id = _b64url_decode(payload_b64).decode("utf-8").strip()
        if not plugin_id:
            return None
        return reject_control_chars(plugin_id, field="plugin_id")
    except (ValueError, UnicodeDecodeError):
        return None


def _has_dot_traversal(raw_path: str) -> bool:
    for segment in raw_path.split("/"):
        if segment in {".", ".."}:
            return True
        decoded = unquote(segment)
        if decoded in {".", ".."} or "\\" in decoded or "\x00" in decoded:
            return True
        if decoded.startswith("../") or "/../" in decoded or decoded.endswith("/.."):
            return True
    return False


def normalize_bridge_path(path: str) -> str:
    """Collapse relative segments on a URL path for boundary checks."""
    raw = unquote(str(path or "").split("?", 1)[0]).replace("\\", "/")
    if not raw:
        return "/"
    return posixpath.normpath("/" + raw.lstrip("/"))


def extract_plugin_path_owner(path: str) -> tuple[str, str] | None:
    """Extract (raw_segment, decoded_plugin_id) from `/api/plugins/<seg>/...`."""
    raw = str(path or "").split("?", 1)[0]
    if _has_dot_traversal(raw):
        return None
    prefix = "/api/plugins/"
    if not raw.startswith(prefix):
        return None
    rest = raw[len(prefix) :]
    if not rest:
        return None
    raw_segment, _, _ = rest.partition("/")
    if not raw_segment:
        return None
    decoded = unquote(raw_segment).strip()
    if not decoded or decoded in {".", ".."}:
        return None
    try:
        return raw_segment, reject_control_chars(decoded, field="plugin_id")
    except ValueError:
        return None


def _resolve_page_plugin_id(
    detail: Mapping[str, Any],
    page: Mapping[str, Any],
    url: str,
) -> str:
    plugin_meta = detail.get("plugin")
    detail_owner = (
        str(plugin_meta.get("id") or "").strip()
        if isinstance(plugin_meta, Mapping)
        else ""
    )
    page_owner = str(page.get("pluginId") or "").strip()
    parsed = urlparse(url)
    path_owner_pair = extract_plugin_path_owner(parsed.path)
    path_owner = path_owner_pair[1] if path_owner_pair is not None else ""
    explicit_owner = detail_owner or page_owner
    if explicit_owner and path_owner and explicit_owner != path_owner:
        return ""
    return explicit_owner or path_owner


def inject_scoped_plugin_tokens(state: Any, detail: dict[str, Any]) -> dict[str, Any]:
    """Attach plugin-scoped tokens (never the master bridge token) to page URLs."""
    master_token = str(getattr(state, "auth_token", "") or "").strip()
    if not master_token:
        return detail
    for page in detail.get("pages") or []:
        if not isinstance(page, dict):
            continue
        url = str(page.get("frontendUrl") or "")
        if not url.startswith("/api/") or BRIDGE_AUTH_QUERY in url:
            continue
        plugin_id = _resolve_page_plugin_id(detail, page, url)
        scoped = issue_plugin_token(master_token, plugin_id)
        if not scoped:
            continue
        separator = "&" if "?" in url else "?"
        page["frontendUrl"] = (
            f"{url}{separator}{BRIDGE_AUTH_QUERY}={quote(scoped, safe='')}"
        )
    return detail


def is_sensitive_master_only_read(path: str) -> bool:
    """Return True if path exposes host credentials, downloads, or agent controls."""
    normalized = normalize_bridge_path(path)
    return (
        normalized == "/api/config"
        or normalized.startswith("/api/config/")
        or normalized == "/api/download"
        or normalized == "/data/config"
        or normalized.startswith("/data/config/")
        or normalized == "/api/agent"
        or normalized.startswith("/api/agent/")
    )


def _is_self_plugin_get_allowed(raw_path: str, plugin_id: str) -> bool:
    owner_pair = extract_plugin_path_owner(raw_path)
    if owner_pair is None or owner_pair[1] != plugin_id:
        return False
    raw_seg = owner_pair[0]
    suffix = raw_path[len("/api/plugins/") + len(raw_seg) :]
    return suffix in {"/ui", "/tools", "/frontend"} or suffix.startswith("/frontend/")


def _is_self_plugin_post_allowed(raw_path: str, plugin_id: str) -> bool:
    owner_pair = extract_plugin_path_owner(raw_path)
    if owner_pair is None or owner_pair[1] != plugin_id:
        return False
    raw_seg = owner_pair[0]
    suffix = raw_path[len("/api/plugins/") + len(raw_seg) :]
    return any(pattern.fullmatch(suffix) is not None for pattern in _SELF_PLUGIN_POST_SUFFIXES)


def is_plugin_route_allowed(method: str, path: str, plugin_id: str) -> bool:
    """Enforce least-privilege route allowlist for plugin-scoped bridge tokens."""
    if not plugin_id:
        return False
    raw_path = str(path or "").split("?", 1)[0]
    if _has_dot_traversal(raw_path) or is_sensitive_master_only_read(raw_path):
        return False
    normalized = normalize_bridge_path(raw_path)
    if normalized == "/data" or normalized.startswith("/data/"):
        return False

    upper_method = str(method or "").strip().upper()
    if upper_method in {"GET", "HEAD", "OPTIONS"}:
        if normalized in _SAFE_PLUGIN_GET_EXACT:
            return True
        if normalized == "/assets" or normalized.startswith("/assets/"):
            return True
        if normalized.startswith("/api/tasks/") and not normalized.endswith("/cancel"):
            task_rest = normalized[len("/api/tasks/") :]
            return bool(task_rest and "/" not in task_rest)
        return _is_self_plugin_get_allowed(raw_path, plugin_id)

    if upper_method == "POST":
        if normalized == "/api/chat/behavior-command":
            return True
        return _is_self_plugin_post_allowed(raw_path, plugin_id)

    return False


def build_plugin_cookie_header(
    path: str,
    supplied_token: str,
    plugin_id: str,
) -> str | None:
    """Build a path-isolated HttpOnly Set-Cookie header for a plugin frontend path."""
    raw_path = str(path or "").split("?", 1)[0]
    owner_pair = extract_plugin_path_owner(raw_path)
    if owner_pair is None or owner_pair[1] != plugin_id:
        return None
    if not supplied_token:
        return None
    canonical_seg = quote(owner_pair[1], safe="")
    return (
        f"{PLUGIN_AUTH_COOKIE}={safe_header_value(supplied_token)}; "
        f"Path=/api/plugins/{safe_header_value(canonical_seg)}/; "
        "HttpOnly; SameSite=Strict"
    )


def resolve_issued_plugin_cookie_header(
    master_token: str,
    path: str,
    supplied_token: str,
) -> str | None:
    """Look up a server-constructed Set-Cookie string for a previously issued token."""
    secret = str(master_token or "").strip()
    raw_token = str(supplied_token or "").strip()
    if not secret or not raw_token or not raw_token.startswith(PLUGIN_TOKEN_PREFIX):
        return None
    raw_path = str(path or "").split("?", 1)[0]
    owner_pair = extract_plugin_path_owner(raw_path)
    if owner_pair is None:
        return None
    target_plugin_id = owner_pair[1]
    key_id = _signing_key_id(_derive_signing_key(secret))
    with _ISSUED_LOCK:
        for cache_key, entry in tuple(_ISSUED_TOKENS.items()):
            if (
                entry.signing_key_id == key_id
                and entry.plugin_id == target_plugin_id
                and hmac.compare_digest(raw_token, entry.token)
            ):
                _ISSUED_TOKENS.move_to_end(cache_key)
                return entry.cookie_header
    return None


__all__ = [
    "BRIDGE_AUTH_QUERY",
    "PLUGIN_AUTH_COOKIE",
    "PLUGIN_TOKEN_PREFIX",
    "build_plugin_cookie_header",
    "extract_plugin_path_owner",
    "inject_scoped_plugin_tokens",
    "is_plugin_route_allowed",
    "is_sensitive_master_only_read",
    "issue_plugin_token",
    "normalize_bridge_path",
    "resolve_issued_plugin_cookie_header",
    "verify_plugin_token",
]
