from __future__ import annotations

import pytest

from config.schema import SystemConfig
from live.music_cover_pipeline import (
    _run_yt_dlp_download,
    resolve_media_url,
    youtube_search_videos,
)


def test_resolve_media_url_rejects_youtube_lookalike_host():
    with pytest.raises(ValueError):
        resolve_media_url(
            "youtube",
            "https://youtube.com.evil.example/watch?v=abc",
            SystemConfig(),
            lambda _message: None,
        )


def test_resolve_media_url_rejects_private_direct_url():
    with pytest.raises(ValueError):
        resolve_media_url(
            "url",
            "http://127.0.0.1:8080/secret.wav",
            SystemConfig(),
            lambda _message: None,
        )


def test_resolve_media_url_accepts_public_https_youtube_url():
    url, title = resolve_media_url(
        "url",
        "https://youtu.be/abc123",
        SystemConfig(),
        lambda _message: None,
    )

    assert url == "https://youtu.be/abc123"
    assert title == "https://youtu.be/abc123"


@pytest.mark.parametrize(
    "youtube_url",
    [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtube.com/watch?v=abc123",
        "https://m.youtube.com/watch?v=abc123",
        "https://youtube-nocookie.com/embed/abc123",
        "https://www.youtube-nocookie.com/embed/abc123",
    ],
)
def test_resolve_media_url_accepts_allowed_youtube_hosts(youtube_url):
    url, title = resolve_media_url(
        "youtube",
        youtube_url,
        SystemConfig(),
        lambda _message: None,
    )

    assert url.startswith("https://")
    assert "abc123" in url
    assert title == youtube_url


def test_resolve_media_url_accepts_bilibili_bv_id():
    url, title = resolve_media_url(
        "bilibili",
        "BV1xx411c7mD",
        SystemConfig(),
        lambda _message: None,
    )

    assert url == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert title == "BV1xx411c7mD"


def test_resolve_media_url_accepts_bilibili_full_url():
    url, title = resolve_media_url(
        "bilibili",
        "https://www.bilibili.com/video/av123456",
        SystemConfig(),
        lambda _message: None,
    )

    assert url == "https://www.bilibili.com/video/av123456"
    assert title == "https://www.bilibili.com/video/av123456"


def test_youtube_search_rejects_control_characters():
    with pytest.raises(ValueError):
        youtube_search_videos("song\n--output=/tmp/pwned")


def test_youtube_search_videos_clamps_limit_and_uses_sanitized_executable(monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr("live.music_cover_pipeline.subprocess.run", fake_run)

    youtube_search_videos("test query", limit=0, yt_dlp="yt-dlp")
    youtube_search_videos("test query", limit=999, yt_dlp="yt-dlp")

    assert calls[0][0] == "yt-dlp"
    assert calls[1][0] == "yt-dlp"
    assert calls[0][1].startswith("ytsearch1:")
    assert calls[1][1].startswith("ytsearch20:")


def test_yt_dlp_download_rejects_private_media_url(tmp_path):
    with pytest.raises(ValueError):
        _run_yt_dlp_download(
            "http://169.254.169.254/latest/meta-data",
            tmp_path,
            "yt-dlp",
            lambda _message: None,
        )


def test_yt_dlp_download_passes_media_url_as_literal_argument(tmp_path, monkeypatch):
    captured = {}

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **_kwargs):
        captured["cmd"] = cmd
        (tmp_path / "song.wav").write_text("wav", encoding="utf-8")
        return Result()

    monkeypatch.setattr("live.music_cover_pipeline.subprocess.run", fake_run)

    media_url = "https://youtu.be/abc123"
    result = _run_yt_dlp_download(media_url, tmp_path, "yt-dlp", lambda _message: None)
    cmd = captured["cmd"]
    dashdash_index = cmd.index("--")

    assert result == tmp_path / "song.wav"
    assert cmd[dashdash_index + 1] == media_url
