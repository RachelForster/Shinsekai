"""Public HTTP(S) egress validation, DNS pinning, and hop-by-hop redirect resolution."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
import contextlib
import ipaddress
import socket
import threading
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests

from sdk.path_utils import reject_control_chars


REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
DEFAULT_MAX_REDIRECTS = 5

_DNS_PIN_LOCK = threading.RLock()
_PINNED_HOST_ADDRINFOS: dict[int, tuple[str, list[Any]]] = {}
_ORIGINAL_GETADDRINFO: Callable[..., list[Any]] | None = None

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
DnsResolver = Callable[..., Sequence[Any]]


def is_public_ip(raw_ip: str | IpAddress) -> bool:
    """Return True only when ``raw_ip`` is globally routable on the public Internet."""
    if isinstance(raw_ip, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        addr: IpAddress = raw_ip
    else:
        ip_text = str(raw_ip or "").strip()
        if "%" in ip_text:
            ip_text = ip_text.split("%", 1)[0]
        try:
            addr = ipaddress.ip_address(ip_text)
        except ValueError:
            return False

    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped

    return bool(
        addr.is_global
        and not addr.is_loopback
        and not addr.is_private
        and not addr.is_link_local
        and not addr.is_reserved
        and not addr.is_multicast
        and not addr.is_unspecified
    )


def is_bilibili_target(target_spec: str) -> bool:
    """Return True if ``target_spec`` is a Bilibili search prefix or a verified Bilibili hostname URL."""
    spec = str(target_spec or "").strip()
    if not spec:
        return False
    if spec.lower().startswith("bilisearch"):
        return True
    parsed = urlsplit(spec)
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").rstrip(".").lower()
    return (
        host == "bilibili.com"
        or host.endswith(".bilibili.com")
        or host == "b23.tv"
        or host.endswith(".b23.tv")
    )


def _extract_ip_from_addrinfo(entry: Any) -> str:
    sockaddr = entry[4]
    ip_text = str(sockaddr[0]).strip()
    if "%" in ip_text:
        ip_text = ip_text.split("%", 1)[0]
    return ip_text


def validate_public_http_url(
    raw_url: str,
    *,
    resolve_dns: bool = True,
    resolver: DnsResolver | None = None,
) -> tuple[str, list[Any]]:
    """Validate an HTTP(S) URL and verify all literal or DNS-resolved IPs are public."""
    cleaned = reject_control_chars(str(raw_url or ""), field="url")
    parsed = urlsplit(cleaned)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"不支持的音频/视频链接协议：{cleaned}")
    if parsed.username or parsed.password:
        raise ValueError(f"禁止在音频/视频链接中携带凭据：{cleaned}")

    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError(f"无效的链接端口：{cleaned}") from exc

    host = parsed.hostname.strip().rstrip(".").lower()
    if (
        not host
        or host in {"localhost", "localhost.localdomain", "0.0.0.0"}
        or host.endswith((".localhost", ".local"))
    ):
        raise ValueError(f"禁止访问本地或内网主机：{cleaned}")

    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        if not is_public_ip(literal_ip):
            raise ValueError(f"禁止访问内网或保留地址：{cleaned}")
        return cleaned, []

    if not resolve_dns:
        return cleaned, []

    lookup = resolver or socket.getaddrinfo
    try:
        records = list(lookup(host, port, type=socket.SOCK_STREAM))
    except (OSError, ValueError) as exc:
        raise ValueError(f"无法解析目标域名（{host}）：{cleaned}") from exc

    if not records:
        raise ValueError(f"目标域名未返回有效地址（{host}）：{cleaned}")

    for record in records:
        try:
            ip_text = _extract_ip_from_addrinfo(record)
            parsed_ip = ipaddress.ip_address(ip_text)
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"目标域名解析结果无效（{host}）：{cleaned}") from exc
        if not is_public_ip(parsed_ip):
            raise ValueError(f"禁止访问解析到内网或保留地址的链接：{cleaned} ({ip_text})")

    return cleaned, records


def _pinned_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> list[Any]:
    tid = threading.get_ident()
    with _DNS_PIN_LOCK:
        pinned = _PINNED_HOST_ADDRINFOS.get(tid)
        orig = _ORIGINAL_GETADDRINFO
    if pinned is not None and isinstance(host, str):
        pinned_host, records = pinned
        if host.strip().rstrip(".").lower() == pinned_host and records:
            return list(records)
    if orig is None:  # pragma: no cover
        raise OSError("socket.getaddrinfo unavailable")
    return list(orig(host, port, *args, **kwargs))


@contextlib.contextmanager
def _pin_validated_dns(host: str, records: Sequence[Any]) -> Iterator[None]:
    """Pin DNS resolution for ``host`` on the current thread to prevent 0-TTL DNS rebinding."""
    global _ORIGINAL_GETADDRINFO
    if not records:
        yield
        return

    tid = threading.get_ident()
    normalized_host = host.strip().rstrip(".").lower()
    with _DNS_PIN_LOCK:
        if not _PINNED_HOST_ADDRINFOS:
            _ORIGINAL_GETADDRINFO = socket.getaddrinfo
            socket.getaddrinfo = _pinned_getaddrinfo  # type: ignore[assignment]
        _PINNED_HOST_ADDRINFOS[tid] = (normalized_host, list(records))
    try:
        yield
    finally:
        with _DNS_PIN_LOCK:
            _PINNED_HOST_ADDRINFOS.pop(tid, None)
            if not _PINNED_HOST_ADDRINFOS and _ORIGINAL_GETADDRINFO is not None:
                socket.getaddrinfo = _ORIGINAL_GETADDRINFO  # type: ignore[assignment]
                _ORIGINAL_GETADDRINFO = None


def _close_response(resp: Any) -> None:
    close_fn = getattr(resp, "close", None)
    if callable(close_fn):
        close_fn()


@contextlib.contextmanager
def open_public_http_stream(
    session: requests.Session,
    url: str,
    *,
    timeout: float = 45.0,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    resolver: DnsResolver | None = None,
) -> Iterator[tuple[str, Any]]:
    """Open a streaming HTTP GET while validating DNS/IP safety on every redirect hop before connecting."""
    current_url = url
    resp: Any = None
    for hop in range(max_redirects + 1):
        validated_url, addr_records = validate_public_http_url(
            current_url,
            resolve_dns=True,
            resolver=resolver,
        )
        host = (urlsplit(validated_url).hostname or "").strip().rstrip(".").lower()
        with _pin_validated_dns(host, addr_records):
            resp = session.get(
                validated_url,
                stream=True,
                timeout=timeout,
                allow_redirects=False,
            )

        status_code = int(getattr(resp, "status_code", 200) or 200)
        headers = getattr(resp, "headers", None) or {}
        location = str(headers.get("Location") or headers.get("location") or "").strip()
        if status_code in REDIRECT_STATUS_CODES and location:
            _close_response(resp)
            resp = None
            if hop >= max_redirects:
                raise ValueError(f"音频/视频链接重定向次数过多（>{max_redirects}）：{url}")
            current_url = urljoin(validated_url, location)
            continue

        try:
            yield validated_url, resp
        finally:
            _close_response(resp)
        return

    raise ValueError(f"音频/视频链接重定向次数过多（>{max_redirects}）：{url}")  # pragma: no cover


def resolve_public_http_redirects(
    url: str,
    *,
    user_agent: str = "",
    timeout: float = 20.0,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    resolver: DnsResolver | None = None,
) -> str:
    """Resolve all HTTP redirects hop-by-hop, validating public DNS/IP before each hop."""
    session = requests.Session()
    if user_agent:
        session.headers.update({"User-Agent": user_agent})
    try:
        with open_public_http_stream(
            session,
            url,
            timeout=timeout,
            max_redirects=max_redirects,
            resolver=resolver,
        ) as (final_url, _resp):
            return final_url
    finally:
        session.close()


__all__ = [
    "DEFAULT_MAX_REDIRECTS",
    "REDIRECT_STATUS_CODES",
    "is_bilibili_target",
    "is_public_ip",
    "open_public_http_stream",
    "resolve_public_http_redirects",
    "validate_public_http_url",
]
