from __future__ import annotations

import hashlib
import socket
from types import SimpleNamespace

import pytest

from application.characters.voice.pipeline.bilibili_search import search_bilibili_voice_urls
from application.characters.voice.pipeline.source_acquisition import acquire_voice_sources
from application.characters.voice.pipeline.yt_dlp_extractor import (
    ensure_yt_dlp_binary,
    extract_audio_with_yt_dlp,
)


def _public_addrinfo(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port or 443))]


def test_acquire_voice_sources_blocks_loopback_private_and_non_http_urls(monkeypatch, tmp_path):
    for bad_url in (
        "http://127.0.0.1:8080/voice.wav",
        "http://localhost/voice.wav",
        "https://192.168.1.20/voice.wav",
        "ftp://example.com/voice.wav",
    ):
        with pytest.raises(ValueError):
            acquire_voice_sources(
                sources=[bad_url],
                raw_dir=tmp_path / "raw",
                project_root=tmp_path,
                gsv_root=None,
            )

    # Also reject hostnames resolving to private IPs and redirects to loopback before connecting
    monkeypatch.setattr(
        "sdk.url_safety.socket.getaddrinfo",
        lambda host, port, *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.12", port or 80))]
        if host == "rebind.example.com"
        else _public_addrinfo(host, port),
    )
    with pytest.raises(ValueError, match="内网或保留地址"):
        acquire_voice_sources(
            sources=["https://rebind.example.com/voice.wav"],
            raw_dir=tmp_path / "raw",
            project_root=tmp_path,
            gsv_root=None,
        )

    hop_calls: list[str] = []

    def redirect_to_loopback(self, url, *args, **kwargs):
        hop_calls.append(url)
        return SimpleNamespace(
            status_code=302,
            headers={"Location": "http://127.0.0.1:9880/internal.wav"},
            close=lambda: None,
        )

    monkeypatch.setattr("requests.Session.get", redirect_to_loopback)
    with pytest.raises(ValueError, match="内网或保留地址"):
        acquire_voice_sources(
            sources=["https://public.example.com/voice.wav"],
            raw_dir=tmp_path / "raw",
            project_root=tmp_path,
            gsv_root=None,
        )
    assert hop_calls == ["https://public.example.com/voice.wav"]


def test_extract_audio_with_yt_dlp_enforces_redirect_policy_and_strict_bilibili_cookie_host(monkeypatch, tmp_path):
    yt_dlp_bin = tmp_path / "yt-dlp.exe"
    yt_dlp_bin.write_bytes(b"bin")
    dest = tmp_path / "dest"
    dest.mkdir()

    monkeypatch.setattr("sdk.url_safety.socket.getaddrinfo", _public_addrinfo)
    monkeypatch.setattr(
        "requests.Session.get",
        lambda self, url, *a, **kw: SimpleNamespace(
            status_code=302,
            headers={"Location": "http://127.0.0.1:9880/ssrf"},
            close=lambda: None,
        )
        if "ssrf-redirect" in url
        else SimpleNamespace(status_code=200, headers={}, close=lambda: None),
    )

    invoked_cmds: list[list[str]] = []

    def fake_run(_label: str, cmd):
        invoked_cmds.append(list(cmd))
        raise RuntimeError("HTTP Error 412")

    # 1. Redirect to loopback must fail BEFORE yt-dlp subprocess is ever spawned
    with pytest.raises(ValueError, match="内网或保留地址"):
        extract_audio_with_yt_dlp(
            yt_dlp_bin,
            "https://public.example.com/ssrf-redirect",
            dest,
            1,
            gsv_root=None,
            max_download_seconds=60,
            run_subprocess=fake_run,
        )
    assert invoked_cmds == []

    # 2. Non-Bilibili URL containing "bilibili.com" in query string must NOT trigger Edge cookie retry
    with pytest.raises(RuntimeError, match="412"):
        extract_audio_with_yt_dlp(
            yt_dlp_bin,
            "https://evil.example.com/watch?ref=https://www.bilibili.com/video/BV1xx411c7mD",
            dest,
            1,
            gsv_root=None,
            max_download_seconds=60,
            run_subprocess=fake_run,
        )
    assert len(invoked_cmds) == 1
    assert "--cookies-from-browser" not in invoked_cmds[0]

    # 3. Genuine bilibili.com hostname DOES trigger Edge cookie fallback
    invoked_cmds.clear()
    with pytest.raises(RuntimeError, match="412"):
        extract_audio_with_yt_dlp(
            yt_dlp_bin,
            "https://www.bilibili.com/video/BV1xx411c7mD",
            dest,
            1,
            gsv_root=None,
            max_download_seconds=60,
            run_subprocess=fake_run,
        )
    assert len(invoked_cmds) == 2
    assert "--cookies-from-browser" in invoked_cmds[1]


def test_search_bilibili_voice_urls_ranks_clean_voice_compilations(monkeypatch):
    def fake_get(self, url, *args, **kwargs):
        if "finger/spi" in url:
            return SimpleNamespace(
                ok=True,
                json=lambda: {"code": 0, "data": {"b_3": "v3", "b_4": "v4"}},
            )
        return SimpleNamespace(
            ok=True,
            json=lambda: {
                "code": 0,
                "data": {
                    "result": [
                        {
                            "bvid": "BV1111111111",
                            "title": "【手书/AI翻唱】山田凉 鬼畜合集",
                            "description": "娱乐二创",
                            "duration": "02:30",
                            "play": 50000,
                        },
                        {
                            "bvid": "BV2222222222",
                            "title": "《孤独摇滚》<em class=\"keyword\">山田凉</em> 动画原声台词语音合集",
                            "description": "单人干音提取",
                            "duration": "04:15",
                            "play": 18000,
                        },
                    ]
                },
            },
        )

    monkeypatch.setattr(
        "application.characters.voice.pipeline.bilibili_search.requests.Session.get",
        fake_get,
    )
    urls = search_bilibili_voice_urls("山田凉 孤独摇滚", max_results=1)
    assert urls == ["https://www.bilibili.com/video/BV2222222222"]


def test_ensure_yt_dlp_binary_verifies_sha256_and_rejects_tampered_payload(monkeypatch, tmp_path):
    payload = b"MZ-fake-yt-dlp-standalone-binary"
    good_hash = hashlib.sha256(payload).hexdigest()

    class _FakeResp:
        def __init__(self, *, text: str = "", body: bytes = b""):
            self.text = text
            self._body = body

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=1024):
            yield self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        "application.characters.voice.pipeline.yt_dlp_extractor.shutil.which",
        lambda _name: None,
    )

    def bad_get(self, url, *args, **kwargs):
        if url.endswith("SHA2-256SUMS"):
            return _FakeResp(text=f"{'0' * 64}  yt-dlp.exe\n{'0' * 64}  yt-dlp_linux\n")
        return _FakeResp(body=payload)

    monkeypatch.setattr(
        "application.characters.voice.pipeline.yt_dlp_extractor.requests.Session.get",
        bad_get,
    )
    with pytest.raises(RuntimeError, match="SHA-256"):
        ensure_yt_dlp_binary(tmp_path)
    assert not list((tmp_path / "data" / "tools" / "yt-dlp").glob("*"))

    def good_get(self, url, *args, **kwargs):
        if url.endswith("SHA2-256SUMS"):
            return _FakeResp(
                text=(
                    f"{good_hash}  yt-dlp.exe\n"
                    f"{good_hash}  yt-dlp_linux\n"
                    f"{good_hash}  yt-dlp_macos\n"
                )
            )
        return _FakeResp(body=payload)

    monkeypatch.setattr(
        "application.characters.voice.pipeline.yt_dlp_extractor.requests.Session.get",
        good_get,
    )
    installed = ensure_yt_dlp_binary(tmp_path)
    assert installed.is_file()
    assert installed.read_bytes() == payload
