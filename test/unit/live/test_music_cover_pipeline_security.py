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


def test_resolve_media_url_accepts_bilibili_bv_id():
    url, title = resolve_media_url(
        "bilibili",
        "BV1xx411c7mD",
        SystemConfig(),
        lambda _message: None,
    )

    assert url == "https://www.bilibili.com/video/BV1xx411c7mD"
    assert title == "BV1xx411c7mD"


def test_youtube_search_rejects_control_characters():
    with pytest.raises(ValueError):
        youtube_search_videos("song\n--output=/tmp/pwned")


def test_yt_dlp_download_rejects_private_media_url(tmp_path):
    with pytest.raises(ValueError):
        _run_yt_dlp_download(
            "http://169.254.169.254/latest/meta-data",
            tmp_path,
            "yt-dlp",
            lambda _message: None,
        )
