from __future__ import annotations

import os

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


def test_media_thumbnail_cache_key_tracks_file_identity_not_only_mtime_and_size(
    tmp_path,
):
    source = tmp_path / "data" / "background.bmp"
    preserved = tmp_path / "preserved.bmp"
    source.parent.mkdir()
    Image.new("RGB", (16, 16), "red").save(source)
    original = source.stat()
    first = _media_thumbnail(source, project_root=tmp_path, size=97)
    source.rename(preserved)
    Image.new("RGB", (16, 16), "blue").save(source)
    assert source.stat().st_size == original.st_size
    os.utime(
        source,
        ns=(original.st_atime_ns, original.st_mtime_ns),
    )

    second = _media_thumbnail(source, project_root=tmp_path, size=97)

    assert second != first
    with Image.open(second) as generated:
        assert generated.getpixel((0, 0)) == (0, 0, 255)


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


def test_media_thumbnail_rejects_symlinked_cache_storage(tmp_path):
    source = tmp_path / "source.png"
    external = tmp_path / "external"
    external.mkdir()
    Image.new("RGB", (16, 16), "red").save(source)
    try:
        (tmp_path / ".cache").symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic links"):
        _media_thumbnail(source, project_root=tmp_path, size=96)

    assert list(external.iterdir()) == []


def test_media_thumbnail_rejects_symlinked_cache_file_alias(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (16, 16), "red").save(source)
    thumbnail = _media_thumbnail(source, project_root=tmp_path, size=96)
    thumbnail.unlink()
    other = thumbnail.parent / "other.png"
    Image.new("RGB", (8, 8), "blue").save(other)
    try:
        thumbnail.symlink_to(other)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PermissionError, match="symbolic link"):
        _media_thumbnail(source, project_root=tmp_path, size=96)
