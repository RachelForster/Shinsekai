from __future__ import annotations

import ipaddress
import socket
from types import SimpleNamespace

import pytest
import requests

from sdk.url_safety import (
    _pin_validated_dns,
    is_bilibili_target,
    is_public_ip,
    open_public_http_stream,
    resolve_public_http_redirects,
    validate_public_http_url,
)


def _addrinfo(ip: str, port: int = 443):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sockaddr = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
    return [(family, socket.SOCK_STREAM, 6, "", sockaddr)]


def test_is_public_ip_distinguishes_global_from_private_and_special_ranges():
    assert is_public_ip("1.1.1.1") is True
    assert is_public_ip("8.8.8.8") is True
    assert is_public_ip(ipaddress.ip_address("2606:4700:4700::1111")) is True
    assert is_public_ip("2606:4700:4700::1111%0") is True

    for non_public in (
        "",
        "not-an-ip",
        "0.0.0.0",
        "127.0.0.1",
        "10.0.0.8",
        "172.16.5.4",
        "192.168.1.20",
        "169.254.169.254",
        "100.64.0.1",
        "224.0.0.1",
        "::1",
        "fe80::1%eth0",
        "::ffff:127.0.0.1",
        "::ffff:192.168.1.1",
    ):
        assert is_public_ip(non_public) is False, non_public


def test_is_bilibili_target_uses_parsed_hostname_boundaries():
    assert is_bilibili_target("bilisearch1:山田凉 语音合集") is True
    assert is_bilibili_target("https://www.bilibili.com/video/BV1xx411c7mD") is True
    assert is_bilibili_target("https://bilibili.com/video/BV1xx411c7mD") is True
    assert is_bilibili_target("https://b23.tv/abcdef") is True
    assert is_bilibili_target("https://m.b23.tv/abcdef") is True

    for untrusted in (
        "",
        "ytsearch1:ryo yamada",
        "ftp://www.bilibili.com/video/BV1xx411c7mD",
        "https://evil.example/video?redirect=https://www.bilibili.com/video/BV1xx411c7mD",
        "https://notbilibili.com/video/BV1xx411c7mD",
        "https://bilibili.com.evil.example/video/BV1xx411c7mD",
        "https://evilb23.tv/abcdef",
    ):
        assert is_bilibili_target(untrusted) is False, untrusted


def test_validate_public_http_url_rejects_bad_schemes_credentials_and_private_dns():
    for bad_url in (
        "ftp://example.com/a.wav",
        "file:///etc/passwd",
        "https:///missing-host",
        "https://user:secret@example.com/a.wav",
        "https://example.com:99999/a.wav",
        "http://localhost:9880/tts",
        "http://sub.localhost/a.wav",
        "http://printer.local/a.wav",
        "http://0.0.0.0/a.wav",
        "http://127.0.0.1/a.wav",
        "http://[::1]/a.wav",
    ):
        with pytest.raises(ValueError):
            validate_public_http_url(bad_url)

    cleaned, records = validate_public_http_url("https://1.1.1.1/audio.wav")
    assert cleaned == "https://1.1.1.1/audio.wav"
    assert records == []

    cleaned_no_dns, records_no_dns = validate_public_http_url(
        "https://media.example.com/audio.wav",
        resolve_dns=False,
    )
    assert cleaned_no_dns == "https://media.example.com/audio.wav"
    assert records_no_dns == []

    # DNS failure / empty / malformed / mixed public+private must all fail
    with pytest.raises(ValueError, match="无法解析"):
        validate_public_http_url(
            "https://dead.example.com/a.wav",
            resolver=lambda *_a, **_kw: (_ for _ in ()).throw(socket.gaierror("nxdomain")),
        )
    with pytest.raises(ValueError, match="未返回有效地址"):
        validate_public_http_url("https://empty.example.com/a.wav", resolver=lambda *_a, **_kw: [])
    with pytest.raises(ValueError, match="解析结果无效"):
        validate_public_http_url("https://bad.example.com/a.wav", resolver=lambda *_a, **_kw: [("bad",)])
    with pytest.raises(ValueError, match="内网或保留地址"):
        validate_public_http_url(
            "https://dual.example.com/a.wav",
            resolver=lambda *_a, **_kw: _addrinfo("1.1.1.1") + _addrinfo("10.0.0.2"),
        )

    ok_url, ok_records = validate_public_http_url(
        "https://cdn.example.com/voice.wav",
        resolver=lambda *_a, **_kw: _addrinfo("1.1.1.1"),
    )
    assert ok_url == "https://cdn.example.com/voice.wav"
    assert len(ok_records) == 1


def test_redirect_validation_blocks_private_hops_before_connecting_and_pins_dns(monkeypatch):
    dns_map = {
        "short.example.com": _addrinfo("1.1.1.1", 443),
        "cdn.example.com": _addrinfo("8.8.8.8", 443),
        "internal.example.com": _addrinfo("192.168.1.88", 80),
    }

    def fake_resolver(host, port, type=0):
        return dns_map[host]

    visited: list[tuple[str, bool]] = []

    def fake_get(self, url, *args, **kwargs):
        visited.append((url, kwargs.get("allow_redirects")))
        if url == "https://short.example.com/good":
            return SimpleNamespace(
                status_code=302,
                headers={"Location": "https://cdn.example.com/voice.wav"},
                close=lambda: None,
            )
        if url == "https://short.example.com/to-loopback":
            return SimpleNamespace(
                status_code=302,
                headers={"Location": "http://127.0.0.1:9880/secret"},
                close=lambda: None,
            )
        if url == "https://short.example.com/to-private-dns":
            return SimpleNamespace(
                status_code=301,
                headers={"Location": "http://internal.example.com/audio.wav"},
                close=lambda: None,
            )
        if url.startswith("https://short.example.com/loop"):
            return SimpleNamespace(
                status_code=302,
                headers={"Location": "/loop-next"},
                close=lambda: None,
            )
        return SimpleNamespace(status_code=200, headers={"Content-Type": "audio/wav"}, close=lambda: None)

    monkeypatch.setattr(requests.Session, "get", fake_get)

    resolved = resolve_public_http_redirects(
        "https://short.example.com/good",
        user_agent="test-agent",
        resolver=fake_resolver,
    )
    assert resolved == "https://cdn.example.com/voice.wav"
    assert visited == [
        ("https://short.example.com/good", False),
        ("https://cdn.example.com/voice.wav", False),
    ]

    visited.clear()
    with pytest.raises(ValueError, match="内网或保留地址"):
        resolve_public_http_redirects("https://short.example.com/to-loopback", resolver=fake_resolver)
    assert visited == [("https://short.example.com/to-loopback", False)]

    visited.clear()
    with pytest.raises(ValueError, match="内网或保留地址"):
        resolve_public_http_redirects("https://short.example.com/to-private-dns", resolver=fake_resolver)
    assert visited == [("https://short.example.com/to-private-dns", False)]

    dns_map["short.example.com"] = _addrinfo("1.1.1.1", 443)
    with pytest.raises(ValueError, match="重定向次数过多"):
        with requests.Session() as sess:
            with open_public_http_stream(
                sess,
                "https://short.example.com/loop",
                max_redirects=2,
                resolver=fake_resolver,
            ):
                pass

    # Verify _pin_validated_dns prevents second-lookup DNS rebinding while delegating other hosts
    rebind_calls = 0

    def rebinding_getaddrinfo(host, port, *args, **kwargs):
        nonlocal rebind_calls
        rebind_calls += 1
        if host == "rebind.example.com":
            return _addrinfo("127.0.0.1", port)
        return _addrinfo("9.9.9.9", port)

    monkeypatch.setattr(socket, "getaddrinfo", rebinding_getaddrinfo)
    pinned_records = _addrinfo("1.1.1.1", 443)
    with _pin_validated_dns("rebind.example.com", pinned_records):
        assert socket.getaddrinfo("rebind.example.com", 443) == pinned_records
        assert socket.getaddrinfo("proxy.example.com", 8080) == _addrinfo("9.9.9.9", 8080)
    assert rebind_calls == 1
    assert socket.getaddrinfo is rebinding_getaddrinfo
