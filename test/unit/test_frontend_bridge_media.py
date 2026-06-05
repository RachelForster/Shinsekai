from __future__ import annotations

import pytest

from frontend_bridge_core.media import _media_thumbnail, _media_thumbnail_batch

Image = pytest.importorskip("PIL.Image")


def test_media_thumbnail_generates_cached_small_image(tmp_path):
    source = tmp_path / "data" / "background.png"
    source.parent.mkdir()
    Image.new("RGB", (800, 480), "#336699").save(source)

    thumbnail = _media_thumbnail(source, project_root=tmp_path, size=96)

    assert thumbnail.is_file()
    assert thumbnail.parent == tmp_path / ".cache" / "frontend-media-thumbnails"
    with Image.open(thumbnail) as generated:
        assert max(generated.size) <= 96
        assert generated.format == "PNG"

    assert _media_thumbnail(source, project_root=tmp_path, size=96) == thumbnail


def test_media_thumbnail_batch_returns_data_urls(tmp_path):
    source = tmp_path / "data" / "background.png"
    source.parent.mkdir()
    Image.new("RGB", (320, 240), "#663399").save(source)

    payload = _media_thumbnail_batch(
        [("data/background.png", source), ("data/background.png", source)],
        project_root=tmp_path,
        size=96,
    )

    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["path"] == "data/background.png"
    assert item["cachePath"].startswith(".cache/frontend-media-thumbnails/")
    assert item["dataUrl"].startswith("data:image/png;base64,")


def test_media_thumbnail_batch_can_return_cache_paths_without_data_urls(tmp_path):
    source = tmp_path / "data" / "background.png"
    source.parent.mkdir()
    Image.new("RGB", (320, 240), "#663399").save(source)

    payload = _media_thumbnail_batch(
        [("data/background.png", source)],
        include_data_url=False,
        project_root=tmp_path,
        size=96,
    )

    item = payload["items"][0]
    assert item["path"] == "data/background.png"
    assert item["cachePath"].startswith(".cache/frontend-media-thumbnails/")
    assert "dataUrl" not in item
